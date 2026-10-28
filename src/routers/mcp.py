"""Servidor MCP do copiloto (decisão 106, docs/mcp.md) e os tokens pessoais que dão acesso a ele.

POST /api/conector-mcp: o endpoint MCP (Streamable HTTP, respostas em JSON, sem sessão). Autenticação pelo token pessoal
(Authorization: Bearer clmcp_...) ou pelo acesso do login OAuth do claude.ai (clmcpa_..., decisão 114), não pelo
login do painel. GET e DELETE: 405 (não há stream nem sessão).
/api/mcp/tokens: o Administrador do grupo cria, vê e revoga os seus. O MCP é a cúpula de informação da
liderança (decisões 109 e 110): só quem vê as duas marcas; os outros usam o copiloto no painel.

Antivírus que inspecionam tráfego MCP (visto com o Avast, em 28/10/2026) reescrevem as respostas com
Content-Length das requisições com o cabeçalho MCP-Protocol-Version ou em endereços terminados em /mcp ou /sse:
tiram o Content-Length e marcam "chunked" sem o corpo estar em pedaços, e o app recusa (InvalidHTTPResponse).
Por isso as respostas daqui já saem em pedaços (Transfer-Encoding: chunked), que passam intactas, e o endpoint
não termina em /mcp. As duas coisas valem para qualquer cliente; nenhuma muda o protocolo.
"""

import json
import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src import models as m
from src.config.settings import CORS_ORIGINS
from src.database.connection import SessionLocal, get_db
from src.middlewares.autenticacao import usuario_atual
from src.routers.oauth_mcp import base
from src.schemas.comum import Entrada
from src.use_cases import oauth_mcp, tokens_mcp
from src.use_cases.assistente import servidor_mcp
from src.use_cases.assistente.servidor_mcp import ERRO_JSON, Resposta
from src.utils.erros import SemPermissao

log = logging.getLogger(__name__)
router = APIRouter(tags=["MCP (copiloto em apps de IA)"])


def acesso(usuario: m.Usuario = Depends(usuario_atual)) -> m.Usuario:
    """Só o Administrador do grupo (decisão 110); os outros perfis da equipe recebem 403."""
    if not tokens_mcp.pode_usar(usuario):
        raise SemPermissao("O acesso pelo Claude é exclusivo do Administrador do grupo.")
    return usuario


# Corpo maior que isso não é uma chamada de ferramenta do copiloto
TAMANHO_MAXIMO = 64 * 1024
SEM_TOKEN = (
    "Token MCP ausente, inválido, vencido ou revogado. Crie um em Inteligência > Conectar ao Claude e mande em "
    "Authorization: Bearer <token>."
)


class TokenEntrada(Entrada):
    nome: str = Field(min_length=1, max_length=60)


@router.get("/mcp/tokens")
def listar_tokens(db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    """Os tokens da pessoa logada (o texto do token nunca volta: só o começo, para reconhecer)."""
    return tokens_mcp.listar(db, usuario)


@router.post("/mcp/tokens", status_code=201)
def criar_token(dados: TokenEntrada, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    """Cria um token. O campo "token" é a única vez que o texto aparece: guarde-o no app que vai usar."""
    token, texto = tokens_mcp.criar(db, usuario, dados.nome)
    db.commit()
    return {**tokens_mcp.token_saida(token), "token": texto}


@router.delete("/mcp/tokens/{token_id}")
def revogar_token(token_id: int, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    """Revoga na hora: a próxima chamada com ele recebe 401."""
    token = tokens_mcp.revogar(db, usuario, token_id)
    db.commit()
    return tokens_mcp.token_saida(token)


def _origem_permitida(request: Request) -> bool:
    """Contra DNS rebinding: navegador de outro site não usa o servidor. Apps de IA (sem Origin) passam."""
    origem = request.headers.get("origin")
    if origem is None:
        return True
    if origem in CORS_ORIGINS:
        return True
    return urlsplit(origem).netloc == request.headers.get("host")


def _json(resposta: Resposta) -> Response:
    """Resposta em pedaços (Transfer-Encoding: chunked), sem Content-Length: ver a nota do antivírus no topo."""
    corpo = b"" if resposta.corpo is None else json.dumps(resposta.corpo, ensure_ascii=False).encode()
    return StreamingResponse(
        iter([corpo] if corpo else []),
        status_code=resposta.status,
        headers=resposta.cabecalhos,
        media_type="application/json" if corpo else None,
    )


def _sem_token(endereco: str) -> Resposta:
    """401 com o endereço da ficha do recurso: é por ela que o claude.ai acha o login OAuth (decisão 114)."""
    resposta = servidor_mcp.erro_jsonrpc(401, servidor_mcp.SEM_AUTORIZACAO, SEM_TOKEN)
    ficha = f"{endereco}/.well-known/oauth-protected-resource/api/conector-mcp"
    resposta.cabecalhos["WWW-Authenticate"] = (
        f'Bearer realm="casa-lorenzi-mcp", resource_metadata="{ficha}", scope="{oauth_mcp.ESCOPO}"'
    )
    return resposta


def _sem_numero_especial(valor: str):
    """NaN e Infinity não são JSON (o Python aceita, o Postgres recusa na auditoria)."""
    raise ValueError(f"{valor} não é um valor JSON")


def _ler(corpo: bytes):
    return json.loads(corpo, parse_constant=_sem_numero_especial)


def _atender(mensagem, cabecalhos: dict, texto_token: str | None, endereco: str) -> Resposta:
    with SessionLocal() as db:
        try:
            # Token pessoal (clmcp_) ou acesso do login OAuth (clmcpa_, decisão 114): os dois dão a mesma conexão
            token = tokens_mcp.autenticar(db, texto_token) or oauth_mcp.autenticar(db, texto_token, oauth_mcp.recurso(endereco))
            if token is None:
                return _sem_token(endereco)
            resposta = servidor_mcp.processar(db, mensagem, cabecalhos, token, cabecalhos.get("user-agent"))
            db.commit()
            return resposta
        except Exception:
            # Banco fora do ar ou falha não prevista: resposta JSON-RPC legível (o 500 padrão sai com Content-Length)
            db.rollback()
            log.exception("Falha no servidor MCP")
            id_ = mensagem.get("id") if isinstance(mensagem, dict) else None
            return servidor_mcp.erro_jsonrpc(
                500,
                servidor_mcp.ERRO_INTERNO,
                "Falha interna: tente de novo em instantes.",
                id_ if servidor_mcp.id_valido(id_) else None,
            )


@router.post("/conector-mcp", include_in_schema=False)
async def mcp(request: Request):
    if not _origem_permitida(request):
        return _json(servidor_mcp.erro_jsonrpc(403, servidor_mcp.SEM_AUTORIZACAO, "Origem não permitida."))
    autorizacao = request.headers.get("authorization", "")
    esquema, _, texto_token = autorizacao.partition(" ")
    texto_token = texto_token.strip() if esquema.lower() == "bearer" else None
    endereco = base(request)
    if not texto_token:
        return _json(_sem_token(endereco))
    corpo = await request.body()
    if len(corpo) > TAMANHO_MAXIMO:
        return _json(servidor_mcp.erro_jsonrpc(413, servidor_mcp.PEDIDO_INVALIDO, "Mensagem grande demais."))
    try:
        mensagem = _ler(corpo)
    except (ValueError, RecursionError):  # JSON quebrado, NaN/Infinity, aninhado demais
        return _json(servidor_mcp.erro_jsonrpc(400, ERRO_JSON, "Corpo não é um JSON válido."))
    cabecalhos = {chave.lower(): valor for chave, valor in request.headers.items()}
    return _json(await run_in_threadpool(_atender, mensagem, cabecalhos, texto_token, endereco))


@router.api_route("/conector-mcp", methods=["GET", "DELETE"], include_in_schema=False)
def mcp_sem_stream():
    """Sem stream do servidor e sem sessão (MCP 2026-07-28; os clientes de 2025 aceitam o 405)."""
    return _json(Resposta(405, cabecalhos={"Allow": "POST"}))
