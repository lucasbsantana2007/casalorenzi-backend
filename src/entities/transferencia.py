"""Fluxo de transferência entre lojas:

SOLICITADA → EM_TRANSITO (baixa na origem) → CONCLUIDA (entrada no destino)
SOLICITADA → CANCELADA
"""

STATUS_TRANSFERENCIA = ("SOLICITADA", "EM_TRANSITO", "CONCLUIDA", "CANCELADA")
PENDENTES = ("SOLICITADA", "EM_TRANSITO")

TRANSICOES = {
    ("SOLICITADA", "EM_TRANSITO"),
    ("EM_TRANSITO", "CONCLUIDA"),
    ("SOLICITADA", "CANCELADA"),
}


def pode_mudar(de: str, para: str) -> bool:
    return (de, para) in TRANSICOES


def codigo(transferencia_id: int) -> str:
    return f"TRF-{transferencia_id:04d}"
