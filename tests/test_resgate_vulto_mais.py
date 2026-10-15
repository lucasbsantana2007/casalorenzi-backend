"""Resgate de pontos Vulto+ no checkout: compra mínima de R$ 500 em produtos (sem o frete), múltiplos de
100, sem passar do saldo nem do valor dos produtos; cancelar o pedido devolve os pontos."""

import math
from decimal import Decimal

import pytest

from src.database.seed.dados import PONTOS_VULTO_MAIS
from src.entities.devolucao import valor_devolvido
from src.entities.fidelidade import desconto_do_resgate, maximo_resgatavel
from tests.test_loja_pedidos import _compra, _pedido_no_painel

SALDO_MARIANA = PONTOS_VULTO_MAIS[101]  # 12.000 pontos = R$ 600


def _sacola(client, *, minimo: float | None = None, abaixo_de: float | None = None):
    """(variação, quantidade, subtotal) com pelo menos `minimo` (a mais próxima dele) ou abaixo de `abaixo_de` em produtos."""
    opcoes = []
    for produto in client.get("/api/produtos?ativo=true").json():
        preco = produto["precoBase"]
        for v in produto["variacoes"]:
            if abaixo_de is not None and preco < abaixo_de and v["estoqueTotal"] >= 1:
                return v["id"], 1, preco
            if minimo is not None:
                quantidade = math.ceil(minimo / preco)
                if quantidade <= min(v["estoqueTotal"], 20):
                    opcoes.append((v["id"], quantidade, preco * quantidade))
    assert opcoes, "nenhuma variação serve"
    return min(opcoes, key=lambda o: o[2])


def _pontos(client, headers):
    return client.get("/api/conta/pontos", headers=headers).json()


def _comprar(client, headers, sacola, pontos):
    variacao_id, quantidade, _ = sacola
    return client.post("/api/checkout", json=_compra(variacao_id, quantidade=quantidade, pontos=pontos), headers=headers)


def test_regras_do_resgate():
    assert desconto_do_resgate(1000) == Decimal("50.00")  # 100 pontos = R$ 5
    assert maximo_resgatavel(30000, Decimal("612.40")) == 12200  # não passa do valor dos produtos
    assert maximo_resgatavel(850, Decimal("900")) == 800  # múltiplos de 100
    # Devolução reembolsa o que foi pago: o desconto sai na proporção do preço
    assert valor_devolvido(Decimal("300"), 1, Decimal("60"), Decimal("600")) == Decimal("270.00")
    assert valor_devolvido(Decimal("300"), 2) == Decimal("600.00")


def test_extrato_de_pontos_do_cliente(client, mariana, novo_cliente):
    extrato = _pontos(client, mariana)
    assert extrato["saldo"] == SALDO_MARIANA and extrato["saldoEmReais"] == 600.0
    assert extrato["resgate"] == {"compraMinima": 500.0, "multiplo": 100, "valorPonto": 0.05}
    assert extrato["movimentos"][0]["tipo"] == "SALDO_INICIAL"
    # Cliente sem pontos: saldo zero; sem sessão de cliente: 401
    assert _pontos(client, novo_cliente[0])["saldo"] == 0
    assert client.get("/api/conta/pontos").status_code == 401


def test_compra_abaixo_de_500_nao_usa_pontos(client, mariana):
    sacola = _sacola(client, abaixo_de=500)
    r = _comprar(client, mariana, sacola, 100)
    assert r.status_code == 422
    assert "R$ 500,00 em produtos (sem o frete)" in r.json()["detail"]
    assert _pontos(client, mariana)["saldo"] == SALDO_MARIANA
    assert _comprar(client, mariana, sacola, 0).status_code == 201  # sem pontos a compra passa


def test_resgate_desconta_do_total_e_do_saldo(client, admin, mariana):
    sacola = _sacola(client, minimo=500)
    r = _comprar(client, mariana, sacola, 1000)
    assert r.status_code == 201, r.text
    pedido = r.json()
    assert pedido["subtotal"] == pytest.approx(sacola[2])
    assert pedido["desconto"] == 50.0
    assert pedido["total"] == pytest.approx(sacola[2] - 50 + pedido["frete"]["valor"])

    extrato = _pontos(client, mariana)
    assert extrato["saldo"] == SALDO_MARIANA - 1000
    resgate = extrato["movimentos"][0]
    assert (resgate["tipo"], resgate["quantidade"], resgate["pedido"]) == ("RESGATE", -1000, pedido["numero"])
    # O painel mostra o desconto do pedido
    assert _pedido_no_painel(client, admin, pedido["numero"])["desconto"] == 50.0


@pytest.mark.parametrize(
    "pontos, trecho",
    [(150, "múltiplos de 100"), (-100, "múltiplos de 100"), (SALDO_MARIANA + 100, "insuficiente"), (SALDO_MARIANA, "no máximo")],
)
def test_resgate_invalido_nao_cria_pedido(client, mariana, pontos, trecho):
    sacola = _sacola(client, minimo=500)
    assert sacola[2] < SALDO_MARIANA * 0.05  # o saldo inteiro passa do valor dos produtos
    antes = len(client.get("/api/clientes/15881399803/pedidos", headers=mariana).json())
    r = _comprar(client, mariana, sacola, pontos)
    assert r.status_code == 422
    assert trecho in r.json()["detail"]
    assert len(client.get("/api/clientes/15881399803/pedidos", headers=mariana).json()) == antes
    assert _pontos(client, mariana)["saldo"] == SALDO_MARIANA


def test_cliente_sem_pontos_nao_resgata(client, novo_cliente):
    r = _comprar(client, novo_cliente[0], _sacola(client, minimo=500), 100)
    assert r.status_code == 422
    assert "você tem 0 pontos" in r.json()["detail"]


def test_cancelar_pedido_devolve_os_pontos(client, admin, mariana):
    numero = _comprar(client, mariana, _sacola(client, minimo=500), 2000).json()["numero"]
    assert _pontos(client, mariana)["saldo"] == SALDO_MARIANA - 2000

    pedido = _pedido_no_painel(client, admin, numero)
    cancelado = client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"status": "CANCELADO"}).json()
    assert cancelado["historico"][-1]["observacao"] == "Pagamento estornado e 2000 pontos Vulto+ devolvidos"

    extrato = _pontos(client, mariana)
    assert extrato["saldo"] == SALDO_MARIANA
    devolucao = extrato["movimentos"][0]
    assert (devolucao["tipo"], devolucao["quantidade"], devolucao["pedido"]) == ("AJUSTE", 2000, numero)
