"""Checkout (com conta de cliente) e gestão dos pedidos no painel."""

import pytest

from src.entities.frete import uf_do_cep

CLIENTE_DEMO_ID = "15881399803"  # Mariana (id público = CPF)
CEP_SP = "01310-100"


def _variacao_com_estoque(client, minimo=1):
    """Primeira variação ativa com estoque total >= minimo (e o preço do produto)."""
    for produto in client.get("/api/produtos?ativo=true").json():
        for v in produto["variacoes"]:
            if v["estoqueTotal"] >= minimo:
                return v["id"], produto["precoBase"]
    raise AssertionError("nenhuma variação com estoque")


def _compra(variacao_id, *, quantidade=1, **extra):
    """O cliente vem do token (conta do cliente), não do corpo."""
    dados = {
        "endereco": {
            "cep": CEP_SP,
            "rua": "Av. Paulista",
            "numero": "1000",
            "bairro": "Bela Vista",
            "cidade": "São Paulo",
            "uf": "SP",
        },
        "freteTipo": "PADRAO",
        "pagamento": {"metodo": "CARTAO", "parcelas": 3},
        "itens": [{"variacaoId": variacao_id, "quantidade": quantidade}],
    }
    dados.update(extra)
    return dados


def _pedido_no_painel(client, headers, numero):
    lista = client.get(f"/api/pedidos?busca={numero}", headers=headers).json()
    assert len(lista) == 1
    return lista[0]


# ---------- Checkout ----------


def test_checkout_cria_pedido_com_precos_e_frete_do_servidor(client, admin, novo_cliente):
    headers, cliente_id = novo_cliente
    variacao_id, preco = _variacao_com_estoque(client)
    # Preço enviado pelo navegador é ignorado: vale o do cadastro
    dados = _compra(variacao_id)
    dados["itens"][0]["precoUnitario"] = 1
    r = client.post("/api/checkout", json=dados, headers=headers)
    assert r.status_code == 201, r.text
    pedido = r.json()
    assert pedido["numero"].startswith("CL-") and pedido["status"] == "PROCESSANDO"
    assert pedido["subtotal"] == preco
    frete_esperado = 0 if preco >= 1000 else 19.9  # SP: padrão R$ 19,90, grátis a partir de R$ 1.000
    assert pedido["frete"] == {"tipo": "PADRAO", "label": "Padrão", "valor": frete_esperado, "prazoDias": 3}
    assert pedido["total"] == pytest.approx(preco + frete_esperado)
    assert pedido["pagamento"] == {"metodo": "CARTAO", "parcelas": 3, "status": "APROVADO"}
    assert pedido["historico"][0]["status"] == "PROCESSANDO"
    assert "loja" not in pedido and "transferencias" not in pedido  # visão pública

    # Aparece na área do cliente
    meus = client.get(f"/api/clientes/{cliente_id}/pedidos", headers=headers)
    assert meus.status_code == 200
    assert [p["numero"] for p in meus.json()] == [pedido["numero"]]

    # No painel aparece com a loja de expedição e o evento do sistema
    painel = _pedido_no_painel(client, admin, pedido["numero"])
    assert painel["canal"] == "E-commerce" and painel["loja"]["id"]
    assert painel["historico"][0]["observacao"].startswith("Pagamento aprovado")


def test_checkout_exige_conta_de_cliente(client, admin, mariana):
    variacao_id, _ = _variacao_com_estoque(client)
    assert client.post("/api/checkout", json=_compra(variacao_id)).status_code == 401
    # Conta da equipe não compra
    equipe = client.post("/api/checkout", json=_compra(variacao_id), headers=admin)
    assert equipe.status_code == 401 and "conta de cliente" in equipe.json()["detail"]

    certo = client.post("/api/checkout", json=_compra(variacao_id), headers=mariana)
    assert certo.status_code == 201
    numeros = [p["numero"] for p in client.get(f"/api/clientes/{CLIENTE_DEMO_ID}/pedidos", headers=mariana).json()]
    assert certo.json()["numero"] in numeros and len(numeros) > 1  # junta com os pedidos antigos da Mariana


@pytest.mark.parametrize(
    ("alteracao", "status", "trecho"),
    [
        ({"itens": []}, 422, "sacola está vazia"),
        ({"pagamento": {"metodo": "BOLETO"}}, 422, "forma de pagamento"),
    ],
)
def test_checkout_valida_os_dados(client, mariana, alteracao, status, trecho):
    variacao_id, _ = _variacao_com_estoque(client)
    r = client.post("/api/checkout", json=_compra(variacao_id, **alteracao), headers=mariana)
    assert r.status_code == status
    assert trecho in r.json()["detail"]


def test_checkout_recusa_item_esgotado_e_cep_nao_atendido(client, mariana):
    variacao_id, _ = _variacao_com_estoque(client)
    total = next(v["estoqueTotal"] for p in client.get("/api/produtos").json() for v in p["variacoes"] if v["id"] == variacao_id)
    if total < 20:
        r = client.post("/api/checkout", json=_compra(variacao_id, quantidade=total + 1), headers=mariana)
        assert r.status_code == 409 and "esgotou" in r.json()["detail"]
    sem_entrega = _compra(variacao_id)
    sem_entrega["endereco"]["cep"] = "00000-000"
    assert client.post("/api/checkout", json=sem_entrega, headers=mariana).status_code == 422


# ---------- Expedição ----------


@pytest.mark.parametrize(
    "cep, uf",
    [
        ("01310-100", "SP"),
        ("22430-041", "RJ"),
        ("30320-570", "MG"),
        ("71680-357", "DF"),
        ("80420-090", "PR"),
        ("72800-000", None),
        ("4000", None),
    ],
)
def test_uf_do_cep_cobre_os_estados_das_lojas(cep, uf):
    assert uf_do_cep(cep) == uf


# ---------- Painel ----------


def test_pedidos_do_painel_exigem_login_e_modulo(client, operador, lojista):
    assert client.get("/api/pedidos").status_code == 401
    assert client.get("/api/pedidos", headers=operador).status_code == 200
    assert client.get("/api/pedidos", headers=lojista).status_code == 200


def test_lojista_e_operador_so_veem_pedidos_da_propria_loja(client, admin, lojista, operador):
    todos = client.get("/api/pedidos", headers=admin).json()
    de_outra_loja = next(p for p in todos if p["lojaId"] != 1)
    da_loja_1 = next(p for p in todos if p["lojaId"] == 1)
    for headers in (lojista, operador):  # os dois são da loja 1 no seed
        # Mesmo pedindo outra loja, a lista vem só com a própria
        for rota in ("/api/pedidos", f"/api/pedidos?lojaId={de_outra_loja['lojaId']}"):
            assert {p["lojaId"] for p in client.get(rota, headers=headers).json()} == {1}
        # Pedido de outra loja aparece como inexistente, inclusive pagamentos e devolução
        assert client.get(f"/api/pedidos/{de_outra_loja['id']}", headers=headers).status_code == 404
        assert client.get(f"/api/pedidos/{de_outra_loja['id']}/pagamentos", headers=headers).status_code == 404
        devolucao = {"itemPedidoId": de_outra_loja["itens"][0]["id"], "quantidade": 1, "motivo": "teste"}
        assert client.post(f"/api/pedidos/{de_outra_loja['id']}/devolucoes", headers=headers, json=devolucao).status_code == 404
        assert (
            client.patch(f"/api/pedidos/{de_outra_loja['id']}", headers=headers, json={"status": "ENTREGUE"}).status_code == 404
        )
        assert client.get(f"/api/pedidos/{da_loja_1['id']}", headers=headers).status_code == 200
    assert len(client.get("/api/pedidos", headers=admin).json()) == len(todos)


def test_so_o_administrador_troca_a_loja_de_expedicao(client, admin, operador, mariana):
    variacao_id, _ = _variacao_com_estoque(client)
    numero = client.post("/api/checkout", json=_compra(variacao_id), headers=mariana).json()["numero"]
    pedido = _pedido_no_painel(client, admin, numero)
    if pedido["lojaId"] != 1:  # leva para a loja do operador, para ele enxergar o pedido
        pedido = client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"lojaId": 1}).json()

    r = client.patch(f"/api/pedidos/{pedido['id']}", headers=operador, json={"lojaId": 2})
    assert r.status_code == 403 and "administrador" in r.json()["detail"]
    assert client.get(f"/api/pedidos/{pedido['id']}", headers=admin).json()["lojaId"] == 1


def _loja_sem_e_com_estoque(client, headers, variacao_id):
    estoques = client.get(f"/api/estoque?variacaoId={variacao_id}", headers=headers).json()
    sem = next((e["lojaId"] for e in estoques if e["quantidade"] == 0), None)
    return sem, {e["lojaId"]: e["quantidade"] for e in estoques}


def test_fluxo_completo_com_transferencia_automatica(client, admin, novo_cliente):
    headers, cliente_id = novo_cliente
    # Variação com estoque em alguma loja e zerada em outra
    for produto in client.get("/api/produtos?ativo=true").json():
        for v in produto["variacoes"]:
            sem, saldos = _loja_sem_e_com_estoque(client, admin, v["id"])
            if sem and v["estoqueTotal"] >= 1:
                variacao_id = v["id"]
                break
        else:
            continue
        break
    numero = client.post("/api/checkout", json=_compra(variacao_id), headers=headers).json()["numero"]
    pedido = _pedido_no_painel(client, admin, numero)

    # Expedição passa para a loja sem a peça: o sistema pede a transferência
    r = client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"lojaId": sem})
    assert r.status_code == 200, r.text
    pedido = r.json()
    assert pedido["loja"]["id"] == sem
    assert pedido["itens"][0]["saldoNaLoja"] == 0
    assert len(pedido["transferencias"]) == 1 and pedido["transferencias"][0]["status"] == "SOLICITADA"
    assert pedido["historico"][-1]["usuario"]["nome"] == "Helena Lorenzi"

    # Sem a peça na loja, não envia
    enviar = {"status": "ENVIADO", "codigoRastreio": "br123456789sp"}
    assert client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json=enviar).status_code == 409

    t = pedido["transferencias"][0]
    for status in ("EM_TRANSITO", "CONCLUIDA"):
        assert client.patch(f"/api/transferencias/{t['id']}", headers=admin, json={"status": status}).status_code == 200

    r = client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json=enviar)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ENVIADO" and r.json()["codigoRastreio"] == "BR123456789SP"
    # A peça saiu do estoque da loja de expedição (venda)
    _, saldos_depois = _loja_sem_e_com_estoque(client, admin, variacao_id)
    assert saldos_depois[sem] == 0

    assert client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"status": "ENTREGUE"}).json()["status"] == "ENTREGUE"
    # Fora do fluxo
    assert client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"status": "CANCELADO"}).status_code == 409
    publico = client.get(f"/api/clientes/{cliente_id}/pedidos/{numero.removeprefix('CL-')}", headers=headers).json()
    assert publico["status"] == "ENTREGUE" and publico["codigoRastreio"] == "BR123456789SP"


def test_cancelar_estorna_e_cancela_transferencias_pendentes(client, admin, mariana):
    variacao_id, _ = _variacao_com_estoque(client)
    sem, _ = _loja_sem_e_com_estoque(client, admin, variacao_id)
    numero = client.post("/api/checkout", json=_compra(variacao_id), headers=mariana).json()["numero"]
    pedido = _pedido_no_painel(client, admin, numero)
    if sem and sem != pedido["loja"]["id"]:
        pedido = client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"lojaId": sem}).json()

    r = client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"status": "CANCELADO"})
    assert r.status_code == 200
    cancelado = r.json()
    assert cancelado["status"] == "CANCELADO"
    assert cancelado["pagamento"]["status"] == "ESTORNADO"
    assert all(t["status"] == "CANCELADA" for t in cancelado["transferencias"])
    # Cancelado não troca de loja
    assert client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"lojaId": 1}).status_code == 409
