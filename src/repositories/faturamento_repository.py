"""Consultas do faturamento por mês × loja × canal e do comparativo com o sistema da Vulto.

Receita = pedidos de venda (não trocas), não cancelados e sem pagamento só pendente, pelo total
(com frete) ou pelo total − frete; devoluções pela data em que aconteceram. Mês no fuso de Brasília."""

from datetime import datetime

from sqlalchemy import and_, exists, func, not_, select, text
from sqlalchemy.orm import Session

from src import models as m
from src.config.settings import FUSO
from src.entities.pedido import TIPOS_SEM_RECEITA


def _mes(coluna):
    return func.to_char(func.timezone(FUSO.key, coluna), "YYYY-MM")


def _so_pendente():
    p = m.Pagamento
    pendente = exists().where(p.pedido_id == m.Pedido.id, p.status == "PENDENTE")
    outro = exists().where(p.pedido_id == m.Pedido.id, p.status != "PENDENTE")
    return and_(pendente, not_(outro))


def receita(db: Session, inicio: datetime, fim: datetime, marca: str | None) -> list[dict]:
    consulta = (
        select(
            _mes(m.Pedido.criado_em).label("mes"),
            m.Pedido.loja_id,
            m.Pedido.canal,
            func.count().label("pedidos"),
            func.sum(m.Pedido.total).label("com_frete"),
            func.coalesce(func.sum(m.Pedido.frete_valor), 0).label("frete"),
        )
        .join(m.Loja, m.Loja.id == m.Pedido.loja_id)
        .where(
            m.Pedido.criado_em >= inicio,
            m.Pedido.criado_em < fim,
            m.Pedido.status != "CANCELADO",
            m.Pedido.tipo.not_in(TIPOS_SEM_RECEITA),
            not_(_so_pendente()),
        )
        .group_by("mes", m.Pedido.loja_id, m.Pedido.canal)
    )
    if marca:
        consulta = consulta.where(m.Loja.marca == marca)
    return [dict(r._mapping) for r in db.execute(consulta)]


def devolucoes(db: Session, inicio: datetime, fim: datetime, marca: str | None) -> list[dict]:
    """Por mês, loja e canal do pedido de origem (devolução sem origem: canal nulo)."""
    consulta = (
        select(
            _mes(m.Devolucao.criada_em).label("mes"),
            m.Devolucao.loja_id,
            m.Pedido.canal,
            func.sum(m.Devolucao.valor_devolvido).label("valor"),
        )
        .join(m.Loja, m.Loja.id == m.Devolucao.loja_id)
        .outerjoin(m.Pedido, m.Pedido.id == m.Devolucao.pedido_id)
        .where(m.Devolucao.criada_em >= inicio, m.Devolucao.criada_em < fim)
        .group_by("mes", m.Devolucao.loja_id, m.Pedido.canal)
    )
    if marca:
        consulta = consulta.where(m.Loja.marca == marca)
    return [dict(r._mapping) for r in db.execute(consulta)]


# ---------- Comparativo com o sistema da Vulto ----------


def vendas_do_legado(db: Session) -> list[dict]:
    """Todas as vendas do vulto.db, cruas, como o relatório da Vulto as lê."""
    consulta = text("SELECT id::int AS id, total, criado_em, loja_id::int AS loja FROM legado_vulto.db__vendas")
    return [dict(r._mapping) for r in db.execute(consulta)]


def destinos_das_vendas(db: Session) -> dict[str, list[tuple[str, int]]]:
    """id da venda do legado (ou "venda:item" das devoluções) → [(tabela, id na plataforma)]."""
    linhas = db.execute(
        select(m.DePara.id_origem, m.DePara.tabela_destino, m.DePara.id_destino).where(
            m.DePara.origem == "vulto.db:vendas", m.DePara.tabela_destino.in_(("pedidos", "devolucoes"))
        )
    )
    destinos: dict[str, list[tuple[str, int]]] = {}
    for id_origem, tabela, id_destino in linhas:
        destinos.setdefault(id_origem.split(":")[0], []).append((tabela, id_destino))
    return destinos


def ocorrencias_das_vendas(db: Session, codigos: tuple[str, ...]) -> dict[str, str]:
    """id da venda → código da ocorrência (testes, duplicatas, centavos, Batel redatada)."""
    linhas = db.execute(
        select(m.MigracaoOcorrencia.id_origem, m.MigracaoOcorrencia.codigo_problema).where(
            m.MigracaoOcorrencia.dominio == "vendas",
            m.MigracaoOcorrencia.codigo_problema.in_(codigos),
            m.MigracaoOcorrencia.origem == "vulto.db:vendas",
        )
    )
    resultado: dict[str, set[str]] = {}
    for id_origem, codigo in linhas:
        resultado.setdefault(id_origem, set()).add(codigo)
    return resultado


def pedidos_vulto(db: Session) -> dict[int, m.Pedido]:
    vulto = select(m.Pedido).join(m.Loja, m.Loja.id == m.Pedido.loja_id).where(m.Loja.marca == "VULTO")
    return {p.id: p for p in db.scalars(vulto)}


def devolucoes_vulto(db: Session) -> dict[int, m.Devolucao]:
    vulto = select(m.Devolucao).join(m.Loja, m.Loja.id == m.Devolucao.loja_id).where(m.Loja.marca == "VULTO")
    return {d.id: d for d in db.scalars(vulto)}


def pedidos_da_planilha_batel(db: Session) -> list[int]:
    return list(
        db.scalars(
            select(m.DePara.id_destino).where(
                m.DePara.origem == "vendas_batel_MANUAL_marco.xlsx:MARÇO", m.DePara.tabela_destino == "pedidos"
            )
        )
    )
