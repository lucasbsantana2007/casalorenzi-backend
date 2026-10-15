"""Vulto+ (etapa 7): saldo congelado em 01/01/2025 + movimentos do sistema corrigidos, validade FIFO, saldo
nunca negativo, extrato do cliente e passivo de pontos com a faixa."""

import os
from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from src import models as m
from src.config.settings import VULTO_DADOS
from src.database.connection import SessionLocal
from src.entities.fidelidade import FUSO, aplicar_validade, categoria_pela_regra, somar_meses
from src.migracao_vulto.__main__ import rodar
from src.migracao_vulto.fidelidade import pontos_planilha
from src.migracao_vulto.normalizacao import ValorInvalido


def _dia(ano: int, mes: int, dia: int) -> datetime:
    return datetime(ano, mes, dia, tzinfo=FUSO)


def test_pontos_anotados_na_planilha():
    assert pontos_planilha("2.203") == (2203, True)  # ponto de milhar
    assert pontos_planilha("1389 pts") == (1389, True)
    assert pontos_planilha("596") == (596, True)
    assert pontos_planilha("2,7k") == (2700, False)  # arredondado: estimado
    assert pontos_planilha("12,5k") == (12500, False)
    assert pontos_planilha("") == (0, True)
    with pytest.raises(ValorInvalido):
        pontos_planilha("dois mil")


def test_categoria_e_vencimento():
    assert [categoria_pela_regra(p) for p in (-10, 1999, 2000, 4999, 5000)] == ["BRONZE", "BRONZE", "PRATA", "PRATA", "OURO"]
    assert somar_meses(_dia(2025, 1, 31), 1) == date(2025, 2, 28)
    assert somar_meses(_dia(2025, 3, 24), 18) == date(2026, 9, 24)


def test_validade_consome_os_pontos_mais_antigos_primeiro():
    movimentos = [(_dia(2025, 1, 1), 100), (_dia(2025, 6, 1), 50), (_dia(2025, 7, 1), -120)]
    # O resgate consome os 100 de janeiro e 20 de junho; sobram 30, que vencem em 01/06/2026
    antes = aplicar_validade(movimentos, 12, _dia(2026, 5, 31))
    assert (antes.saldo, antes.vencimentos, antes.a_vencer) == (30, [], [(date(2026, 6, 1), 30)])
    depois = aplicar_validade(movimentos, 12, _dia(2026, 6, 2))
    assert (depois.saldo, depois.vencimentos) == (0, [(_dia(2026, 6, 1), 30)])
    # Sem resgate, os de janeiro vencem em 01/01/2026 (12 meses) ou 01/07/2026 (Ouro, 18 meses)
    assert aplicar_validade(movimentos[:2], 12, _dia(2026, 3, 1)).saldo == 50
    assert aplicar_validade(movimentos[:2], 18, _dia(2026, 3, 1)).saldo == 150


def test_saldo_nunca_fica_negativo():
    validade = aplicar_validade([(_dia(2025, 2, 1), 10), (_dia(2025, 3, 1), -30), (_dia(2025, 4, 1), 5)], 12, _dia(2025, 5, 1))
    assert validade.saldo == 5
    assert validade.faltas == [(_dia(2025, 3, 1), 20)]


@pytest.fixture(scope="module")
def staging():
    if not os.path.isdir(VULTO_DADOS):
        pytest.skip("Pasta VULTO_DADOS com os dados da Vulto não encontrada.")
    rodar(["staging"])


def _ocorrencias(db, codigo: str) -> int:
    return db.scalar(
        select(func.count()).where(m.MigracaoOcorrencia.dominio == "fidelidade", m.MigracaoOcorrencia.codigo_problema == codigo)
    )


def _totais(db) -> tuple[int, int]:
    return (
        db.scalar(select(func.count()).select_from(m.MovimentoPontos)),
        db.scalar(select(func.sum(m.ContaPontos.saldo))),
    )


def test_vulto_mais_migrado(staging, client, admin, lojista, mariana):
    rodar(["lojas", "produtos", "clientes", "vendas", "fidelidade"])

    # Passivo em 01/10/2026: Ouro 18 meses (gravado) e Ouro 12, a R$ 0,05 (vigente) e R$ 0,10 (o que o sistema dava)
    passivo = client.get("/api/financeiro/vulto-mais/passivo", headers=admin).json()
    cenarios = {c["validadeOuroMeses"]: c for c in passivo["cenarios"]}
    assert cenarios[18]["pontos"] == 3352597 and cenarios[18]["gravado"]
    assert cenarios[18]["valorVigente"] == 167629.85
    assert cenarios[12]["pontos"] == 3257953
    faixa = passivo["faixa"]
    assert faixa["minimo"]["pontos"] < faixa["vigente"]["pontos"] < faixa["maximo"]["pontos"]
    assert faixa["maximo"]["pontos"] == 3352597 + passivo["naoAplicados"]["dobroOnline"] + passivo["naoAplicados"]["bonusOuro"]
    assert client.get("/api/financeiro/vulto-mais/passivo", headers=lojista).status_code == 403

    # Extrato: o crédito inflado pelo bug do app (61.164 pontos sobre R$ 305,82 em centavos) volta para 612,
    # e o ajuste manual "correcao bug app v3.4" sai
    extrato = client.get("/api/clientes/22218638797/vulto-mais", headers=admin).json()
    assert any(mv["tipo"] == "CREDITO" and mv["quantidade"] == 612 for mv in extrato["movimentos"])
    assert not any("correcao bug" in mv["obs"] for mv in extrato["movimentos"])
    assert extrato["saldo"] == sum(mv["quantidade"] for mv in extrato["movimentos"])
    assert sum(item["pontos"] for item in extrato["aVencer"]) == extrato["saldo"]
    # O cliente só vê o próprio extrato
    assert client.get("/api/clientes/22218638797/vulto-mais", headers=mariana).status_code == 404

    with SessionLocal() as db:
        assert _ocorrencias(db, "CREDITO_INFLADO_BUG_APP") == 31
        assert _ocorrencias(db, "AJUSTE_DO_BUG_SUBSTITUIDO") == 21
        assert _ocorrencias(db, "CANCELADA_SEM_ESTORNO") == 285
        # Nenhum saldo negativo, e o saldo de toda conta é a soma do extrato
        soma = select(m.MovimentoPontos.conta_id, func.sum(m.MovimentoPontos.quantidade).label("soma")).group_by(
            m.MovimentoPontos.conta_id
        )
        soma = soma.subquery()
        divergentes = db.scalar(
            select(func.count())
            .select_from(m.ContaPontos)
            .outerjoin(soma, soma.c.conta_id == m.ContaPontos.id)
            .where(m.ContaPontos.saldo != func.coalesce(soma.c.soma, 0))
        )
        assert divergentes == 0
        assert db.scalar(select(func.min(m.ContaPontos.saldo))) >= 0
        antes = _totais(db)

    rodar(["fidelidade"])  # de novo: refaz igual
    with SessionLocal() as db:
        assert _totais(db) == antes
