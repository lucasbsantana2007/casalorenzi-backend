"""Clientes: equipe de atendimento (painel) ou o próprio cliente logado (área do cliente).

O id do cliente nas rotas é o CPF (11 dígitos), como no site; por dentro, a API usa o número da
tabela. O cliente só acessa o próprio CPF: o de outra pessoa aparece como inexistente (404), para
não revelar quem é cliente.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import Sessao, exigir_cliente_ou_modulo, exigir_modulo
from src.routers.atendimentos import detalhe_saida, lista_saida
from src.schemas.clientes import cliente_saida
from src.schemas.pedidos import pedido_saida
from src.use_cases import clientes
from src.utils.erros import NaoEncontrado

router = APIRouter(prefix="/clientes", tags=["Clientes"])
acesso_painel = exigir_modulo("atendimento")
acesso = exigir_cliente_ou_modulo("atendimento")


def _cliente(db: Session, sessao: Sessao, cpf: str) -> m.Cliente:
    """Cliente do CPF da rota, conferindo que o cliente logado só abre a própria conta."""
    cliente = clientes.por_cpf(db, cpf)
    if sessao.cliente is not None and sessao.cliente.id != cliente.id:
        raise NaoEncontrado("Cliente não encontrado.")
    return cliente


@router.get("")
def listar(busca: str | None = None, db: Session = Depends(get_db), _: m.Usuario = Depends(acesso_painel)):
    """Busca por nome, e-mail, telefone (até 50 resultados). Só a equipe. Usada para abrir chamado em nome do cliente."""
    return [cliente_saida(c) for c in clientes.listar(db, busca)]


@router.get("/{cliente_id}")
def obter(cliente_id: str, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    cliente = _cliente(db, sessao, cliente_id)
    total_pedidos, total_atendimentos = clientes.totais(db, cliente.id)
    return {**cliente_saida(cliente), "totalPedidos": total_pedidos, "totalAtendimentos": total_atendimentos}


@router.get("/{cliente_id}/pedidos")
def listar_pedidos(cliente_id: str, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    cliente = _cliente(db, sessao, cliente_id)
    return [pedido_saida(p) for p in clientes.pedidos(db, cliente.id)]


@router.get("/{cliente_id}/pedidos/{numero}")
def consultar_pedido(cliente_id: str, numero: str, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    """Aceita "CL-104820" ou só "104820". Pedido de outro cliente: 404."""
    cliente = _cliente(db, sessao, cliente_id)
    return pedido_saida(clientes.pedido_por_numero(db, cliente.id, numero))


@router.get("/{cliente_id}/atendimentos")
def listar_atendimentos(cliente_id: str, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    cliente = _cliente(db, sessao, cliente_id)
    return lista_saida(db, clientes.atendimentos(db, cliente.id))


@router.get("/{cliente_id}/atendimentos/{atendimento_id}")
def obter_atendimento(cliente_id: str, atendimento_id: int, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    """Chamado com a conversa e as fotos. Chamado de outro cliente: 404."""
    cliente = _cliente(db, sessao, cliente_id)
    return detalhe_saida(db, clientes.atendimento(db, cliente.id, atendimento_id))
