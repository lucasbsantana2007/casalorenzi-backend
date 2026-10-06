"""Devoluções de peças (painel, módulo pedidos). Cada devolução volta a peça ao estoque."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.schemas.devolucoes import DevolucaoEntrada, devolucao_saida
from src.use_cases import devolucoes

router = APIRouter(tags=["Pedidos"])
acesso = exigir_modulo("pedidos")


@router.post("/pedidos/{pedido_id}/devolucoes", status_code=201)
def registrar(pedido_id: int, dados: DevolucaoEntrada, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    """Devolve peças de um item do pedido ao estoque (movimentação DEVOLUCAO). Pedido cancelado ou
    ainda não enviado: 409. Quantidade acima do comprado menos o já devolvido: 422."""
    d = devolucoes.registrar(
        db,
        pedido_id,
        usuario,
        item_pedido_id=dados.item_pedido_id,
        variacao_id=dados.item_variacao_id,
        quantidade=dados.quantidade,
        motivo=dados.motivo,
        atendimento_id=dados.atendimento_id,
        loja_id=dados.loja_id,
    )
    return devolucao_saida(d)


@router.get("/devolucoes")
def listar(
    de: str | None = None,
    ate: str | None = None,
    lojaId: int | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
):
    """de/ate em aaaa-mm-dd (inclusive). lojaId: loja em que as peças voltaram ao estoque."""
    return [devolucao_saida(d) for d in devolucoes.listar(db, de=de, ate=ate, loja_id=lojaId)]
