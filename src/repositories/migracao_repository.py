"""Rastreio da migração da Vulto: de_para (origem → registro da plataforma) e ocorrências."""

from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src import models as m


def _vinculos(db: Session, origem: str, tabela_destino: str) -> dict[str, m.DePara]:
    """Os vínculos de (origem, tabela), carregados uma vez por sessão: a migração consulta e grava milhares,
    e uma consulta por registro custa uma ida e volta ao banco (horas, contra o banco de produção)."""
    cache = db.info.setdefault("de_para", {})
    if (origem, tabela_destino) not in cache:
        cache[(origem, tabela_destino)] = {
            vinculo.id_origem: vinculo
            for vinculo in db.scalars(
                select(m.DePara).where(m.DePara.origem == origem, m.DePara.tabela_destino == tabela_destino)
            )
        }
    return cache[(origem, tabela_destino)]


def esquecer_vinculos(db: Session) -> None:
    """Grava os vínculos pendentes e descarta o cache. Chame antes de apagar vínculos direto no banco: depois
    disso, o cache se recarrega do banco."""
    db.flush()
    db.info.pop("de_para", None)


def destinos(db: Session, origem: str, tabela_destino: str) -> set[int]:
    """Ids na plataforma de tudo o que já migrou de (origem, tabela)."""
    return {vinculo.id_destino for vinculo in _vinculos(db, origem, tabela_destino).values()}


def destino(db: Session, origem: str, id_origem: str, tabela_destino: str) -> int | None:
    """Id na plataforma do registro que veio de (origem, id_origem), ou None se ainda não migrou."""
    vinculo = _vinculos(db, origem, tabela_destino).get(id_origem)
    return vinculo.id_destino if vinculo else None


def vincular(db: Session, origem: str, id_origem: str, tabela_destino: str, id_destino: int) -> None:
    """Grava (ou atualiza) o vínculo origem → destino, sem confirmar."""
    vinculos = _vinculos(db, origem, tabela_destino)
    vinculo = vinculos.get(id_origem)
    if vinculo is None:
        vinculo = m.DePara(origem=origem, id_origem=id_origem, tabela_destino=tabela_destino, id_destino=id_destino)
        db.add(vinculo)
        vinculos[id_origem] = vinculo
    else:
        vinculo.id_destino = id_destino


def limpar_ocorrencias(db: Session, dominio: str) -> int:
    """Apaga as ocorrências de um domínio antes de rodá-lo de novo (idempotência). Devolve quantas."""
    return db.execute(delete(m.MigracaoOcorrencia).where(m.MigracaoOcorrencia.dominio == dominio)).rowcount


def registrar_ocorrencia(
    db: Session,
    *,
    codigo_problema: str,
    dominio: str,
    origem: str,
    descricao: str,
    acao_tomada: str,
    id_origem: str | None = None,
    valor_original: str | None = None,
    valor_final: str | None = None,
    impacto: Decimal | None = None,
    impacto_unidade: str | None = None,
) -> m.MigracaoOcorrencia:
    ocorrencia = m.MigracaoOcorrencia(
        codigo_problema=codigo_problema,
        dominio=dominio,
        origem=origem,
        id_origem=id_origem,
        descricao=descricao,
        acao_tomada=acao_tomada,
        valor_original=valor_original,
        valor_final=valor_final,
        impacto=impacto,
        impacto_unidade=impacto_unidade,
    )
    db.add(ocorrencia)
    return ocorrencia


def ocorrencias_por_acao(db: Session, dominio: str) -> dict[str, int]:
    db.flush()  # a sessão não descarrega sozinha (autoflush desligado): conta também as da transação
    linhas = db.execute(
        select(m.MigracaoOcorrencia.acao_tomada, func.count())
        .where(m.MigracaoOcorrencia.dominio == dominio)
        .group_by(m.MigracaoOcorrencia.acao_tomada)
    )
    return {acao: int(n) for acao, n in linhas}


def origem(db: Session, tabela_destino: str, id_destino: int, origem_: str) -> str | None:
    """id na origem do registro da plataforma (o caminho inverso do de_para)."""
    return db.scalar(
        select(m.DePara.id_origem).where(
            m.DePara.tabela_destino == tabela_destino, m.DePara.id_destino == id_destino, m.DePara.origem == origem_
        )
    )


def motivo_da_venda(db: Session, venda_id: str) -> str | None:
    """Por que uma venda da Vulto não virou pedido (teste, duplicata ou devolução)."""
    if db.scalar(select(m.DePara.id).where(m.DePara.origem == "vulto.db:vendas", m.DePara.id_origem.like(f"{venda_id}:%"))):
        return "é uma devolução (valor negativo); está nas devoluções do pedido de origem."
    return db.scalar(
        select(m.MigracaoOcorrencia.descricao).where(
            m.MigracaoOcorrencia.dominio == "vendas",
            m.MigracaoOcorrencia.id_origem == venda_id,
            m.MigracaoOcorrencia.acao_tomada == "DESCARTADO",
        )
    )
