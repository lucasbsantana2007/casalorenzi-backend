"""Estoque é controlado por LOJA + VARIAÇÃO (SKU); todo saldo vem das movimentações."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.marca import na_marca
from src.middlewares.autenticacao import conferir_marca, escopo_marca, exigir_modulo
from src.schemas.estoque import MovimentacaoEntrada, estoque_saida, movimentacao_saida
from src.use_cases import estoque

router = APIRouter(tags=["Estoque"])
acesso = exigir_modulo("estoque")


@router.get("/estoque")
def listar_estoque(
    busca: str | None = None,
    lojaId: int | None = None,
    categoria: str | None = None,
    status: Literal["NORMAL", "BAIXO", "SEM_ESTOQUE", "ALERTA"] | None = None,
    variacaoId: int | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    itens = estoque.listar(db, busca=busca, loja_id=lojaId, categoria=categoria, status=status, variacao_id=variacaoId)
    return [estoque_saida(e) for e in itens if na_marca(marca, e.loja.marca)]


@router.get("/estoque/posicao")
def posicao_em_data(
    data: str | None = None,
    lojaId: int | None = None,
    busca: str | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """Saldo de cada item ao final do dia informado (aaaa-mm-dd)."""
    itens = estoque.posicao_em_data(db, data, lojaId, busca)
    return {
        "data": data,
        "itens": [{**estoque_saida(e), "quantidadeNaData": saldo} for e, saldo in itens if na_marca(marca, e.loja.marca)],
    }


@router.get("/estoque/{estoque_id}")
def obter_estoque(
    estoque_id: int, db: Session = Depends(get_db), _: m.Usuario = Depends(acesso), marca: str | None = Depends(escopo_marca)
):
    item = estoque.obter(db, estoque_id)
    conferir_marca(marca, item.loja.marca, "Item de estoque não encontrado.")
    return estoque_saida(item)


@router.get("/movimentacoes")
def listar_movimentacoes(
    estoqueId: int | None = None,
    lojaId: int | None = None,
    tipo: str | None = None,
    de: str | None = None,
    ate: str | None = None,
    busca: str | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    movimentacoes = estoque.listar_movimentacoes(db, estoque_id=estoqueId, loja_id=lojaId, tipo=tipo, de=de, ate=ate, busca=busca)
    return [movimentacao_saida(mov) for mov in movimentacoes if na_marca(marca, mov.estoque.loja.marca)]


@router.post("/movimentacoes", status_code=201)
def registrar_movimentacao(
    dados: MovimentacaoEntrada,
    db: Session = Depends(get_db),
    usuario: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """Lançamento manual (entrada, venda, devolução ou ajuste). O autor vem do token. Só na marca de quem lança."""
    conferir_marca(marca, estoque.obter(db, dados.estoque_id).loja.marca, "Item de estoque não encontrado.")
    mov = estoque.registrar_movimentacao(
        db, estoque_id=dados.estoque_id, tipo=dados.tipo, quantidade=dados.quantidade, origem=dados.origem, usuario_id=usuario.id
    )
    return movimentacao_saida(mov)
