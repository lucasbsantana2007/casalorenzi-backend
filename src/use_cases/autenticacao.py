"""Login único (equipe e clientes), cadastro da conta do cliente e "esqueci a senha".

- O mesmo /auth/login serve aos dois: o e-mail é procurado primeiro na equipe e depois nos
  clientes com conta. A mensagem de erro é a mesma para e-mail inexistente e senha errada.
- A conta do cliente nasce no checkout (CPF + e-mail + senha) e já devolve a sessão.
- "Esqueci a senha" responde igual exista ou não a conta, e o link vale 30 minutos, uma vez.
"""

import logging
import secrets

from sqlalchemy.orm import Session

from src import models as m
from src.config.settings import LINK_SENHA_NA_RESPOSTA
from src.entities.cliente import (
    SENHA_MINIMA,
    VALIDADE_TOKEN_SENHA,
    cpf_valido,
    email_valido,
    normalizar_email,
    somente_digitos_cpf,
)
from src.entities.papeis import CLIENTE
from src.repositories import cliente_repository, sessao, usuario_repository
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos, Expirado, NaoAutenticado, SemPermissao
from src.utils.seguranca import confere_hash, criar_token, gerar_hash

log = logging.getLogger("casalorenzi")

CREDENCIAIS_INVALIDAS = "E-mail ou senha incorretos."
CONVITE_PENDENTE = "Esta conta ainda não tem senha. Use o link do convite enviado por e-mail para criá-la."
CAMINHO_NOVA_SENHA = "/login/nova-senha"


def sessao_do_cliente(cliente: m.Cliente) -> str:
    return criar_token(cliente.id, CLIENTE)


def entrar(db: Session, email: str, senha: str) -> tuple[str, m.Usuario | m.Cliente]:
    """(token, conta). A conta é um m.Usuario (equipe) ou um m.Cliente."""
    usuario = usuario_repository.por_email(db, email)
    if usuario is not None:
        if usuario.convite_pendente and usuario.ativo:
            raise NaoAutenticado(CONVITE_PENDENTE)
        if not confere_hash(senha, usuario.senha_hash):
            raise NaoAutenticado(CREDENCIAIS_INVALIDAS)
        # Só depois da senha certa, para não revelar quem é da equipe
        if not usuario.ativo:
            raise SemPermissao("Esta conta está desativada. Fale com o administrador.")
        return criar_token(usuario.id, usuario.papel), usuario
    cliente = cliente_repository.por_email(db, email)
    if cliente is None or not confere_hash(senha, cliente.senha_hash):
        raise NaoAutenticado(CREDENCIAIS_INVALIDAS)
    return sessao_do_cliente(cliente), cliente


def _validar_senha(senha: str | None, confirmacao: str | None) -> str:
    senha = senha or ""
    if len(senha) < SENHA_MINIMA:
        raise DadosInvalidos(f"A senha deve ter pelo menos {SENHA_MINIMA} caracteres.")
    if senha != (confirmacao or ""):
        raise DadosInvalidos("As senhas não conferem.")
    return senha


def cadastrar_cliente(
    db: Session, *, nome: str, cpf: str, email: str, telefone: str, senha: str, senha_confirmacao: str
) -> tuple[str, m.Cliente]:
    """Cria a conta do cliente e devolve a sessão. CPF ou e-mail já cadastrados: 409."""
    nome = (nome or "").strip()
    cpf = somente_digitos_cpf(cpf)
    email = normalizar_email(email)
    if not nome:
        raise DadosInvalidos("Informe o nome completo.")
    if len(nome) > 120:
        raise DadosInvalidos("O nome deve ter no máximo 120 caracteres.")
    if not cpf_valido(cpf):
        raise DadosInvalidos("CPF inválido.")
    if not email_valido(email):
        raise DadosInvalidos("Informe um e-mail válido.")
    senha = _validar_senha(senha, senha_confirmacao)
    telefone = (telefone or "").strip()
    if len(telefone) > 30:
        raise DadosInvalidos("Telefone inválido.")

    if cliente_repository.por_cpf(db, cpf) is not None:
        raise Conflito("Já existe uma conta com este CPF. Entre com o seu e-mail e senha.")
    if usuario_repository.por_email(db, email) is not None or cliente_repository.por_email(db, email) is not None:
        # Inclui clientes antigos (sem conta) com este e-mail: eles criam a senha pelo "esqueci a senha"
        raise Conflito("Já existe uma conta com este e-mail. Entre com o seu e-mail e senha.")

    cliente = cliente_repository.criar(db, nome=nome, email=email, telefone=telefone, cpf=cpf, senha_hash=gerar_hash(senha))
    sessao.confirmar(db, cliente)
    return sessao_do_cliente(cliente), cliente


def solicitar_nova_senha(db: Session, email: str | None) -> str | None:
    """Gera o link de troca para a conta do e-mail (equipe ou cliente). A resposta da rota é a mesma
    exista ou não a conta. O link sai no log (ainda não há envio de e-mail) e só volta na resposta
    com LINK_SENHA_NA_RESPOSTA=true (demonstração)."""
    alvo = normalizar_email(email)
    if not email_valido(alvo):
        raise DadosInvalidos("Informe um e-mail válido.")
    usuario = usuario_repository.por_email(db, alvo)
    cliente = None if usuario is not None else cliente_repository.por_email(db, alvo)
    if (usuario is None and cliente is None) or (usuario is not None and not usuario.ativo):
        return None
    link = criar_link_senha(db, VALIDADE_TOKEN_SENHA, usuario=usuario, cliente=cliente)
    sessao.confirmar(db)
    log.info("Link de troca de senha para %s: %s", alvo, link)
    return link if LINK_SENHA_NA_RESPOSTA else None


def criar_link_senha(db: Session, validade, *, usuario: m.Usuario | None = None, cliente: m.Cliente | None = None) -> str:
    """Link de uso único para criar ou trocar a senha (esqueci a senha e convite de funcionário novo), sem confirmar."""
    token = secrets.token_urlsafe(32)
    cliente_repository.criar_token_senha(db, token, agora() + validade, usuario=usuario, cliente=cliente)
    return f"{CAMINHO_NOVA_SENHA}?token={token}"


def redefinir_senha(db: Session, token: str | None, senha: str | None, confirmacao: str | None) -> str:
    """Define a senha nova e invalida este e os demais links pendentes da conta. Devolve o e-mail.
    Cliente antigo (sem conta) que troca a senha passa a entrar pelo login; funcionário novo que
    cria a senha pelo convite passa a entrar no painel."""
    momento = agora()
    registro = cliente_repository.token_senha(db, (token or "").strip(), travar=True) if token else None
    if registro is None or registro.usado_em is not None or registro.expira_em < momento:
        raise Expirado('Este link expirou ou já foi usado. Peça um novo em "Esqueceu a senha?".')
    senha = _validar_senha(senha, confirmacao)
    conta = registro.usuario or registro.cliente
    conta.senha_hash = gerar_hash(senha)
    pendentes = cliente_repository.tokens_senha_pendentes(db, usuario_id=registro.usuario_id, cliente_id=registro.cliente_id)
    for link in pendentes:
        link.usado_em = momento
    sessao.confirmar(db)
    return conta.email
