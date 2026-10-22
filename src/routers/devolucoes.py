"""Devoluções de peças (painel, módulo pedidos). Cada devolução volta a peça ao estoque."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.marca import na_marca
from src.middlewares.autenticacao import conferir_marca, escopo_marca, exigir_modulo
from src.schemas.devolucoes import DevolucaoEntrada, devolucao_saida
from src.use_cases import devolucoes

router = APIRouter(tags=["Pedidos"])
acesso = exigir_modulo("pedidos")


@router.post("/pedidos/{pedido_id}/devolucoes", status_code=201)
def registrar(
    pedido_id: int,
    dados: DevolucaoEntrada,
    db: Session = Depends(get_db),
    usuario: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """Devolve peças de um item do pedido ao estoque (movimentação DEVOLUCAO). Pedido cancelado ou
    ainda não enviado: 409. Quantidade acima do comprado menos o já devolvido: 422. Pedido de outra
    loja (Lojista e Operador) ou de outra marca: 404."""
    pedido = db.get(m.Pedido, pedido_id)
    if pedido is not None:
        conferir_marca(marca, pedido.loja.marca, "Pedido não encontrado.")
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
    usuario: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """de/ate em aaaa-mm-dd (inclusive). lojaId: loja em que as peças voltaram ao estoque
    (Lojista e Operador: sempre a própria loja)."""
    lista = devolucoes.listar(db, usuario, de=de, ate=ate, loja_id=lojaId)
    return [devolucao_saida(d) for d in lista if na_marca(marca, d.loja.marca)]
