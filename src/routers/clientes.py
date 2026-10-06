"""Clientes no painel (equipe de atendimento). Cliente não tem login nem rotas próprias aqui."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.routers.atendimentos import lista_saida
from src.schemas.clientes import cliente_saida
from src.schemas.pedidos import pedido_saida
from src.use_cases import clientes

router = APIRouter(prefix="/clientes", tags=["Clientes"])
acesso = exigir_modulo("atendimento")


@router.get("")
def listar(busca: str | None = None, db: Session = Depends(get_db), _: m.Usuario = Depends(acesso)):
    """Busca por nome, e-mail ou telefone (até 50 resultados). Usada para abrir chamado em nome do cliente."""
    return [cliente_saida(c) for c in clientes.listar(db, busca)]


@router.get("/{cliente_id}")
def obter(cliente_id: int, db: Session = Depends(get_db), _: m.Usuario = Depends(acesso)):
    cliente = clientes.obter(db, cliente_id)
    total_pedidos, total_atendimentos = clientes.totais(db, cliente_id)
    return {**cliente_saida(cliente), "totalPedidos": total_pedidos, "totalAtendimentos": total_atendimentos}


@router.get("/{cliente_id}/pedidos")
def listar_pedidos(cliente_id: int, db: Session = Depends(get_db), _: m.Usuario = Depends(acesso)):
    return [pedido_saida(p) for p in clientes.pedidos(db, cliente_id)]


@router.get("/{cliente_id}/atendimentos")
def listar_atendimentos(cliente_id: int, db: Session = Depends(get_db), _: m.Usuario = Depends(acesso)):
    return lista_saida(db, clientes.atendimentos(db, cliente_id))
