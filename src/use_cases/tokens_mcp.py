"""Tokens pessoais do servidor MCP (decisões 106, 109 e 110): só o Administrador do grupo (o que vê as duas
marcas; hoje, a Helena) cria os seus no painel
(Inteligência > Conectar ao Claude), cola no app que vai usar (Claude Code, Claude Desktop, n8n) e revoga quando
quiser.

O token em si aparece uma vez, na criação; o banco guarda só o sha256. Ele não carrega permissão nenhuma: a
cada chamada, o servidor lê o dono e usa o papel, a marca e a conta ativa dele naquele momento. Quem for
desativado ou deixar de ser Administrador do grupo perde o MCP na hora, sem precisar revogar.
"""

import hashlib
import json
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from src import models as m
from src.config import settings
from src.entities.marca import GRUPO
from src.entities.papeis import ACESSO
from src.repositories import token_mcp_repository as repo
from src.use_cases.assistente.ferramentas import Execucao
from src.utils.datas import agora, ms
from src.utils.erros import Conflito, DadosInvalidos, NaoEncontrado

# Começo fixo: quem achar o token num arquivo ou log sabe de onde ele é (e o que revogar)
PREFIXO = "clmcp_"
# Gravar o último uso a cada chamada seria uma escrita por consulta; uma vez por minuto basta para a tela
_INTERVALO_ULTIMO_USO = timedelta(minutes=1)

ATIVO, VENCIDO, REVOGADO = "ATIVO", "VENCIDO", "REVOGADO"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def situacao(token: m.TokenMcp) -> str:
    if token.revogado_em is not None:
        return REVOGADO
    if token.expira_em <= agora():
        return VENCIDO
    return ATIVO


def token_saida(token: m.TokenMcp, chamadas: int = 0) -> dict:
    return {
        "id": token.id,
        "nome": token.nome,
        "prefixo": token.prefixo,
        "situacao": situacao(token),
        "criadoEm": ms(token.criado_em),
        "expiraEm": ms(token.expira_em),
        "ultimoUsoEm": ms(token.ultimo_uso_em),
        "revogadoEm": ms(token.revogado_em),
        "chamadas": chamadas,
    }


def listar(db: Session, usuario: m.Usuario) -> list[dict]:
    tokens = repo.do_usuario(db, usuario.id)
    chamadas = repo.chamadas_por_token(db, [t.id for t in tokens])
    return [token_saida(t, chamadas.get(t.id, 0)) for t in tokens]


def criar(db: Session, usuario: m.Usuario, nome: str) -> tuple[m.TokenMcp, str]:
    """Novo token para a pessoa logada. Devolve o registro e o token em texto (a única vez que ele aparece)."""
    nome = " ".join(nome.split())
    if not nome:
        raise DadosInvalidos("Dê um nome ao token (ex.: Claude Code do notebook).")
    momento = agora()
    repo.travar_usuario(db, usuario.id)  # dois pedidos ao mesmo tempo não passam juntos do limite
    if repo.ativos_do_usuario(db, usuario.id, momento) >= settings.MCP_TOKENS_POR_USUARIO:
        raise Conflito(
            f"Você já tem {settings.MCP_TOKENS_POR_USUARIO} tokens ativos. Revogue um que não usa mais antes de criar outro."
        )
    texto = PREFIXO + secrets.token_urlsafe(32)
    token = m.TokenMcp(
        usuario_id=usuario.id,
        nome=nome[:60],
        hash=_hash(texto),
        prefixo=texto[:12],
        criado_em=momento,
        expira_em=momento + timedelta(days=settings.MCP_TOKEN_VALIDADE_DIAS),
    )
    db.add(token)
    db.flush()
    return token, texto


def revogar(db: Session, usuario: m.Usuario, token_id: int) -> m.TokenMcp:
    """Só a própria pessoa revoga os seus (de outra pessoa: 404). Revogar de novo não muda nada."""
    token = db.get(m.TokenMcp, token_id)
    if token is None or token.usuario_id != usuario.id:
        raise NaoEncontrado("Token não encontrado.")
    if token.revogado_em is None:
        token.revogado_em = agora()
    return token


def pode_usar(usuario: m.Usuario) -> bool:
    """O MCP é do Administrador do grupo (decisão 110): papel Administrador e as duas marcas, com a conta ativa."""
    return bool(usuario.ativo) and usuario.papel in ACESSO["administracao"] and usuario.marca == GRUPO


def autenticar(db: Session, texto: str | None) -> m.TokenMcp | None:
    """Token válido de um Administrador do grupo ativo; senão None (o servidor responde 401)."""
    if not texto or not texto.startswith(PREFIXO) or len(texto) > 100:
        return None
    token = repo.por_hash(db, _hash(texto))
    if token is None or situacao(token) != ATIVO:
        return None
    usuario = token.usuario
    if not pode_usar(usuario):
        return None
    momento = agora()
    if token.ultimo_uso_em is None or momento - token.ultimo_uso_em >= _INTERVALO_ULTIMO_USO:
        token.ultimo_uso_em = momento
    return token


def registrar_chamada(db: Session, token: m.TokenMcp, execucao: Execucao, cliente: str | None) -> None:
    argumentos = execucao.argumentos
    if argumentos is None:
        argumentos = {}
    elif not isinstance(argumentos, dict):
        argumentos = {"valor": str(argumentos)[:200]}
    serializado = json.dumps(argumentos, ensure_ascii=False, default=str)
    if len(serializado) > 2000:  # o app pode mandar qualquer coisa: a auditoria guarda só o começo
        argumentos = {"truncado": serializado[:2000]}
    db.add(
        m.ChamadaMcp(
            token_id=token.id,
            usuario_id=token.usuario_id,
            ferramenta=execucao.nome,
            argumentos=argumentos,
            sucesso=execucao.sucesso,
            erro=(execucao.erro or None) and execucao.erro[:255],
            duracao_ms=execucao.duracao_ms,
            cliente=(cliente or None) and cliente[:80],
            criada_em=agora(),
        )
    )
