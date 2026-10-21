"""Atendimento (chamado do cliente) e suas mensagens.

Canal por onde o cliente falou: SITE (chamado aberto no site ou pelo painel, o único da Casa Lorenzi)
e os da ferramenta à parte que a Vulto usava (WhatsApp, Instagram e e-mail). Atendimento de um canal
externo pode não ter cliente identificado: aí fica o contato (telefone, e-mail ou @) que ele usou.
"""

STATUS_ATENDIMENTO = ("ABERTO", "EM_ANDAMENTO", "AGUARDANDO_CLIENTE", "CONCLUIDO")
CANAIS_ATENDIMENTO = ("SITE", "WHATSAPP", "INSTAGRAM", "EMAIL")
CANAL_ATENDIMENTO_PADRAO = "SITE"
EM_ABERTO = ("ABERTO", "EM_ANDAMENTO", "AGUARDANDO_CLIENTE")
AUTOR_MENSAGEM = ("CLIENTE", "ATENDENTE", "SISTEMA")
DESCRICAO_MINIMA = 10


def protocolo(atendimento_id: int) -> str:
    return f"ATD-{26000 + atendimento_id * 37:06d}"


def status_apos_mensagem(status_atual: str, autor_tipo: str) -> str:
    """Resposta da equipe deixa o caso aguardando o cliente; resposta do cliente o reabre."""
    if autor_tipo == "ATENDENTE" and status_atual in EM_ABERTO:
        return "AGUARDANDO_CLIENTE"
    if autor_tipo == "CLIENTE" and status_atual == "AGUARDANDO_CLIENTE":
        return "EM_ANDAMENTO"
    return status_atual
