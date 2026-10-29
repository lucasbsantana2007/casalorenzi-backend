"""Servidor MCP do copiloto (decisões 106 e 109, docs/mcp.md): as ferramentas do copiloto gerencial para apps de IA
de fora do painel (Claude Code, Claude Desktop, n8n, claude.ai), com as mesmas regras do painel. Para toda a equipe
com acesso ao Assistente IA (decisão 115): cada um vê o que o seu papel e a sua marca permitem.

O que vale aqui é o mesmo do copiloto: só leitura, permissão por papel e marca de quem é dono do token, conferida
a cada chamada, parâmetros validados pelo mesmo contrato (campo a mais é recusado) e valores já formatados. Fica de
fora tudo que é do cliente (pedidos, pontos, devoluções): nenhum dado pessoal sai por aqui. O saldo do Lupe+ de um
cliente (consultar_pontos_cliente) fica só no copiloto do painel (decisão 120). A diferença é quem
escreve a resposta final: o modelo do app da pessoa, e não o nosso; por isso o verificador de números não roda, e
as instruções do servidor pedem para copiar os valores como vieram.

Protocolo (MCP sobre Streamable HTTP, sem SSE e sem sessão), nas duas gerações em uso:
- 2026-07-28 ("moderna"): cada requisição traz a versão e as capacidades do cliente em params._meta, e os
  cabeçalhos MCP-Protocol-Version, Mcp-Method e Mcp-Name repetem o corpo (se não batem: 400, HeaderMismatch).
  server/discover diz as versões, as capacidades e as instruções.
- 2025-03-26 a 2025-11-25 ("legada"): o cliente abre com initialize; depois manda a versão no cabeçalho
  MCP-Protocol-Version (sem ele, vale 2025-03-26). Não há sessão: cada POST se resolve sozinho.
O SDK oficial (`mcp`) não entrou: este módulo cobre o que o servidor usa (ferramentas) sem dependência nova.
"""

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from src import models as m
from src.entities import assistente as regra
from src.entities.assistente import DEFINICOES
from src.entities.marca import marca_do_escopo
from src.entities.papeis import ACESSO, pode_acessar
from src.middlewares import limite
from src.repositories import cadastro_repository
from src.use_cases import analises, tokens_mcp
from src.use_cases.assistente import ferramentas_gerenciais
from src.use_cases.assistente.ferramentas import (
    ROTULO_MODULO,
    ROTULO_PAPEL,
    Contexto,
    Entrada,
    Execucao,
    Ferramenta,
    Resultado,
    executar,
    motivo_da_recusa,
    registro_de,
)
from src.use_cases.assistente.formatacao import cru, data
from src.use_cases.assistente.prompts import NOME_MARCA, agora_texto
from src.utils.erros import MuitasTentativas

VERSAO_MODERNA = "2026-07-28"
VERSOES_LEGADAS = ("2025-11-25", "2025-06-18", "2025-03-26")
VERSOES = (VERSAO_MODERNA, *VERSOES_LEGADAS)
# Cliente legado que não manda MCP-Protocol-Version (as versões antes de 2025-06-18 não tinham o cabeçalho)
VERSAO_SEM_CABECALHO = "2025-03-26"
SERVIDOR = {"name": "casa-lorenzi-copiloto", "title": "Casa Lorenzi e Vulto: copiloto gerencial", "version": "1.0.0"}
META = "io.modelcontextprotocol/"
CAPACIDADES = {"tools": {"listChanged": False}}

# Códigos JSON-RPC (os -320xx são os definidos pela especificação do MCP)
ERRO_JSON, PEDIDO_INVALIDO, METODO_INEXISTENTE, PARAMETROS_INVALIDOS, ERRO_INTERNO = -32700, -32600, -32601, -32602, -32603
CABECALHO_DIVERGENTE, VERSAO_NAO_SUPORTADA = -32020, -32022
# Token ou origem recusados (código da aplicação, fora da faixa reservada ao JSON-RPC e ao MCP)
SEM_AUTORIZACAO = -31001

INSTRUCOES = (
    "Dados reais da plataforma Casa Lorenzi e Vulto (varejo de moda), só leitura, com as mesmas regras e permissões "
    "do painel. Comece por ver_contexto: ele diz a data de hoje, até quando há vendas registradas, as lojas (com os "
    "ids que as ferramentas pedem), as categorias e o que este usuário pode consultar. Os valores já vêm formatados: "
    "copie-os como vieram, sem somar, arredondar ou calcular por conta própria, e diga o período e a definição da "
    "métrica usados. Número que não veio de uma ferramenta não é dado da empresa. Aqui não há dados de clientes "
    "individuais, só números agregados: para um cliente específico, indique o painel (Atendimento > Lupe+). "
    "Responda em português."
)
LIMITE_DE_CONSULTAS = "LIMITE_DE_CONSULTAS: muitas consultas seguidas com este token. Aguarde alguns minutos."


class _SemParametros(Entrada):
    pass


def _ver_contexto(db: Session, ctx: Contexto, _: BaseModel) -> Resultado:
    usuario = db.get(m.Usuario, ctx.usuario_id)
    modulos = [
        modulo
        for modulo in ("financeiro", "fidelidade", "pedidos", "atendimento", "estoque", "transferencias")
        if modulo in ACESSO
    ]
    marcas = [NOME_MARCA[ctx.marca_escopo]] if ctx.marca_escopo else list(NOME_MARCA.values())
    dados = {
        "agora": agora_texto(),
        "usuario": usuario.nome if usuario else None,
        "papel": ROTULO_PAPEL.get(ctx.papel, ctx.papel),
        "marcasQuePodeVer": marcas,
        "podeConsultar": [ROTULO_MODULO[mod] for mod in modulos if pode_acessar(ctx.papel, mod)],
        "semAcessoA": [ROTULO_MODULO[mod] for mod in modulos if not pode_acessar(ctx.papel, mod)],
        "vendasRegistradasAte": data(analises.dados_ate(db, ctx.marca_escopo)),
        "lojas": [
            {"id": loja["id"], "nome": loja["nome"], "marca": NOME_MARCA[loja["marca"]], "tipo": loja["tipo"]}
            for loja in ferramentas_gerenciais.lojas_do_contexto(db, ctx.marca_escopo)
        ],
        "categorias": cadastro_repository.nomes_categorias(db),
        "definicoes": DEFINICOES,
    }
    return Resultado(dados=dados)


VER_CONTEXTO = Ferramenta(
    "ver_contexto",
    "Data e hora de agora, até quando há vendas registradas, as lojas e o CD (id, nome, marca e tipo), as categorias, "
    "o que este usuário pode consultar e a definição de cada métrica. Use antes das outras ferramentas.",
    _SemParametros,
    _ver_contexto,
)
# Fica só no painel: consulta com dado pessoal de cliente não sai para apps de fora (decisão 120, volta à 106)
SO_NO_PAINEL = {"consultar_pontos_cliente"}
FERRAMENTAS = [VER_CONTEXTO, *(f for f in ferramentas_gerenciais.FERRAMENTAS if f.nome not in SO_NO_PAINEL)]
REGISTRO = registro_de(FERRAMENTAS)
_ANOTACOES = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}


@dataclass
class Resposta:
    """O que o roteador devolve: status HTTP e, se houver, o corpo JSON-RPC."""

    status: int
    corpo: dict | None = None
    cabecalhos: dict = field(default_factory=dict)


def contexto(token: m.TokenMcp) -> Contexto:
    """Quem pergunta é o dono do token, com o papel e a marca de hoje (o Administrador do grupo vê as duas)."""
    usuario = token.usuario
    return Contexto(
        tipo=regra.GERENCIAL,
        conversa_id=f"mcp-{token.id}",
        origem="MCP",
        usuario_id=usuario.id,
        papel=usuario.papel,
        marca_escopo=marca_do_escopo(usuario.marca, None),
    )


def descricao(ferramenta: Ferramenta) -> dict:
    esquema = ferramenta.esquema()["input_schema"]
    esquema.setdefault("type", "object")
    return {
        "name": ferramenta.nome,
        "title": ferramenta.nome.replace("_", " ").capitalize(),
        "description": ferramenta.descricao,
        "inputSchema": esquema,
        "annotations": _ANOTACOES,
    }


def ferramentas_do(ctx: Contexto) -> list[Ferramenta]:
    """As que o perfil pode usar, sempre na mesma ordem (o app pode guardar a lista)."""
    return [f for f in FERRAMENTAS if motivo_da_recusa(f, ctx) is None]


def erro_jsonrpc(status: int, codigo: int, mensagem: str, id_=None, dados: Any = None) -> Resposta:
    erro: dict = {"code": codigo, "message": mensagem}
    if dados is not None:
        erro["data"] = dados
    corpo: dict = {"jsonrpc": "2.0", "error": erro}
    if id_ is not None:
        corpo["id"] = id_
    return Resposta(status, corpo)


def _nao_suportada(id_, pedida) -> Resposta:
    return erro_jsonrpc(
        400, VERSAO_NAO_SUPORTADA, "Unsupported protocol version", id_, {"supported": list(VERSOES), "requested": pedida}
    )


def _decodificar(valor: str | None) -> str | None:
    """Mcp-Name pode vir em base64 (=?base64?...?=) quando o nome não cabe num cabeçalho."""
    if valor and valor.startswith("=?base64?") and valor.endswith("?="):
        try:
            return base64.b64decode(valor[9:-2], validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            return None
    return valor


def id_valido(id_) -> bool:
    return (isinstance(id_, str) or isinstance(id_, int)) and not isinstance(id_, bool)


def processar(
    db: Session, mensagem: Any, cabecalhos: Mapping[str, str], token: m.TokenMcp, agente: str | None = None
) -> Resposta:
    """Uma mensagem JSON-RPC já autenticada (o roteador conferiu o token e a origem). cabecalhos: chaves minúsculas."""
    if isinstance(mensagem, list):
        return erro_jsonrpc(400, PEDIDO_INVALIDO, "Lotes de mensagens (batch) não são aceitos: mande uma por requisição.")
    if not isinstance(mensagem, dict) or mensagem.get("jsonrpc") != "2.0":
        return erro_jsonrpc(400, PEDIDO_INVALIDO, "Mensagem JSON-RPC 2.0 inválida.")
    metodo = mensagem.get("method")
    if "id" not in mensagem:
        # Notificação (notifications/initialized, notifications/cancelled...) ou resposta: aceita, sem corpo
        return (
            Resposta(202)
            if isinstance(metodo, str) or "result" in mensagem or "error" in mensagem
            else erro_jsonrpc(400, PEDIDO_INVALIDO, "Mensagem JSON-RPC 2.0 inválida.")
        )
    id_ = mensagem["id"]
    if not id_valido(id_) or not isinstance(metodo, str):
        if not isinstance(metodo, str) and ("result" in mensagem or "error" in mensagem):
            return Resposta(202)  # resposta do cliente a algo que nunca pedimos: ignorada
        return erro_jsonrpc(400, PEDIDO_INVALIDO, "Requisição sem id válido ou sem método.", id_ if id_valido(id_) else None)
    parametros = mensagem.get("params")
    if parametros is None:
        parametros = {}
    if not isinstance(parametros, dict):
        return erro_jsonrpc(400, PARAMETROS_INVALIDOS, "params precisa ser um objeto.", id_)

    if metodo == "initialize":
        pedida = parametros.get("protocolVersion")
        resultado = {
            "protocolVersion": pedida if pedida in VERSOES_LEGADAS else VERSOES_LEGADAS[0],
            "capabilities": CAPACIDADES,
            "serverInfo": SERVIDOR,
            "instructions": INSTRUCOES,
        }
        return Resposta(200, {"jsonrpc": "2.0", "id": id_, "result": resultado})

    meta = parametros.get("_meta")
    versao_meta = meta.get(META + "protocolVersion") if isinstance(meta, dict) else None
    cabecalho_versao = cabecalhos.get("mcp-protocol-version")
    if versao_meta is not None and versao_meta not in VERSOES_LEGADAS:
        moderna = True
        if versao_meta != VERSAO_MODERNA:
            return _nao_suportada(id_, versao_meta)
        if cabecalho_versao != versao_meta:
            return erro_jsonrpc(400, CABECALHO_DIVERGENTE, "Header mismatch: MCP-Protocol-Version", id_)
        if cabecalhos.get("mcp-method") != metodo:
            return erro_jsonrpc(400, CABECALHO_DIVERGENTE, "Header mismatch: Mcp-Method", id_)
        if metodo in ("tools/call", "resources/read", "prompts/get"):
            nome = parametros.get("name") if metodo != "resources/read" else parametros.get("uri")
            if _decodificar(cabecalhos.get("mcp-name")) != nome:
                return erro_jsonrpc(400, CABECALHO_DIVERGENTE, "Header mismatch: Mcp-Name", id_)
        if not isinstance(meta.get(META + "clientCapabilities"), dict):
            return erro_jsonrpc(400, PARAMETROS_INVALIDOS, f"Falta _meta['{META}clientCapabilities'].", id_)
        info = meta.get(META + "clientInfo")
        if isinstance(info, dict) and isinstance(info.get("name"), str):
            agente = info["name"]
    else:
        moderna = False
        # Versão de 2025 (no cabeçalho ou, por engano, em _meta): atendida sem as regras da 2026-07-28
        versao = cabecalho_versao or versao_meta or VERSAO_SEM_CABECALHO
        if versao == VERSAO_MODERNA:
            return erro_jsonrpc(400, PARAMETROS_INVALIDOS, f"Falta _meta['{META}protocolVersion'].", id_)
        if versao not in VERSOES_LEGADAS:
            return _nao_suportada(id_, versao)

    ctx = contexto(token)
    if metodo == "ping":
        resultado: dict = {}
    elif metodo == "server/discover" and moderna:
        resultado = {"supportedVersions": list(VERSOES), "capabilities": CAPACIDADES, "instructions": INSTRUCOES}
    elif metodo == "tools/list":
        resultado = {"tools": [descricao(f) for f in ferramentas_do(ctx)]}
    elif metodo == "tools/call":
        nome = parametros.get("name")
        if not isinstance(nome, str) or nome not in REGISTRO:
            return erro_jsonrpc(200, PARAMETROS_INVALIDOS, f"Unknown tool: {str(nome)[:60]}", id_)
        resultado = _chamar(db, token, ctx, nome, parametros.get("arguments"), agente)
    else:
        return erro_jsonrpc(404 if moderna else 200, METODO_INEXISTENTE, f"Method not found: {metodo[:60]}", id_)

    if moderna:
        resultado = {"resultType": "complete", **resultado, "_meta": {META + "serverInfo": SERVIDOR}}
    return Resposta(200, {"jsonrpc": "2.0", "id": id_, "result": resultado})


def _chamar(db: Session, token: m.TokenMcp, ctx: Contexto, nome: str, argumentos: Any, agente: str | None) -> dict:
    """Roda a ferramenta pelo mesmo executor do copiloto e registra a chamada. Erro da consulta (sem permissão,
    parâmetro inválido, banco fora) volta como resultado com isError, para o modelo do app poder corrigir."""
    maximo, janela = regra.LIMITE_POR_CONVERSA[regra.GERENCIAL]
    try:
        limite.conferir(f"mcp:token:{token.id}", maximo=maximo, janela_segundos=janela)
    except MuitasTentativas:
        execucao = Execucao(nome, argumentos, None, LIMITE_DE_CONSULTAS, 0, negada=True, origem=ctx.origem)
    else:
        execucao = executar(REGISTRO, nome, argumentos, ctx)
    tokens_mcp.registrar_chamada(db, token, execucao, agente)
    if not execucao.sucesso:
        return {"content": [{"type": "text", "text": execucao.erro}], "isError": True}
    dados = cru(execucao.resultado.dados)
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    return {"content": [{"type": "text", "text": texto}], "structuredContent": dados, "isError": False}
