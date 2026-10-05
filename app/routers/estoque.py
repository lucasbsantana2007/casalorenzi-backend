"""Estoque é controlado por LOJA + VARIAÇÃO (SKU); todo saldo vem das movimentações."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Categoria, Estoque, Movimentacao, Produto, Usuario, Variacao
from app.schemas import MovimentacaoEntrada
from app.security import exigir_modulo
from app.services import aplicar_movimentacao
from app.utils import chave_texto, corresponde, fim_do_dia, inicio_do_dia, ler_data, status_estoque
from app.views import estoque_view, movimentacao_view

router = APIRouter(tags=["Estoque"])
acesso_estoque = exigir_modulo("estoque")

ORDEM_STATUS = {"SEM_ESTOQUE": 0, "BAIXO": 1, "NORMAL": 2}
# Sinal esperado da quantidade em cada tipo lançado manualmente
SINAL_POR_TIPO = {"ENTRADA": 1, "DEVOLUCAO": 1, "VENDA": -1, "AJUSTE": 0}


def _filtrar_estoques(
    db: Session,
    *,
    busca: str | None = None,
    loja_id: int | None = None,
    categoria: str | None = None,
    status: str | None = None,
    variacao_id: int | None = None,
) -> list[Estoque]:
    consulta = (
        select(Estoque).join(Estoque.variacao).join(Variacao.produto).join(Produto.categoria).order_by(Estoque.id)
    )
    if loja_id:
        consulta = consulta.where(Estoque.loja_id == loja_id)
    if variacao_id:
        consulta = consulta.where(Estoque.variacao_id == variacao_id)
    if categoria:
        consulta = consulta.where(Categoria.nome == categoria)
    itens = []
    for e in db.scalars(consulta):
        situacao = status_estoque(e.quantidade, e.quantidade_min)
        # ALERTA agrupa estoque baixo e sem estoque
        if status and (situacao == "NORMAL" if status == "ALERTA" else situacao != status):
            continue
        if not corresponde(busca, e.variacao.produto.nome, e.variacao.sku, e.variacao.cor):
            continue
        itens.append(e)
    return itens


@router.get("/estoque")
def listar_estoque(
    busca: str | None = None,
    lojaId: int | None = None,
    categoria: str | None = None,
    status: Literal["NORMAL", "BAIXO", "SEM_ESTOQUE", "ALERTA"] | None = None,
    variacaoId: int | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(acesso_estoque),
):
    itens = [
        estoque_view(e)
        for e in _filtrar_estoques(
            db, busca=busca, loja_id=lojaId, categoria=categoria, status=status, variacao_id=variacaoId
        )
    ]
    itens.sort(key=lambda e: (ORDEM_STATUS[e["status"]], chave_texto(e["produto"]["nome"]), e["lojaId"]))
    return itens


@router.get("/estoque/posicao")
def posicao_em_data(
    data: str | None = None,
    lojaId: int | None = None,
    busca: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(acesso_estoque),
):
    """Reconstrói o saldo de cada item ao final do dia informado, a partir do histórico."""
    dia = ler_data(data)
    if dia is None:
        raise HTTPException(422, "Informe a data de referência.")
    saldos = dict(
        db.execute(
            select(Movimentacao.estoque_id, func.sum(Movimentacao.quantidade))
            .where(Movimentacao.criado_em < fim_do_dia(dia))
            .group_by(Movimentacao.estoque_id)
        ).all()
    )
    itens = [
        {**estoque_view(e), "quantidadeNaData": int(saldos.get(e.id) or 0)}
        for e in _filtrar_estoques(db, loja_id=lojaId, busca=busca)
    ]
    itens.sort(key=lambda e: (not e["produto"]["ativo"], chave_texto(e["produto"]["nome"]), e["lojaId"]))
    return {"data": data, "itens": itens}


@router.get("/estoque/{estoque_id}")
def obter_estoque(estoque_id: int, db: Session = Depends(get_db), _: Usuario = Depends(acesso_estoque)):
    estoque = db.get(Estoque, estoque_id)
    if estoque is None:
        raise HTTPException(404, "Item de estoque não encontrado.")
    return estoque_view(estoque)


@router.get("/movimentacoes")
def listar_movimentacoes(
    estoqueId: int | None = None,
    lojaId: int | None = None,
    tipo: str | None = None,
    de: str | None = None,
    ate: str | None = None,
    busca: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(acesso_estoque),
):
    consulta = select(Movimentacao).join(Movimentacao.estoque).order_by(
        Movimentacao.criado_em.desc(), Movimentacao.id
    )
    if estoqueId:
        consulta = consulta.where(Movimentacao.estoque_id == estoqueId)
    if lojaId:
        consulta = consulta.where(Estoque.loja_id == lojaId)
    if tipo:
        consulta = consulta.where(Movimentacao.tipo == tipo)
    if dia_inicial := ler_data(de, "de"):
        consulta = consulta.where(Movimentacao.criado_em >= inicio_do_dia(dia_inicial))
    if dia_final := ler_data(ate, "ate"):
        consulta = consulta.where(Movimentacao.criado_em < fim_do_dia(dia_final))
    return [
        movimentacao_view(mov)
        for mov in db.scalars(consulta)
        if corresponde(busca, mov.estoque.variacao.produto.nome, mov.estoque.variacao.sku, mov.origem)
    ]


@router.post("/movimentacoes", status_code=201)
def registrar_movimentacao(
    dados: MovimentacaoEntrada,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(acesso_estoque),
):
    """Lançamento manual (entrada, venda, devolução ou ajuste).
    Transferências geram suas movimentações pela rota /transferencias."""
    estoque = db.get(Estoque, dados.estoque_id, with_for_update={"of": Estoque})
    if estoque is None:
        raise HTTPException(404, "Item de estoque não encontrado.")
    if dados.tipo not in SINAL_POR_TIPO:
        raise HTTPException(422, "Movimentações de transferência são geradas pela tela de transferências.")
    sinal = SINAL_POR_TIPO[dados.tipo]
    if dados.quantidade == 0 or (sinal and dados.quantidade * sinal < 0):
        raise HTTPException(422, "Informe uma quantidade válida.")
    mov = aplicar_movimentacao(
        db,
        estoque,
        tipo=dados.tipo,
        quantidade=dados.quantidade,
        origem=dados.origem.strip(),
        usuario_id=usuario.id,
    )
    db.commit()
    return movimentacao_view(mov)
