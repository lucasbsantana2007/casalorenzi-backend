"""Etapa 10: conciliação da migração (nenhum registro some sem ocorrência) e o registro de decisões gerado
das ocorrências, sem nenhum tipo de problema de fora."""

import os
import re

import pytest
from sqlalchemy import event, func, select, text

from src import models as m
from src.config.settings import VULTO_DADOS
from src.database.connection import SessionLocal, engine
from src.migracao_vulto import atendimento, fidelidade, usuarios, vendas
from src.migracao_vulto.__main__ import rodar
from src.relatorios import registro_decisoes


@pytest.fixture(scope="module")
def staging():
    if not os.path.isdir(VULTO_DADOS):
        pytest.skip("Pasta VULTO_DADOS com os dados da Vulto não encontrada.")
    rodar(["staging"])


def _migrados(db, origem: str) -> int:
    return db.scalar(select(func.count()).where(m.DePara.origem == origem))


def _descartados(db, dominio: str) -> int:
    """Registros de origem que não entraram, cada um com a sua ocorrência."""
    return db.scalar(
        select(func.count()).where(
            m.MigracaoOcorrencia.dominio == dominio,
            m.MigracaoOcorrencia.acao_tomada == "DESCARTADO",
            m.MigracaoOcorrencia.id_origem.is_not(None),
        )
    )


# A migração roda do computador de quem migra contra o banco de produção: cada comando é uma ida e volta
# pela internet (~140 ms até o Render). Em lote, a carga inteira cabe em menos de mil comandos (eram 137 mil:
# 5 horas); o limite pega a volta de uma consulta por registro.
LIMITE_DE_COMANDOS = 1500


def test_conciliacao_e_registro_de_decisoes(staging):
    comandos = []
    contar = lambda *_args: comandos.append(1)  # noqa: E731
    event.listen(engine, "before_cursor_execute", contar)
    try:
        resultados = {
            r.dominio: r
            for r in rodar(["lojas", "produtos", "clientes", "usuarios", "vendas", "estoque", "fidelidade", "atendimento"])
        }
    finally:
        event.remove(engine, "before_cursor_execute", contar)
    assert len(comandos) < LIMITE_DE_COMANDOS, f"{len(comandos)} comandos SQL na migração"
    with SessionLocal() as db:
        # Lido = migrado + descartado com ocorrência, domínio a domínio (os 1:1; estoque, produtos e clientes juntam
        # vários registros num só e são conferidos pelos totais nos testes de cada etapa)
        assert resultados["vendas"].lidos == (
            _migrados(db, vendas.ORIGEM_VENDAS) + _migrados(db, vendas.ORIGEM_BATEL) + _descartados(db, "vendas")
        )
        assert resultados["atendimento"].lidos == _migrados(db, atendimento.ORIGEM) + _descartados(db, "atendimento")
        assert resultados["usuarios"].lidos == (
            _migrados(db, usuarios.ORIGEM_FUNCIONARIOS) + _migrados(db, usuarios.ORIGEM_ATENDENTES) + _descartados(db, "usuarios")
        )
        # Cada movimento de pontos do legado entrou (o estorno que faltava é um movimento a mais) ou tem ocorrência
        movimentos = db.scalar(
            select(func.count()).where(
                m.MovimentoPontos.origem == fidelidade.ORIGEM_MOV, m.MovimentoPontos.obs.not_like("estorno que faltou%")
            )
        )
        descartados = db.scalar(
            select(func.count()).where(
                m.MigracaoOcorrencia.dominio == "fidelidade",
                m.MigracaoOcorrencia.origem == fidelidade.ORIGEM_MOV,
                m.MigracaoOcorrencia.acao_tomada == "DESCARTADO",
            )
        )
        assert db.scalar(text("SELECT count(*) FROM legado_vulto.db__pontos_mov")) == movimentos + descartados

        documento = registro_decisoes.gerar(db)
        codigos = set(db.scalars(select(m.MigracaoOcorrencia.codigo_problema).distinct()))

    # Todos os números foram preenchidos e nenhum tipo de ocorrência ficou de fora
    assert not re.findall(r"\{[a-zA-Z_]+\}", documento)
    assert all(f"`{codigo}`" in documento for codigo in codigos)
    assert "| 27 | Senhas em texto puro" in documento
    assert "R$ 6.444.100,77 sem frete" in documento
