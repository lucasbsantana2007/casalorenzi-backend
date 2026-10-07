"""Configurações da conta do cliente (só o próprio cliente, pelo token): ver e editar os dados,
trocar a senha e excluir a conta.

- O CPF não muda: identifica a conta. Trocar o e-mail (que é o login) pede a senha atual.
- Excluir a conta pede a senha. Os dados pessoais são apagados e a conta deixa de entrar; os
  pedidos e chamados continuam, anônimos, porque o financeiro e o fiscal precisam deles.
"""

from sqlalchemy.orm import Session

from src import models as m
from src.entities.cliente import SENHA_MINIMA, email_valido, normalizar_email
from src.repositories import cliente_repository, sessao, usuario_repository
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos
from src.utils.seguranca import confere_hash, gerar_hash

SENHA_INCORRETA = "A senha atual está incorreta."
NOME_EXCLUIDO = "Cliente excluído"


def _conferir_senha(cliente: m.Cliente, senha: str | None, mensagem: str = SENHA_INCORRETA) -> None:
    # 422 (não 401): o site trata 401 como sessão vencida
    if not senha or not confere_hash(senha, cliente.senha_hash):
        raise DadosInvalidos(mensagem)


def atualizar(
    db: Session, cliente: m.Cliente, *, nome: str, email: str, telefone: str, senha_atual: str | None = None
) -> m.Cliente:
    nome = (nome or "").strip()
    email = normalizar_email(email)
    telefone = (telefone or "").strip()
    if not nome:
        raise DadosInvalidos("Informe o nome completo.")
    if len(nome) > 120:
        raise DadosInvalidos("O nome deve ter no máximo 120 caracteres.")
    if not email_valido(email):
        raise DadosInvalidos("Informe um e-mail válido.")
    if len(telefone) > 30:
        raise DadosInvalidos("Telefone inválido.")
    if email != cliente.email:
        if not senha_atual:
            raise DadosInvalidos("Para trocar o e-mail, confirme com a sua senha atual.")
        _conferir_senha(cliente, senha_atual)
        outro = cliente_repository.por_email(db, email)
        if (outro is not None and outro.id != cliente.id) or usuario_repository.por_email(db, email) is not None:
            raise Conflito("Já existe uma conta com este e-mail.")
    cliente.nome, cliente.email, cliente.telefone = nome, email, telefone
    sessao.confirmar(db, cliente)
    return cliente


def trocar_senha(db: Session, cliente: m.Cliente, *, senha_atual: str, senha: str, confirmacao: str) -> None:
    """Também invalida os links de "Esqueceu a senha?" ainda pendentes."""
    _conferir_senha(cliente, senha_atual)
    if len(senha or "") < SENHA_MINIMA:
        raise DadosInvalidos(f"A nova senha deve ter pelo menos {SENHA_MINIMA} caracteres.")
    if senha != (confirmacao or ""):
        raise DadosInvalidos("As senhas não conferem.")
    if confere_hash(senha, cliente.senha_hash):
        raise DadosInvalidos("A nova senha deve ser diferente da atual.")
    cliente.senha_hash = gerar_hash(senha)
    momento = agora()
    for link in cliente_repository.tokens_senha_pendentes(db, cliente_id=cliente.id):
        link.usado_em = momento
    sessao.confirmar(db)


def excluir(db: Session, cliente: m.Cliente, *, senha: str) -> None:
    """Apaga os dados pessoais e encerra o acesso (o token deixa de valer na hora)."""
    _conferir_senha(cliente, senha, "Senha incorreta. Confirme com a sua senha para excluir a conta.")
    momento = agora()
    for link in cliente_repository.tokens_senha_pendentes(db, cliente_id=cliente.id):
        link.usado_em = momento
    cliente.nome = NOME_EXCLUIDO
    cliente.email = f"excluido-{cliente.id}@contas-excluidas.invalid"  # único e impossível de receber e-mail
    cliente.telefone = None
    cliente.cpf = None
    cliente.senha_hash = None
    cliente.loja_preferida_id = None
    cliente.excluido_em = momento
    sessao.confirmar(db)
