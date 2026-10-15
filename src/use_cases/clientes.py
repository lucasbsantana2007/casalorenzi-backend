"""Clientes: vistos pela equipe no painel e, com a própria conta, pelo cliente na área do cliente.
Quem pode ver o quê é conferido na rota (o cliente só acessa o próprio id)."""

from sqlalchemy.orm import Session

from src import models as m
from src.entities.cliente import cpf_do_id, cpf_valido, email_valido, normalizar_email, telefone_e164
from src.repositories import atendimento_repository, cliente_repository, pedido_repository
from src.utils.erros import DadosInvalidos, NaoEncontrado


def listar(db: Session, busca: str | None = None) -> list[m.Cliente]:
    """Busca por nome, e-mail ou telefone (até 50 resultados)."""
    return cliente_repository.listar(db, busca)


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


def unificado(
    db: Session, cpf: str | None = None, email: str | None = None, telefone: str | None = None
) -> list[tuple[m.Cliente, list[m.Pedido], m.ContaPontos | None]]:
    """A mesma pessoa nas duas marcas: busca por CPF, e-mail e/ou telefone (qualquer máscara) e devolve
    cada cliente encontrado com os pedidos da Casa Lorenzi e da Vulto e a conta Vulto+. Vários
    parâmetros que apontam para clientes diferentes devolvem todos (a equipe vê a divergência)."""
    if not any(v and v.strip() for v in (cpf, email, telefone)):
        raise DadosInvalidos("Informe CPF, e-mail ou telefone.")
    encontrados: dict[int, m.Cliente] = {}
    if cpf and cpf.strip():
        if not cpf_valido(cpf):
            raise DadosInvalidos("CPF inválido.")
        if (cliente := cliente_repository.por_cpf(db, cpf_do_id(cpf))) is not None:
            encontrados[cliente.id] = cliente
    if email and email.strip():
        if not email_valido(email):
            raise DadosInvalidos("E-mail inválido.")
        if (cliente := cliente_repository.por_email(db, normalizar_email(email))) is not None:
            encontrados[cliente.id] = cliente
    if telefone and telefone.strip():
        if (numero := telefone_e164(telefone)) is None:
            raise DadosInvalidos("Telefone inválido: informe com DDD.")
        encontrados.update({c.id: c for c in cliente_repository.por_telefone(db, numero)})
    return [
        (c, pedido_repository.do_cliente(db, c.id), cliente_repository.conta_pontos(db, c.id))
        for c in sorted(encontrados.values(), key=lambda c: c.id)
        if c.excluido_em is None
    ]
