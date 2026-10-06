"""Erros esperados: fazem parte das regras do sistema e já nascem com a resposta definida.

Os use cases levantam estes erros sem saber nada de HTTP; o app.py traduz cada um
para o status code certo e devolve { "detail": "mensagem" } (padrão do FastAPI).
"""


class ErroDeNegocio(Exception):
    status_code = 400

    def __init__(self, mensagem: str):
        super().__init__(mensagem)
        self.mensagem = mensagem


class NaoAutenticado(ErroDeNegocio):
    status_code = 401


class SemPermissao(ErroDeNegocio):
    status_code = 403


class NaoEncontrado(ErroDeNegocio):
    status_code = 404


class Conflito(ErroDeNegocio):
    """A operação não combina com o estado atual (ex.: enviar um pedido já cancelado)."""

    status_code = 409


class Expirado(ErroDeNegocio):
    """O recurso existiu, mas não vale mais (ex.: link de troca de PIN vencido)."""

    status_code = 410


class DadosInvalidos(ErroDeNegocio):
    status_code = 422


class MuitasTentativas(ErroDeNegocio):
    status_code = 429
