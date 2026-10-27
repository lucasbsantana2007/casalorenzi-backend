"""Pontos Helo (antes Vulto+): ganho de pontos nas compras, bônus da categoria, resgate no checkout, estorno no cancelamento,
vencimento em 12 meses e consulta do extrato (cliente e equipe)."""

import math
from datetime import timedelta
from decimal import Decimal

import pytest

from src import models as m
from src.database.connection import SessionLocal
from src.entities.devolucao import valor_devolvido
from src.entities.fidelidade import desconto_do_resgate, maximo_resgatavel, pontos_da_compra
from src.use_cases import fidelidade
from src.utils.datas import agora
from tests.conftest import CLIENTE_DEMO_ID
from tests.test_loja_pedidos import _compra, _pedido_no_painel


def _dar_pontos(cpf: str, pontos: int, *, ha_dias: int = 0) -> None:
    """Saldo inicial direto no extrato (o seed não tem pontos), ganho há `ha_dias` dias."""
    with SessionLocal() as db:
        cliente = db.query(m.Cliente).filter_by(cpf=cpf).one()
        fidelidade.lancar(db, cliente.id, "SALDO_INICIAL", pontos, agora() - timedelta(days=ha_dias), obs="teste")
        db.commit()


def _pontos(client, headers):
    resposta = client.get("/api/conta/pontos", headers=headers)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _sacola(client, *, minimo: float = 0, abaixo_de: float | None = None):
    """(variação, quantidade, valor dos produtos): a mais barata com pelo menos `minimo`, ou abaixo de `abaixo_de`."""
    opcoes = []
    for produto in client.get("/api/produtos?ativo=true").json():
        preco = produto["precoBase"]
        for v in produto["variacoes"]:
            if abaixo_de is not None:
                if preco < abaixo_de and v["estoqueTotal"] >= 1:
                    return v["id"], 1, preco
                continue
            quantidade = max(1, math.ceil(minimo / preco))
            if quantidade <= min(v["estoqueTotal"], 20):
                opcoes.append((v["id"], quantidade, preco * quantidade))
    assert opcoes, "nenhuma variação serve"
    return min(opcoes, key=lambda o: o[2])


def _comprar(client, headers, sacola, pontos=0):
    variacao_id, quantidade, _ = sacola
    return client.post("/api/checkout", json=_compra(variacao_id, quantidade=quantidade, pontos=pontos), headers=headers)


def test_regras_de_ganho_e_resgate():
    # R$ 1 = 1 ponto na loja e 2 no site e no app; Ouro +25% e Vip +50% sobre tudo
    assert pontos_da_compra(Decimal("100"), "Loja física", None) == 100
    assert pontos_da_compra(Decimal("100"), "E-commerce", "PRATA") == 200
    assert pontos_da_compra(Decimal("100"), "App", "OURO") == 250
    assert pontos_da_compra(Decimal("100"), "Loja física", "VIP") == 150
    assert pontos_da_compra(Decimal("0.30"), "Loja física", "VIP") == 0  # 0,45 arredonda para 0
    # 100 pontos = R$ 5, múltiplos de 100, sem passar do valor dos produtos
    assert desconto_do_resgate(1000) == Decimal("50.00")
    assert maximo_resgatavel(30000, Decimal("612.40")) == 12200
    assert maximo_resgatavel(850, Decimal("900")) == 800
    # Devolução reembolsa o que foi pago: o desconto sai na proporção do preço
    assert valor_devolvido(Decimal("300"), 1, Decimal("60"), Decimal("600")) == Decimal("270.00")
    assert valor_devolvido(Decimal("300"), 2) == Decimal("600.00")


def test_compra_no_site_ganha_o_dobro_sobre_os_produtos(client, mariana):
    sacola = _sacola(client, minimo=100)
    pedido = _comprar(client, mariana, sacola).json()
    pontos = _pontos(client, mariana)
    esperado = round(sacola[2] * 2)  # site = dobro; o frete não conta; sem categoria, sem bônus
    assert pontos["saldo"] == esperado
    assert pedido["pontosGanhos"] == esperado
    assert pontos["categoria"] in ("Bronze", "Prata", "Ouro", "Vip")
    credito = pontos["extrato"][0]
    assert credito["tipo"] == "CREDITO" and credito["quantidade"] == esperado
    assert credito["pedidoNumero"] == pedido["numero"]
    assert credito["venceEm"] == (agora().date().replace(year=agora().year + 1)).isoformat()


@pytest.mark.parametrize(("saldo", "bonus"), [(6000, Decimal("1.25")), (12000, Decimal("1.50")), (1000, Decimal("1"))])
def test_bonus_pela_categoria_antes_da_compra(client, mariana, saldo, bonus):
    _dar_pontos(CLIENTE_DEMO_ID, saldo)
    sacola = _sacola(client, minimo=100)
    _comprar(client, mariana, sacola)
    ganhos = _pontos(client, mariana)["saldo"] - saldo
    assert ganhos == int((Decimal(str(sacola[2])) * 2 * bonus).quantize(Decimal("1"), rounding="ROUND_HALF_UP"))


def test_resgate_vira_desconto_e_a_compra_ainda_ganha_pontos(client, mariana):
    _dar_pontos(CLIENTE_DEMO_ID, 2000)  # Prata: sem bônus
    sacola = _sacola(client, minimo=500)
    resposta = _comprar(client, mariana, sacola, pontos=1000)
    assert resposta.status_code == 201, resposta.text
    pedido = resposta.json()
    assert pedido["desconto"] == 50.0
    assert pedido["total"] == pytest.approx(pedido["subtotal"] - 50 + (pedido["frete"]["valor"] or 0))
    pontos = _pontos(client, mariana)
    tipos = [mov["tipo"] for mov in pontos["extrato"][:2]]
    assert sorted(tipos) == ["CREDITO", "RESGATE"]
    resgate = next(mov for mov in pontos["extrato"] if mov["tipo"] == "RESGATE")
    assert resgate["quantidade"] == -1000 and resgate["valorDesconto"] == 50.0
    assert pontos["saldo"] == 2000 - 1000 + round(sacola[2] * 2)


@pytest.mark.parametrize(
    ("saldo", "pontos", "minimo", "trecho"),
    [
        (5000, 150, 500, "múltiplos de 100"),
        (5000, 1000, None, "pelo menos R$ 500,00"),
        (300, 1000, 500, "Saldo Helo insuficiente"),
    ],
)
def test_resgate_recusado(client, mariana, saldo, pontos, minimo, trecho):
    _dar_pontos(CLIENTE_DEMO_ID, saldo)
    sacola = _sacola(client, minimo=minimo) if minimo else _sacola(client, abaixo_de=500)
    resposta = _comprar(client, mariana, sacola, pontos=pontos)
    assert resposta.status_code == 422
    assert trecho in resposta.json()["detail"]
    assert _pontos(client, mariana)["saldo"] == saldo  # nada foi gravado


def test_cancelar_tira_os_pontos_ganhos_e_devolve_os_usados(client, admin, mariana):
    _dar_pontos(CLIENTE_DEMO_ID, 3000)
    pedido = _comprar(client, mariana, _sacola(client, minimo=500), pontos=2000).json()
    no_painel = _pedido_no_painel(client, admin, pedido["numero"])
    r = client.patch(f"/api/pedidos/{no_painel['id']}", json={"status": "CANCELADO"}, headers=admin)
    assert r.status_code == 200, r.text
    pontos = _pontos(client, mariana)
    assert pontos["saldo"] == 3000
    assert {mov["tipo"] for mov in pontos["extrato"][:2]} == {"ESTORNO", "AJUSTE"}


def test_devolucao_tira_os_pontos_das_pecas_devolvidas(client, mariana):
    sacola = _sacola(client, minimo=100)
    pedido = _comprar(client, mariana, sacola).json()
    ganhos = _pontos(client, mariana)["saldo"]
    with SessionLocal() as db:
        no_banco = db.query(m.Pedido).filter_by(numero=pedido["numero"]).one()
        saiu = fidelidade.estornar_compra(db, no_banco, agora(), fracao=Decimal("0.5"), motivo="Devolução de teste")
        db.commit()
    assert saiu == round(ganhos * 0.5)
    assert _pontos(client, mariana)["saldo"] == ganhos - saiu


def test_pontos_vencem_em_12_meses_gastando_primeiro_os_mais_antigos(client, mariana):
    # Em ordem, como a plataforma lança: 1000 ganhos há 400 dias (venceram), resgate de 300 antes de
    # vencerem (sai dos mais antigos) e 500 ganhos há 30 dias (valem até daqui a ~11 meses)
    _dar_pontos(CLIENTE_DEMO_ID, 1000, ha_dias=400)
    with SessionLocal() as db:
        cliente = db.query(m.Cliente).filter_by(cpf=CLIENTE_DEMO_ID).one()
        fidelidade.lancar(db, cliente.id, "RESGATE", -300, agora() - timedelta(days=380), obs="teste")
        db.commit()
    _dar_pontos(CLIENTE_DEMO_ID, 500, ha_dias=30)
    pontos = _pontos(client, mariana)
    assert pontos["saldo"] == 500  # 1000 − 300 usados = 700 vencidos
    vencimento = pontos["extrato"][0]
    assert vencimento["tipo"] == "VENCIMENTO" and vencimento["quantidade"] == -700
    daqui_a_11_meses = (agora() - timedelta(days=30)).date().replace(year=agora().year + 1)
    assert pontos["aVencer"] == [{"data": daqui_a_11_meses.isoformat(), "pontos": 500}]
    # Consultar de novo não vence duas vezes
    assert _pontos(client, mariana)["saldo"] == 500


def test_equipe_de_atendimento_consulta_os_pontos_do_cliente(client, admin, lojista, operador, mariana):
    _dar_pontos(CLIENTE_DEMO_ID, 7000)
    for headers in (admin, lojista):
        r = client.get(f"/api/clientes/{CLIENTE_DEMO_ID}/pontos", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["saldo"] == 7000 and r.json()["categoria"] == "Ouro" and r.json()["bonus"] == 25
    assert r.json()["valorEmReais"] == 350.0
    assert client.get(f"/api/clientes/{CLIENTE_DEMO_ID}/pontos", headers=operador).status_code == 403
    assert client.get("/api/conta/pontos").status_code == 401
