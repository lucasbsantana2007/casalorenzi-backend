"""Regras de negócio usadas por mais de uma rota."""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.utils import agora


def estoque_por(db: Session, loja_id: int, variacao_id: int, travar: bool = False) -> m.Estoque | None:
    consulta = select(m.Estoque).where(m.Estoque.loja_id == loja_id, m.Estoque.variacao_id == variacao_id)
    if travar:
        consulta = consulta.with_for_update(of=m.Estoque)
    return db.scalar(consulta)


def aplicar_movimentacao(
    db: Session,
    estoque: m.Estoque,
    *,
    tipo: str,
    quantidade: int,
    origem: str,
    usuario_id: int | None,
    transferencia_id: int | None = None,
    quando: datetime | None = None,
) -> m.Movimentacao:
    """Registra a movimentação e atualiza o saldo. Nunca deixa o saldo negativo."""
    saldo = estoque.quantidade + quantidade
    if saldo < 0:
        raise HTTPException(422, f"Saldo insuficiente: há {estoque.quantidade} unidade(s) disponível(is).")
    quando = quando or agora()
    mov = m.Movimentacao(
        estoque=estoque,
        tipo=tipo,
        quantidade=quantidade,
        origem=origem,
        usuario_id=usuario_id,
        transferencia_id=transferencia_id,
        saldo_resultante=saldo,
        criado_em=quando,
    )
    db.add(mov)
    estoque.quantidade = saldo
    estoque.atualizado_em = quando
    return mov


def criar_estoques_zerados(db: Session, variacao: m.Variacao) -> None:
    """Toda variação nova passa a existir, com saldo zero, em todas as lojas."""
    for loja in db.scalars(select(m.Loja)):
        db.add(m.Estoque(loja_id=loja.id, variacao=variacao, quantidade=0, quantidade_min=2, atualizado_em=agora()))
