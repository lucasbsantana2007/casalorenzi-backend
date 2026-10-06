"""Pagamentos dos pedidos (painel, módulo pedidos)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.schemas.pagamentos import pagamento_saida
from src.use_cases import pagamentos

router = APIRouter(tags=["Pedidos"])


@router.get("/pedidos/{pedido_id}/pagamentos")
def listar_do_pedido(pedido_id: int, db: Session = Depends(get_db), _: m.Usuario = Depends(exigir_modulo("pedidos"))):
    return [pagamento_saida(p) for p in pagamentos.listar_do_pedido(db, pedido_id)]
