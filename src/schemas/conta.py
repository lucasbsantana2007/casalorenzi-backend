from src import models as m
from src.schemas.comum import Entrada


class DadosContaEntrada(Entrada):
    nome: str = ""
    email: str = ""
    telefone: str = ""
    # Só quando o e-mail muda (o e-mail é o login)
    senha_atual: str | None = None


class TrocaSenhaEntrada(Entrada):
    senha_atual: str = ""
    senha: str = ""
    senha_confirmacao: str = ""


class ExclusaoContaEntrada(Entrada):
    senha: str = ""


def conta_saida(cliente: m.Cliente) -> dict:
    """Dados que o próprio cliente vê e edita (nunca hashes nem controle de tentativas)."""
    return {
        "id": cliente.cpf,
        "nome": cliente.nome,
        "email": cliente.email,
        "cpf": cliente.cpf,
        "telefone": cliente.telefone or "",
        "clienteDesde": cliente.cliente_desde.isoformat() if cliente.cliente_desde else None,
    }
