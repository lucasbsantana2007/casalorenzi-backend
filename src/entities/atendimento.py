"""Atendimento (chamado do cliente) e suas mensagens.

Canal por onde o cliente falou: SITE (chamado aberto no site ou pelo painel, o único da Casa Lorenzi)
e os da ferramenta à parte que a Vulto usava (WhatsApp, Instagram e e-mail). Atendimento de um canal
externo pode não ter cliente identificado: aí fica o contato (telefone, e-mail ou @) que ele usou.
"""

from datetime import datetime, timedelta
from urllib.parse import quote

STATUS_ATENDIMENTO = ("ABERTO", "EM_ANDAMENTO", "AGUARDANDO_CLIENTE", "CONCLUIDO")
CANAIS_ATENDIMENTO = ("SITE", "WHATSAPP", "INSTAGRAM", "EMAIL")
CANAL_ATENDIMENTO_PADRAO = "SITE"
EM_ABERTO = ("ABERTO", "EM_ANDAMENTO", "AGUARDANDO_CLIENTE")
AUTOR_MENSAGEM = ("CLIENTE", "ATENDENTE", "SISTEMA")
DESCRICAO_MINIMA = 10


def protocolo(atendimento_id: int) -> str:
    return f"ATD-{26000 + atendimento_id * 37:06d}"


def link_whatsapp(numero: str, protocolo_atendimento: str, assunto: str | None = None) -> str:
    """Link wa.me que abre a conversa com o atendimento já com a mensagem escrita: o protocolo leva a
    equipe ao chamado (com o resumo da conversa do assistente) sem perguntar de novo. numero: só dígitos,
    com DDI e DDD (5511999999999)."""
    texto = f"Olá! Vim do assistente do site. Protocolo {protocolo_atendimento}."
    if assunto and assunto.strip():
        texto += f"\nAssunto: {' '.join(assunto.split())[:200]}"
    return f"https://wa.me/{numero}?text={quote(texto)}"


def aguardando_equipe_desde(mensagens: list[tuple[str, datetime]]) -> datetime | None:
    """Desde quando o cliente espera a equipe: a primeira mensagem dele depois da última resposta da equipe.
    mensagens: (autor_tipo, enviado_em) em ordem; as do SISTEMA não contam. None quando a última é da equipe."""
    desde = None
    for autor, quando in mensagens:
        if autor == "ATENDENTE":
            desde = None
        elif autor == "CLIENTE" and desde is None:
            desde = quando
    return desde


def atrasado(desde: datetime | None, agora: datetime, minutos: int) -> bool:
    return desde is not None and agora - desde > timedelta(minutes=minutos)


def status_apos_mensagem(status_atual: str, autor_tipo: str) -> str:
    """Resposta da equipe deixa o caso aguardando o cliente; resposta do cliente o reabre."""
    if autor_tipo == "ATENDENTE" and status_atual in EM_ABERTO:
        return "AGUARDANDO_CLIENTE"
    if autor_tipo == "CLIENTE" and status_atual == "AGUARDANDO_CLIENTE":
        return "EM_ANDAMENTO"
    return status_atual
