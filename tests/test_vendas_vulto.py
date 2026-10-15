"""Migração das vendas da Vulto (etapa 5): pedidos, devoluções, trocas, Batel em março, e o
faturamento comparado com o relatório do sistema da Vulto."""

import os
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from src import models as m
from src.config.settings import FUSO, VULTO_DADOS
from src.database.connection import SessionLocal
from src.migracao_vulto.__main__ import rodar
from src.use_cases.faturamento import dia_legado, valor_legado


def test_relatorio_antigo_e_lido_como_o_sistema_da_vulto_lia():
    """dia_utc() tirava o Z sem converter o fuso; valor() lia "19081" como 19.081 e "1.234,56" como zero."""
    assert dia_legado("2026-10-01T02:28:31Z") == "2026-10-01"  # em Brasília ainda é 30/09
    assert dia_legado("20/01/2025 15:21") == "2025-01-20"
    assert dia_legado("2025-09-01T10:38:41.000000") == "2025-09-01"
    assert valor_legado("19081") == Decimal("19081.00")
    assert valor_legado("379,80") == Decimal("379.80")
    assert valor_legado("1.234,56") == Decimal("0")


# ---------- Com os dados reais ----------


@pytest.fixture(scope="module")
def staging():
    if not os.path.isdir(VULTO_DADOS):
        pytest.skip("Pasta VULTO_DADOS com os dados da Vulto não encontrada.")
    rodar(["staging"])


@pytest.fixture
def migrado(staging):
    return {r.dominio: r for r in rodar(["lojas", "produtos", "clientes", "vendas"])}


def _pedido(db, numero: str) -> m.Pedido:
    return db.scalar(select(m.Pedido).where(m.Pedido.numero == numero))


def _contar(db, modelo, *condicoes) -> int:
    return db.scalar(select(func.count()).select_from(modelo).where(*condicoes))


def test_vendas_viram_pedidos_devolucoes_e_trocas(migrado):
    resultado = migrado["vendas"]
    assert resultado.descartados == 118  # 42 vendas de teste + 76 duplicatas do app
    with SessionLocal() as db:
        vulto = m.Pedido.numero.like("VLT-%")
        # 18.598 vendas − 201 devoluções − 118 descartadas + 59 vendas só da planilha manual da Batel
        assert _contar(db, m.Pedido, vulto) == 18338
        assert _contar(db, m.Pedido, vulto, m.Pedido.tipo == "TROCA") == 328
        assert _contar(db, m.Devolucao, m.Devolucao.usuario_id.is_(None)) == 201
        assert _contar(db, m.Devolucao, m.Devolucao.usuario_id.is_(None), m.Devolucao.pedido_id.is_(None)) == 24

        # App em centavos: "33980" = R$ 339,80; saiu do CD
        app = _pedido(db, "VLT-05785")
        assert (app.total, app.canal, app.loja.nome) == (Decimal("339.80"), "App", "CD Cajamar")
        # Frete que o app somou no total sem gravar: separado
        frete = _pedido(db, "VLT-00093")
        assert (frete.total, frete.subtotal, frete.frete_valor) == (Decimal("99.80"), Decimal("89.90"), Decimal("9.90"))
        # Status vazio (loja física, jan/25) = pago
        vazio = _pedido(db, "VLT-00002")
        assert vazio.status == "ENTREGUE" and [p.status for p in vazio.pagamentos] == ["APROVADO"]
        # Ship from store: pedido do site expedido por Pinheiros
        sfs = _pedido(db, "VLT-15017")
        assert (sfs.canal, sfs.loja.nome) == ("E-commerce", "Vulto Pinheiros")
        # Troca: pedido TROCA (baixa estoque, fora da receita)
        assert _pedido(db, "VLT-00238").tipo == "TROCA"
        # Duplicata do app (aguardando seguido do pago) e vendas de teste ficam de fora
        assert _pedido(db, "VLT-00272") is None and _pedido(db, "VLT-00273") is not None
        assert _pedido(db, "VLT-05788") is None  # item TESTE-001

        # Batel: a venda relançada em 23/03 volta para 02/03 (data da planilha, que o Excel tinha invertido)
        relancada = _pedido(db, "VLT-12800")
        assert relancada.criado_em.astimezone(FUSO).replace(tzinfo=None) == datetime(2026, 3, 2, 15, 46)
        assert _contar(db, m.Pedido, m.Pedido.numero.like("VLT-BATEL-%")) == 59
        total_planilha = db.scalar(
            select(m.MigracaoOcorrencia.acao_tomada).where(m.MigracaoOcorrencia.codigo_problema == "BATEL_TOTAL_DA_PLANILHA")
        )
        assert total_planilha == "MANTIDO"  # a soma das vendas não canceladas bate com o TOTAL MARÇO

        # Compras do Vulto+ ligadas aos pedidos (para a migração da fidelidade)
        assert _contar(db, m.DePara, m.DePara.origem == "vulto.db:compras") > 7000

    rodar(["vendas"])  # de novo: mesmo resultado
    with SessionLocal() as db:
        assert _contar(db, m.Pedido, m.Pedido.numero.like("VLT-%")) == 18338
        assert _contar(db, m.Devolucao, m.Devolucao.usuario_id.is_(None)) == 201


def test_faturamento_e_comparativo_com_o_sistema_da_vulto(client, admin, lojista, migrado):
    comparativo = client.get("/api/financeiro/faturamento/comparativo-vulto", headers=admin).json()
    total = comparativo["total"]
    # Toda a diferença é explicada pelos ajustes: nada sobra em "outros", em nenhum mês
    assert all(abs(mes["ajustes"]["outros"]) < 0.01 for mes in comparativo["meses"])
    assert total["sistemaVulto"] + sum(total["ajustes"].values()) == pytest.approx(total["nossoComFrete"], abs=0.01)
    assert total["sistemaVulto"] == pytest.approx(94580496.26)
    assert total["ajustes"]["centavos"] < -87_000_000
    assert total["ajustes"]["trocas"] == pytest.approx(-74447.20)
    assert total["ajustes"]["batel"] == pytest.approx(22466.99)
    assert [m["mes"] for m in comparativo["meses"]][0] == "2025-01" and comparativo["meses"][-1]["mes"] == "2026-09"

    faturamento = client.get("/api/financeiro/faturamento?marca=VULTO", headers=admin).json()
    assert faturamento["total"]["liquidoComFrete"] == pytest.approx(total["nossoComFrete"])
    assert faturamento["total"]["semFrete"] == pytest.approx(faturamento["total"]["comFrete"] - faturamento["total"]["frete"])
    assert {linha["canal"] for linha in faturamento["linhas"]} >= {"Loja física", "E-commerce", "App"}
    assert {linha["marca"] for linha in faturamento["linhas"]} == {"VULTO"}

    # As duas marcas no financeiro, separáveis
    lorenzi = client.get("/api/financeiro/faturamento?marca=LORENZI", headers=admin).json()["total"]["comFrete"]
    todas = client.get("/api/financeiro/faturamento", headers=admin).json()["total"]["comFrete"]
    assert todas == pytest.approx(lorenzi + faturamento["total"]["comFrete"])
    assert client.get("/api/financeiro/faturamento/comparativo-vulto", headers=lojista).status_code == 403


def test_consulta_de_venda_da_vulto_e_lista_de_pedidos(client, admin, lojista, migrado):
    por_id = client.get("/api/pedidos/vulto/1234", headers=admin).json()
    assert (por_id["numero"], por_id["vendaVulto"], por_id["loja"]["nome"]) == ("VLT-01234", 1234, "Vulto Shopping Eldorado")
    por_externo = client.get("/api/pedidos/vulto/APP-7001782", headers=admin).json()
    assert (por_externo["numero"], por_externo["pedidoExterno"], por_externo["canal"]) == ("VLT-01415", "APP-7001782", "App")
    teste = client.get("/api/pedidos/vulto/5788", headers=admin)
    assert teste.status_code == 404 and "teste" in teste.json()["detail"]
    devolucao = client.get("/api/pedidos/vulto/445", headers=admin)
    assert devolucao.status_code == 404 and "devolução" in devolucao.json()["detail"]
    # Lojista da Casa Lorenzi não vê pedido de loja da Vulto
    assert client.get("/api/pedidos/vulto/1234", headers=lojista).status_code == 404

    # A lista do painel continua só com a Casa Lorenzi; a Vulto vem com o filtro
    padrao = client.get("/api/pedidos", headers=admin).json()
    assert padrao and all(p["numero"].startswith("CL-") for p in padrao)
    processando = client.get("/api/pedidos?marca=VULTO&status=PROCESSANDO", headers=admin).json()
    assert processando and all(p["numero"].startswith("VLT-") for p in processando)
    assert client.get("/api/pedidos?busca=APP-7001782&marca=VULTO", headers=admin).json()[0]["numero"] == "VLT-01415"
