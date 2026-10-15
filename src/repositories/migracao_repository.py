"""Rastreio da migração da Vulto: de_para (origem → registro da plataforma) e ocorrências."""

from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src import models as m


def destino(db: Session, origem: str, id_origem: str, tabela_destino: str) -> int | None:
    """Id na plataforma do registro que veio de (origem, id_origem), ou None se ainda não migrou."""
    return db.scalar(
        select(m.DePara.id_destino).where(
            m.DePara.origem == origem, m.DePara.id_origem == id_origem, m.DePara.tabela_destino == tabela_destino
        )
    )


def vincular(db: Session, origem: str, id_origem: str, tabela_destino: str, id_destino: int) -> None:
    """Grava (ou atualiza) o vínculo origem → destino, sem confirmar."""
    vinculo = db.scalar(
        select(m.DePara).where(
            m.DePara.origem == origem, m.DePara.id_origem == id_origem, m.DePara.tabela_destino == tabela_destino
        )
    )
    if vinculo is None:
        db.add(m.DePara(origem=origem, id_origem=id_origem, tabela_destino=tabela_destino, id_destino=id_destino))
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
