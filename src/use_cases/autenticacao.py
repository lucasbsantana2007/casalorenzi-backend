"""Login único (equipe e clientes), cadastro da conta do cliente e "esqueci a senha".

- O mesmo /auth/login serve aos dois: o e-mail é procurado primeiro na equipe e depois nos
  clientes com conta. O cliente também entra pelo CPF (decisão 53 da Vulto: há clientes sem e-mail
  e famílias com o mesmo e-mail). A mensagem de erro é a mesma para conta inexistente e senha errada.
- A conta do cliente nasce no checkout (CPF + e-mail + senha) e já devolve a sessão.
- "Esqueci a senha" responde igual exista ou não a conta, e o link vale 30 minutos, uma vez.
"""

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
from src.entities.pedido import CANAL_ECOMMERCE
from src.integrations import modelos_email
from src.integrations.email import enviar as enviar_email
from src.repositories import cliente_repository, sessao, usuario_repository
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos, Expirado, NaoAutenticado, SemPermissao
from src.utils.seguranca import confere_hash, criar_token, gerar_hash

CREDENCIAIS_INVALIDAS = "E-mail, CPF ou senha incorretos."
CONVITE_PENDENTE = "Esta conta ainda não tem senha. Use o link do convite enviado por e-mail para criá-la."
CAMINHO_NOVA_SENHA = "/login/nova-senha"


def sessao_do_cliente(cliente: m.Cliente) -> str:
    return criar_token(cliente.id, CLIENTE)


def cliente_pelo_login(db: Session, login: str | None) -> m.Cliente | None:
    """O cliente do e-mail (se só um cliente usa esse e-mail) ou do CPF (com ou sem máscara)."""
    login = (login or "").strip()
    if "@" in login:
        return cliente_repository.por_email(db, login)
    cpf = somente_digitos_cpf(login)
    return cliente_repository.por_cpf(db, cpf) if len(cpf) == 11 else None


def entrar(db: Session, email: str, senha: str) -> tuple[str, m.Usuario | m.Cliente]:
    """(token, conta). `email` aceita o e-mail ou, para cliente, o CPF. A conta é um m.Usuario ou um m.Cliente."""
    usuario = usuario_repository.por_email(db, email) if "@" in (email or "") else None
    if usuario is not None:
        if usuario.convite_pendente and usuario.ativo:
            raise NaoAutenticado(CONVITE_PENDENTE)
        if not confere_hash(senha, usuario.senha_hash):
            raise NaoAutenticado(CREDENCIAIS_INVALIDAS)
        # Só depois da senha certa, para não revelar quem é da equipe
        if not usuario.ativo:
            raise SemPermissao("Esta conta está desativada. Fale com o administrador.")
        return criar_token(usuario.id, usuario.papel), usuario
    cliente = cliente_pelo_login(db, email)
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
    if usuario_repository.por_email(db, email) is not None or cliente_repository.email_em_uso(db, email):
        # Inclui clientes antigos (sem conta) com este e-mail: eles criam a senha pelo "esqueci a senha"
        raise Conflito("Já existe uma conta com este e-mail. Entre com o seu e-mail e senha.")

    cliente = cliente_repository.criar(
        db, nome=nome, email=email, telefone=telefone, cpf=cpf, senha_hash=gerar_hash(senha), canal_cadastro=CANAL_ECOMMERCE
    )
    sessao.confirmar(db, cliente)
    return sessao_do_cliente(cliente), cliente


def solicitar_nova_senha(db: Session, email: str | None) -> str | None:
    """Gera o link de troca para a conta do e-mail ou do CPF (cliente) e manda para o e-mail da conta.
    A resposta da rota é a mesma exista ou não a conta. Cliente sem e-mail não recebe link: o atendimento
    cadastra o e-mail dele (POST /clientes/{cpf}/acesso). O link só volta na resposta com
    LINK_SENHA_NA_RESPOSTA=true (demonstração)."""
    alvo = (email or "").strip()
    if "@" in alvo:
        alvo = normalizar_email(alvo)
        if not email_valido(alvo):
            raise DadosInvalidos("Informe um e-mail válido.")
    elif len(somente_digitos_cpf(alvo)) != 11:
        raise DadosInvalidos("Informe o e-mail ou o CPF da conta.")
    usuario = usuario_repository.por_email(db, alvo) if "@" in alvo else None
    cliente = None if usuario is not None else cliente_pelo_login(db, alvo)
    if cliente is not None and not cliente.email:
        return None
    if (usuario is None and cliente is None) or (usuario is not None and not usuario.ativo):
        return None
    link = criar_link_senha(db, VALIDADE_TOKEN_SENHA, usuario=usuario, cliente=cliente)
    sessao.confirmar(db)
    conta = usuario or cliente
    enviar_email(modelos_email.nova_senha(conta.email, conta.nome, link))
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
