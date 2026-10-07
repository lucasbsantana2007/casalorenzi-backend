"""Links absolutos para arquivos servidos pela API (ex.: foto do produto), que o site usa direto
no <img>. A base vem de URL_PUBLICA_API ou, sem ela, do endereço da requisição atual."""

from contextvars import ContextVar

from src.config.settings import URL_PUBLICA_API

_base_da_requisicao: ContextVar[str] = ContextVar("base_da_requisicao", default="")


def definir_base(url: str) -> None:
    """Chamada pelo middleware a cada requisição."""
    _base_da_requisicao.set(url.rstrip("/"))


def url_da_api(caminho: str) -> str:
    """caminho começa com "/" e já sem o prefixo /api. Ex.: url_da_api("/produtos/4/imagem")."""
    return f"{URL_PUBLICA_API or _base_da_requisicao.get()}/api{caminho}"
