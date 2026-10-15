"""Consultas dos números da diretoria: o valor das vendas por trás de uma ocorrência da migração, as vendas
ainda aguardando pagamento e a composição do estoque de cada loja (abertura, entradas, transferências...)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, case, exists, func, not_, select
from sqlalchemy.orm import Session

from src import models as m


def _sem_frete():
    return func.coalesce(func.sum(m.Pedido.total - func.coalesce(m.Pedido.frete_valor, 0)), 0)


def vendas_da_ocorrencia(db: Session, codigo: str, origem: str) -> tuple[int, Decimal]:
    """(vendas, valor sem frete) dos pedidos que vieram das vendas marcadas com a ocorrência (ex.: o status vazio
    lido como pago). Só vendas (troca não é receita) e não canceladas."""
    ids = select(m.MigracaoOcorrencia.id_origem).where(
        m.MigracaoOcorrencia.dominio == "vendas", m.MigracaoOcorrencia.codigo_problema == codigo
    )
    pedidos = select(m.DePara.id_destino).where(
        m.DePara.origem == origem, m.DePara.tabela_destino == "pedidos", m.DePara.id_origem.in_(ids)
    )
    linha = db.execute(
        select(func.count(), _sem_frete()).where(
            m.Pedido.id.in_(pedidos), m.Pedido.tipo == "VENDA", m.Pedido.status != "CANCELADO"
        )
    ).one()
    return linha[0], Decimal(linha[1])


def aguardando_pagamento(db: Session, desde: datetime, ate: datetime, marca: str) -> tuple[int, Decimal]:
    """(vendas, valor sem frete) com o pagamento só pendente no período: ainda não são receita."""
    p = m.Pagamento
    pendente = exists().where(p.pedido_id == m.Pedido.id, p.status == "PENDENTE")
    outro = exists().where(p.pedido_id == m.Pedido.id, p.status != "PENDENTE")
    linha = db.execute(
        select(func.count(), _sem_frete())
        .join(m.Loja, m.Loja.id == m.Pedido.loja_id)
        .where(
            m.Loja.marca == marca,
            m.Pedido.tipo == "VENDA",
            m.Pedido.status != "CANCELADO",
            m.Pedido.criado_em >= desde,
            m.Pedido.criado_em < ate,
            and_(pendente, not_(outro)),
        )
    ).one()
    return linha[0], Decimal(linha[1])


def ocorrencia(db: Session, dominio: str, codigo: str) -> tuple[int, Decimal]:
    """(registros, soma do impacto) de uma ocorrência da migração."""
    linha = db.execute(
        select(func.count(), func.coalesce(func.sum(m.MigracaoOcorrencia.impacto), 0)).where(
            m.MigracaoOcorrencia.dominio == dominio, m.MigracaoOcorrencia.codigo_problema == codigo
        )
    ).one()
    return linha[0], Decimal(linha[1])


# Como cada movimentação entra na composição do saldo (o ajuste da migração diz na origem se é a abertura
# estimada ou o acerto da contagem)
def _parcela():
    mv = m.Movimentacao
    return case(
        (and_(mv.tipo == "AJUSTE", mv.origem.like("abertura%")), "abertura"),
        (and_(mv.tipo == "AJUSTE", mv.origem.like("contagem%")), "ajusteContagem"),
        (mv.tipo == "ENTRADA", "entradas"),
        (mv.tipo.in_(("TRANSFERENCIA_ENTRADA", "TRANSFERENCIA_SAIDA")), "transferencias"),
        (mv.tipo == "VENDA", "vendas"),
        (mv.tipo == "DEVOLUCAO", "devolucoes"),
        else_="outros",
    )


def composicao_do_estoque(db: Session, marca: str, ate: datetime) -> dict[int, dict[str, int]]:
    """loja_id → {parcela: peças} das movimentações até o momento (a soma das parcelas é o saldo)."""
    parcela = _parcela().label("parcela")
    linhas = db.execute(
        select(m.Estoque.loja_id, parcela, func.sum(m.Movimentacao.quantidade))
        .join(m.Estoque, m.Estoque.id == m.Movimentacao.estoque_id)
        .join(m.Loja, m.Loja.id == m.Estoque.loja_id)
        .where(m.Loja.marca == marca, m.Movimentacao.criado_em < ate)
        .group_by(m.Estoque.loja_id, parcela)
    )
    composicao: dict[int, dict[str, int]] = {}
    for loja_id, nome, pecas in linhas:
        composicao.setdefault(loja_id, {})[nome] = int(pecas)
    return composicao
