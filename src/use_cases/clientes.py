"""Clientes: vistos pela equipe no painel e, com a própria conta, pelo cliente na área do cliente.
Quem pode ver o quê é conferido na rota (o cliente só acessa o próprio id)."""

from datetime import timedelta

from sqlalchemy.orm import Session

from src import models as m
from src.config.settings import LINK_SENHA_NA_RESPOSTA
from src.entities.cliente import cpf_do_id, email_valido, normalizar_email
from src.integrations import modelos_email
from src.integrations.email import enviar as enviar_email
from src.repositories import atendimento_repository, cliente_repository, pedido_repository, sessao, usuario_repository
from src.utils.erros import Conflito, DadosInvalidos, NaoEncontrado

# Link do primeiro acesso enviado pelo atendimento: o cliente pode demorar a ver o e-mail
VALIDADE_PRIMEIRO_ACESSO = timedelta(days=7)


def listar(db: Session, busca: str | None = None, dados_validos: bool | None = None) -> list[m.Cliente]:
    """Busca por nome, e-mail ou telefone (até 50 resultados). Com dados_validos, filtra pelo cadastro
    completo (True) ou com algo a corrigir (False) e traz todos: é a lista de quem contatar."""
    if dados_validos is None:
        return cliente_repository.listar(db, busca)
    return [c for c in cliente_repository.listar(db, busca, limite=None) if c.dados_validos == dados_validos]


def por_cpf(db: Session, cpf: str | int) -> m.Cliente:
    """Cliente pelo id público (CPF). Conta excluída (sem CPF) não aparece."""
    cliente = cliente_repository.por_cpf(db, cpf_do_id(cpf))
    if cliente is None:
        raise NaoEncontrado("Cliente não encontrado.")
    return cliente


def obter(db: Session, cliente_id: int) -> m.Cliente:
    cliente = cliente_repository.por_id(db, cliente_id)
    if cliente is None:
        raise NaoEncontrado("Cliente não encontrado.")
    return cliente


def pedidos(db: Session, cliente_id: int) -> list[m.Pedido]:
    obter(db, cliente_id)
    return pedido_repository.do_cliente(db, cliente_id)


def atendimentos(db: Session, cliente_id: int) -> list[m.Atendimento]:
    obter(db, cliente_id)
    return atendimento_repository.do_cliente(db, cliente_id)


def totais(db: Session, cliente_id: int) -> tuple[int, int]:
    """(pedidos, atendimentos) do cliente."""
    return pedido_repository.contar_do_cliente(db, cliente_id), atendimento_repository.contar_do_cliente(db, cliente_id)


def atendimento(db: Session, cliente_id: int, atendimento_id: int) -> m.Atendimento:
    """Chamado do cliente. De outro cliente: aparece como inexistente (404)."""
    a = atendimento_repository.obter(db, atendimento_id)
    if a is None or a.cliente_id != cliente_id:
        raise NaoEncontrado("Solicitação não encontrada.")
    return a


def pedido_por_numero(db: Session, cliente_id: int, numero: str) -> m.Pedido:
    """Aceita "CL-104820", "cl 104820" ou só "104820". Só pedidos do próprio cliente."""
    termo = "".join(c for c in (numero or "") if c.isdigit())
    pedido = pedido_repository.do_cliente_por_numero(db, cliente_id, f"CL-{termo}") if termo else None
    if pedido is None:
        raise NaoEncontrado("Não encontramos um pedido com esse número.")
    return pedido


def liberar_acesso(db: Session, cliente: m.Cliente, email: str | None) -> str | None:
    """O atendimento cadastra (ou confirma) o e-mail do cliente e manda o link para ele criar a senha.
    É o caminho de quem não tem e-mail no cadastro (747 clientes que vieram só do sistema de pontos da
    Vulto): depois disso, ele entra com o CPF ou o e-mail. Devolve o link só na demonstração."""
    from src.use_cases.autenticacao import criar_link_senha  # evita import circular

    email = normalizar_email(email)
    if not email_valido(email):
        raise DadosInvalidos("Informe um e-mail válido.")
    if email != cliente.email and (
        cliente_repository.email_em_uso(db, email, exceto_id=cliente.id) or usuario_repository.por_email(db, email) is not None
    ):
        raise Conflito("Este e-mail já é de outra conta.")
    cliente.email = email
    link = criar_link_senha(db, VALIDADE_PRIMEIRO_ACESSO, cliente=cliente)
    sessao.confirmar(db)
    enviar_email(modelos_email.nova_senha(email, cliente.nome, link))
    return link if LINK_SENHA_NA_RESPOSTA else None
