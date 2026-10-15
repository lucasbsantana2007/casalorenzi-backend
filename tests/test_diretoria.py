"""Números da diretoria (etapa 9): as três respostas sobre a Vulto fecham com as etapas anteriores, a ponte do
relatório da Vulto até o nosso faturamento fecha mês a mês, e os CSVs abrem no Excel em português."""

import os

import pytest

from src.config.settings import VULTO_DADOS
from src.migracao_vulto.__main__ import rodar


@pytest.fixture(scope="module")
def staging():
    if not os.path.isdir(VULTO_DADOS):
        pytest.skip("Pasta VULTO_DADOS com os dados da Vulto não encontrada.")
    rodar(["staging"])


def _fecha(passos: list[dict]) -> bool:
    """Sistema da Vulto + cada passo = nosso número (o último passo)."""
    return abs(sum(p["valor"] for p in passos[:-1]) - passos[-1]["valor"]) < 0.02


def test_numeros_da_diretoria(staging, client, admin, lojista):
    rodar(["lojas", "produtos", "clientes", "vendas", "estoque", "fidelidade"])
    assert client.get("/api/diretoria/numeros", headers=lojista).status_code == 403
    numeros = client.get("/api/diretoria/numeros", headers=admin).json()

    # 1. Faturamento sem frete (aprovado), com a ponte passo a passo e a margem
    faturamento = numeros["faturamento"]
    assert faturamento["total"]["semFrete"] == 6444100.77
    assert [p["chave"] for p in faturamento["ponte"]][-2:] == ["frete", "nossoSemFrete"]
    assert _fecha(faturamento["ponte"])
    assert all(_fecha(mes["passos"]) for mes in faturamento["ponteMensal"])
    assert next(p for p in faturamento["ponte"] if p["chave"] == "outros")["valor"] == 0
    assert round(sum(loja["semFrete"] for loja in faturamento["porLoja"]), 2) == 6444100.77
    margem = faturamento["margem"]
    assert margem["minimo"] < faturamento["total"]["semFrete"] < margem["maximo"]

    # 2. Estoque em 01/10/2026: a composição de cada loja fecha com o saldo
    estoque = numeros["estoque"]
    assert estoque["total"] == 15248
    for loja in estoque["porLoja"]:
        parcelas = ("abertura", "entradas", "transferencias", "vendas", "devolucoes", "ajusteContagem", "outros")
        assert sum(loja[p] for p in parcelas) == loja["saldo"], loja["loja"]
    assert next(loja for loja in estoque["porLoja"] if loja["loja"] == "Vulto Savassi")["contagem"]["dataEstimada"]
    assert sum(p["total"] for p in estoque["porProduto"]) == 15248

    # 3. Passivo de pontos na faixa
    passivo = numeros["passivo"]
    assert passivo["faixa"]["vigente"]["pontos"] == 3352597
    assert passivo["faixa"]["vigente"]["valor"] == 167629.85

    # CSV para o Excel em português
    resposta = client.get("/api/diretoria/numeros/passivo.csv", headers=admin)
    assert resposta.status_code == 200 and resposta.headers["content-type"].startswith("text/csv")
    texto = resposta.content.decode("utf-8")
    assert texto.startswith("﻿cenario;pontos;valor_do_ponto;valor;observacao")
    assert "Ouro 18 meses;3352597;0,05;167629,85;gravado nas contas" in texto
    assert client.get("/api/diretoria/numeros/outra.csv", headers=admin).status_code == 422
