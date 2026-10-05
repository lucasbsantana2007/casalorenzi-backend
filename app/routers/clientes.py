"""Portal do cliente. O cliente só acessa o próprio id; administradores e lojistas, qualquer um."""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Atendimento, Pedido, Usuario
from app.routers.atendimentos import carregar_atendimento
from app.security import garantir_acesso_cliente, usuario_atual
from app.utils import normalizar
from app.views import atendimento_detalhado, atendimentos_view, pedido_view

router = APIRouter(prefix="/clientes", tags=["Portal do cliente"])


def _cliente(db: Session, cliente_id: int, usuario: Usuario) -> Usuario:
    garantir_acesso_cliente(usuario, cliente_id)
    cliente = db.get(Usuario, cliente_id)
    if cliente is None or cliente.papel != "CLIENTE":
        raise HTTPException(404, "Cliente não encontrado.")
    return cliente


@router.get("/{cliente_id}")
def obter_perfil(cliente_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)):
    cliente = _cliente(db, cliente_id, usuario)
    return {"id": cliente.id, "nome": cliente.nome, "email": cliente.email}


@router.get("/{cliente_id}/atendimentos")
def listar_solicitacoes(cliente_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)):
    _cliente(db, cliente_id, usuario)
    atendimentos = db.scalars(
        select(Atendimento)
        .where(Atendimento.solicitante_id == cliente_id)
        .order_by(Atendimento.criado_em.desc(), Atendimento.id)
    ).all()
    return atendimentos_view(db, list(atendimentos))


@router.get("/{cliente_id}/atendimentos/{atendimento_id}")
def obter_solicitacao(
    cliente_id: int, atendimento_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)
):
    _cliente(db, cliente_id, usuario)
    atendimento = carregar_atendimento(db, atendimento_id, usuario)
    if atendimento.solicitante_id != cliente_id:
        raise HTTPException(404, "Solicitação não encontrada.")
    return atendimento_detalhado(db, atendimento)


def _pedidos(cliente_id: int):
    return select(Pedido).options(selectinload(Pedido.itens)).where(Pedido.cliente_id == cliente_id)


@router.get("/{cliente_id}/pedidos")
def listar_pedidos(cliente_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)):
    _cliente(db, cliente_id, usuario)
    pedidos = db.scalars(_pedidos(cliente_id).order_by(Pedido.criado_em.desc(), Pedido.id))
    return [pedido_view(p) for p in pedidos]


def _so_numero(numero: str) -> str:
    """Aceita 'CL-104820', 'cl104820' ou apenas '104820'."""
    return re.sub(r"^cl-?", "", re.sub(r"\s", "", normalizar(numero)))


@router.get("/{cliente_id}/pedidos/{numero}")
def consultar_pedido(
    cliente_id: int, numero: str, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)
):
    """Só encontra pedidos do próprio cliente."""
    _cliente(db, cliente_id, usuario)
    termo = _so_numero(numero)
    for pedido in db.scalars(_pedidos(cliente_id)):
        if _so_numero(pedido.numero) == termo:
            return pedido_view(pedido)
    raise HTTPException(404, "Não encontramos um pedido com esse número.")
