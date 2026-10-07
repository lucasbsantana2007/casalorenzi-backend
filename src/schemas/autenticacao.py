from src import models as m
from src.entities.papeis import CLIENTE
from src.schemas.comum import Entrada, usuario_saida


class LoginEntrada(Entrada):
    email: str
    senha: str


class CadastroClienteEntrada(Entrada):
    """Campos com valor padrão: o use case devolve a mensagem certa em português em vez do 422 genérico."""

    nome: str = ""
    cpf: str = ""
    email: str = ""
    telefone: str = ""
    senha: str = ""
    senha_confirmacao: str = ""


class EsqueciSenhaEntrada(Entrada):
    email: str = ""


class RedefinirSenhaEntrada(Entrada):
    token: str = ""
    senha: str = ""
    senha_confirmacao: str = ""


def conta_saida(conta: m.Usuario | m.Cliente) -> dict:
    """Usuário da sessão no formato que o frontend guarda: { id, nome, email, papel, lojaId }.
    Para o cliente, papel "CLIENTE" e o CPF junto; nunca inclui o hash da senha."""
    if isinstance(conta, m.Cliente):
        # Para o site, o id do cliente é o CPF (o número interno da tabela não sai da API)
        return {"id": conta.cpf, "nome": conta.nome, "email": conta.email, "papel": CLIENTE, "lojaId": None, "cpf": conta.cpf}
    return usuario_saida(conta)
