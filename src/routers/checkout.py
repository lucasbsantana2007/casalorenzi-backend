"""Checkout da loja: o cliente compra logado na própria conta. Regras em src/use_cases/checkout.py."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import cliente_atual
from src.schemas.pedidos import CheckoutEntrada, pedido_publico_saida
from src.use_cases import checkout

router = APIRouter(tags=["Loja"])


@router.post("/checkout", status_code=201)
def finalizar_compra(dados: CheckoutEntrada, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """Cria o pedido do cliente logado (pagamento simulado, aprovado). Preços e frete são recalculados
    aqui. Sem sessão de cliente: 401. Item esgotado: 409."""
    return pedido_publico_saida(checkout.finalizar_compra(db, cliente, dados))
