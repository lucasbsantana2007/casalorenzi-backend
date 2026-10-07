"""Limite de tentativas por janela de tempo (ex.: "esqueci a senha"), contra abuso e envio em massa.

Fica na memória do processo: vale para um servidor só e zera quando a API reinicia. Basta para o
deploy atual (uma instância); com mais de uma, o contador precisaria ir para o banco ou um Redis.
"""

import threading
import time
from collections import defaultdict, deque

from src.utils.erros import MuitasTentativas

MENSAGEM = "Muitas tentativas seguidas. Aguarde alguns minutos e tente de novo."

_tentativas: dict[str, deque[float]] = defaultdict(deque)
_trava = threading.Lock()


def conferir(*chaves: str, maximo: int, janela_segundos: int) -> None:
    """Conta uma tentativa em cada chave (ex.: e-mail e IP). Se alguma já chegou ao máximo dentro da
    janela, recusa com 429 sem contar."""
    agora = time.monotonic()
    with _trava:
        filas = [_tentativas[chave] for chave in chaves]
        for fila in filas:
            while fila and agora - fila[0] > janela_segundos:
                fila.popleft()
        if any(len(fila) >= maximo for fila in filas):
            raise MuitasTentativas(MENSAGEM)
        for fila in filas:
            fila.append(agora)


def limpar() -> None:
    """Zera todos os contadores (usado nos testes)."""
    with _trava:
        _tentativas.clear()
