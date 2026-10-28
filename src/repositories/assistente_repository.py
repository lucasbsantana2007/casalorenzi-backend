"""Conversas, mensagens, auditoria das consultas e consumo dos assistentes de IA."""

from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, aliased

from src import models as m
from src.utils.erros import Conflito


def obter(db: Session, conversa_id: str, tipo: str) -> m.ConversaAssistente | None:
    return db.scalar(
        select(m.ConversaAssistente).where(m.ConversaAssistente.id == conversa_id, m.ConversaAssistente.tipo == tipo)
    )


def travar(db: Session, conversa_id: str) -> None:
    """Uma mensagem por vez em cada conversa: a segunda, enviada enquanto a primeira é respondida, recebe 409
    (sem esperar a trava, para não segurar a requisição)."""
    try:
        db.execute(select(m.ConversaAssistente.id).where(m.ConversaAssistente.id == conversa_id).with_for_update(nowait=True))
    except OperationalError:
        db.rollback()
        raise Conflito("Ainda estou respondendo a mensagem anterior. Aguarde um instante.") from None


def mensagens(db: Session, conversa_id: str, limite: int | None = None) -> list[m.MensagemAssistente]:
    """Em ordem cronológica; com limite, as mais recentes."""
    consulta = (
        select(m.MensagemAssistente)
        .where(m.MensagemAssistente.conversa_id == conversa_id)
        .order_by(m.MensagemAssistente.criada_em.desc(), m.MensagemAssistente.id.desc())
    )
    if limite:
        consulta = consulta.limit(limite)
    return list(reversed(list(db.scalars(consulta))))


def mensagem(db: Session, conversa_id: str, mensagem_id: int) -> m.MensagemAssistente | None:
    return db.scalar(
        select(m.MensagemAssistente).where(
            m.MensagemAssistente.conversa_id == conversa_id, m.MensagemAssistente.id == mensagem_id
        )
    )


def por_id_cliente(db: Session, conversa_id: str, id_cliente: str) -> m.MensagemAssistente | None:
    """A mensagem do usuário com esse identificador (reenvio), se já existe."""
    return db.scalar(
        select(m.MensagemAssistente).where(
            m.MensagemAssistente.conversa_id == conversa_id, m.MensagemAssistente.id_cliente == id_cliente
        )
    )


def resposta_a(db: Session, mensagem_id: int) -> m.MensagemAssistente | None:
    return db.scalar(select(m.MensagemAssistente).where(m.MensagemAssistente.responde_a_id == mensagem_id).limit(1))


def do_usuario(db: Session, usuario_id: int, limite: int = 30) -> list[m.ConversaAssistente]:
    """Conversas do copiloto de um membro da equipe, das mais recentes."""
    consulta = (
        select(m.ConversaAssistente)
        .where(m.ConversaAssistente.usuario_id == usuario_id, m.ConversaAssistente.tipo == "GERENCIAL")
        .order_by(m.ConversaAssistente.atualizada_em.desc())
        .limit(limite)
    )
    return list(db.scalars(consulta))


def contar_mensagens(db: Session, conversa_ids: list[str]) -> dict[str, int]:
    if not conversa_ids:
        return {}
    linhas = db.execute(
        select(m.MensagemAssistente.conversa_id, func.count())
        .where(m.MensagemAssistente.conversa_id.in_(conversa_ids), m.MensagemAssistente.papel == "USUARIO")
        .group_by(m.MensagemAssistente.conversa_id)
    )
    return dict(linhas.all())


def apagar_expiradas(db: Session, agora: datetime) -> int:
    """Retenção: apaga as conversas vencidas (as mensagens e a auditoria vão junto; o consumo fica)."""
    resultado = db.execute(delete(m.ConversaAssistente).where(m.ConversaAssistente.expira_em < agora))
    return resultado.rowcount or 0


# ---------- Métricas de uso ----------


def consumo_desde(db: Session, desde: datetime) -> list:
    """(dia, tipo, modelo, status, chamadas, tokens de entrada, saída, cache lido, cache escrito, custo, ms médio)."""
    dia = func.date_trunc("day", m.ConsumoIA.criado_em).label("dia")
    consulta = (
        select(
            dia,
            m.ConsumoIA.tipo,
            m.ConsumoIA.modelo,
            m.ConsumoIA.status,
            func.count().label("chamadas"),
            func.coalesce(func.sum(m.ConsumoIA.tokens_entrada), 0).label("entrada"),
            func.coalesce(func.sum(m.ConsumoIA.tokens_saida), 0).label("saida"),
            func.coalesce(func.sum(m.ConsumoIA.tokens_cache_leitura), 0).label("cache_leitura"),
            func.coalesce(func.sum(m.ConsumoIA.tokens_cache_escrita), 0).label("cache_escrita"),
            func.coalesce(func.sum(m.ConsumoIA.custo_estimado), 0).label("custo"),
            func.coalesce(func.avg(m.ConsumoIA.duracao_ms), 0).label("duracao"),
        )
        .where(m.ConsumoIA.criado_em >= desde)
        .group_by(dia, m.ConsumoIA.tipo, m.ConsumoIA.modelo, m.ConsumoIA.status)
        .order_by(dia)
    )
    return list(db.execute(consulta))


def respostas_desde(db: Session, desde: datetime) -> list:
    """(tipo da conversa, modo, quantidade) das respostas dos assistentes."""
    consulta = (
        select(m.ConversaAssistente.tipo, m.MensagemAssistente.modo, func.count())
        .join(m.ConversaAssistente, m.ConversaAssistente.id == m.MensagemAssistente.conversa_id)
        .where(m.MensagemAssistente.papel == "ASSISTENTE", m.MensagemAssistente.criada_em >= desde)
        .group_by(m.ConversaAssistente.tipo, m.MensagemAssistente.modo)
    )
    return list(db.execute(consulta))


def qualidade_desde(db: Session, desde: datetime) -> list:
    """(tipo da conversa, auditoria, avaliação, comentário, avaliada em, pergunta) das respostas com auditoria ou
    avaliação do cliente."""
    pergunta = aliased(m.MensagemAssistente)
    consulta = (
        select(
            m.ConversaAssistente.tipo,
            m.MensagemAssistente.auditoria,
            m.MensagemAssistente.avaliacao,
            m.MensagemAssistente.avaliacao_comentario,
            m.MensagemAssistente.avaliada_em,
            pergunta.conteudo,
        )
        .join(m.ConversaAssistente, m.ConversaAssistente.id == m.MensagemAssistente.conversa_id)
        .outerjoin(pergunta, pergunta.id == m.MensagemAssistente.responde_a_id)
        .where(
            m.MensagemAssistente.papel == "ASSISTENTE",
            m.MensagemAssistente.criada_em >= desde,
            or_(m.MensagemAssistente.auditoria.isnot(None), m.MensagemAssistente.avaliacao.isnot(None)),
        )
        .order_by(m.MensagemAssistente.id)
    )
    return list(db.execute(consulta))


def conversas_desde(db: Session, desde: datetime) -> list:
    """(tipo, status, quantidade) das conversas abertas desde o instante."""
    consulta = (
        select(m.ConversaAssistente.tipo, m.ConversaAssistente.status, func.count())
        .where(m.ConversaAssistente.criada_em >= desde)
        .group_by(m.ConversaAssistente.tipo, m.ConversaAssistente.status)
    )
    return list(db.execute(consulta))


def ferramentas_desde(db: Session, desde: datetime) -> list:
    """(ferramenta, sucesso, quantidade, ms médio) das consultas feitas pelos assistentes."""
    consulta = (
        select(
            m.ChamadaFerramenta.ferramenta,
            m.ChamadaFerramenta.sucesso,
            func.count(),
            func.coalesce(func.avg(m.ChamadaFerramenta.duracao_ms), 0),
        )
        .where(m.ChamadaFerramenta.criada_em >= desde)
        .group_by(m.ChamadaFerramenta.ferramenta, m.ChamadaFerramenta.sucesso)
    )
    return list(db.execute(consulta))
