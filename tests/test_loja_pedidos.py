"""Checkout, "Meus pedidos" (e-mail + PIN) e gestão dos pedidos do e-commerce no painel."""

import base64

import pytest

from src.entities.frete import uf_do_cep
from src.use_cases import meus_pedidos

PIN_DEMO = "1234"
MARIANA = "mariana.costa@gmail.com"  # cliente de demonstração (PIN 1234)
CEP_SP = "01310-100"
# Menor PNG válido (1x1): os anexos são conferidos pela assinatura do arquivo
PNG_1X1 = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4d30000000049454e44ae426082"
    )
).decode()


def _variacao_com_estoque(client, minimo=1):
    """Primeira variação ativa com estoque total >= minimo (e o preço do produto)."""
    for produto in client.get("/api/produtos?ativo=true").json():
        for v in produto["variacoes"]:
            if v["estoqueTotal"] >= minimo:
                return v["id"], produto["precoBase"]
    raise AssertionError("nenhuma variação com estoque")


def _compra(variacao_id, *, email="novo.cliente@exemplo.com", pin="4321", quantidade=1, **extra):
    dados = {
        "email": email,
        "emailConfirmacao": email,
        "pin": pin,
        "pinConfirmacao": pin,
        "nome": "Cliente Novo",
        "telefone": "(11) 99999-0000",
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


def test_checkout_cria_pedido_com_precos_e_frete_do_servidor(client, admin):
    variacao_id, preco = _variacao_com_estoque(client)
    # Preço enviado pelo navegador é ignorado: vale o do cadastro
    dados = _compra(variacao_id)
    dados["itens"][0]["precoUnitario"] = 1
    r = client.post("/api/checkout", json=dados)
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

    # O PIN criado no checkout libera "Meus pedidos"
    meus = client.post("/api/meus-pedidos", json={"email": "NOVO.Cliente@exemplo.com", "pin": "4321"})
    assert meus.status_code == 200
    assert [p["numero"] for p in meus.json()] == [pedido["numero"]]

    # No painel aparece com a loja de expedição e o evento do sistema
    painel = _pedido_no_painel(client, admin, pedido["numero"])
    assert painel["canal"] == "E-commerce" and painel["loja"]["id"]
    assert painel["historico"][0]["observacao"].startswith("Pagamento aprovado")


def test_checkout_de_cliente_existente_exige_o_mesmo_pin(client):
    variacao_id, _ = _variacao_com_estoque(client)
    errado = client.post("/api/checkout", json=_compra(variacao_id, email=MARIANA, pin="9999"))
    assert errado.status_code == 409
    assert "mesmo PIN" in errado.json()["detail"]

    certo = client.post("/api/checkout", json=_compra(variacao_id, email=MARIANA, pin=PIN_DEMO))
    assert certo.status_code == 201
    numeros = [p["numero"] for p in client.post("/api/meus-pedidos", json={"email": MARIANA, "pin": PIN_DEMO}).json()]
    assert certo.json()["numero"] in numeros and len(numeros) > 1  # junta com os pedidos antigos da Mariana


@pytest.mark.parametrize(
    ("alteracao", "status", "trecho"),
    [
        ({"emailConfirmacao": "outro@exemplo.com"}, 422, "e-mails não conferem"),
        ({"pinConfirmacao": "1111"}, 422, "PINs não conferem"),
        ({"pin": "12a4", "pinConfirmacao": "12a4"}, 422, "4 números"),
        ({"itens": []}, 422, "sacola está vazia"),
        ({"pagamento": {"metodo": "BOLETO"}}, 422, "forma de pagamento"),
    ],
)
def test_checkout_valida_os_dados(client, alteracao, status, trecho):
    variacao_id, _ = _variacao_com_estoque(client)
    r = client.post("/api/checkout", json=_compra(variacao_id, **alteracao))
    assert r.status_code == status
    assert trecho in r.json()["detail"]


def test_checkout_recusa_item_esgotado_e_cep_nao_atendido(client):
    variacao_id, _ = _variacao_com_estoque(client)
    total = next(v["estoqueTotal"] for p in client.get("/api/produtos").json() for v in p["variacoes"] if v["id"] == variacao_id)
    if total < 20:
        r = client.post("/api/checkout", json=_compra(variacao_id, quantidade=total + 1))
        assert r.status_code == 409 and "esgotou" in r.json()["detail"]
    sem_entrega = _compra(variacao_id)
    sem_entrega["endereco"]["cep"] = "00000-000"
    assert client.post("/api/checkout", json=sem_entrega).status_code == 422


# ---------- Meus pedidos (PIN) ----------


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


def test_pin_errado_bloqueia_apos_cinco_tentativas(client):
    for _ in range(5):
        r = client.post("/api/meus-pedidos", json={"email": MARIANA, "pin": "0000"})
        assert r.status_code == 401
        assert r.json()["detail"] == "E-mail ou PIN incorretos."
    # Bloqueado: nem o PIN certo entra
    assert client.post("/api/meus-pedidos", json={"email": MARIANA, "pin": PIN_DEMO}).status_code == 429


def test_email_inexistente_tem_a_mesma_resposta_do_pin_errado(client):
    r = client.post("/api/meus-pedidos", json={"email": "ninguem@exemplo.com", "pin": PIN_DEMO})
    assert r.status_code == 401
    assert r.json()["detail"] == "E-mail ou PIN incorretos."


def test_esqueci_e_redefinir_pin(client, monkeypatch):
    monkeypatch.setattr(meus_pedidos, "PIN_LINK_NA_RESPOSTA", True)
    # E-mail desconhecido: mesma resposta, sem link
    assert client.post("/api/meus-pedidos/esqueci-pin", json={"email": "ninguem@exemplo.com"}).json() == {
        "enviado": True,
        "linkDemo": None,
    }
    link = client.post("/api/meus-pedidos/esqueci-pin", json={"email": MARIANA}).json()["linkDemo"]
    assert link.startswith("/meus-pedidos/novo-pin?token=")
    token = link.split("token=")[1]

    assert (
        client.post("/api/meus-pedidos/redefinir-pin", json={"token": token, "pin": "1111", "pinConfirmacao": "2222"}).status_code
        == 422
    )
    r = client.post("/api/meus-pedidos/redefinir-pin", json={"token": token, "pin": "0987", "pinConfirmacao": "0987"})
    assert r.status_code == 200 and r.json() == {"email": MARIANA}

    assert client.post("/api/meus-pedidos", json={"email": MARIANA, "pin": PIN_DEMO}).status_code == 401
    assert client.post("/api/meus-pedidos", json={"email": MARIANA, "pin": "0987"}).status_code == 200
    # Link de uso único
    reuso = client.post("/api/meus-pedidos/redefinir-pin", json={"token": token, "pin": "5555", "pinConfirmacao": "5555"})
    assert reuso.status_code == 410


def test_link_do_pin_nao_vem_na_resposta_com_a_opcao_desligada(client, monkeypatch):
    # Explícito: o teste não pode depender do .env de quem roda (a opção existe só para demonstração)
    monkeypatch.setattr(meus_pedidos, "PIN_LINK_NA_RESPOSTA", False)
    assert client.post("/api/meus-pedidos/esqueci-pin", json={"email": MARIANA}).json() == {"enviado": True, "linkDemo": None}


def test_cliente_abre_chamado_com_foto_e_responde(client):
    numero = client.post("/api/meus-pedidos", json={"email": MARIANA, "pin": PIN_DEMO}).json()[0]["numero"]
    tipo_troca = 1
    r = client.post(
        "/api/meus-pedidos/solicitacoes",
        json={
            "email": MARIANA,
            "pin": PIN_DEMO,
            "numero": numero,
            "tipoSolicitacaoId": tipo_troca,
            "descricao": "A peça veio com a costura aberta na manga.",
            "anexo": {"nome": "manga.png", "tipo": "image/png", "conteudoBase64": PNG_1X1},
        },
    )
    assert r.status_code == 201, r.text
    criado = r.json()
    assert criado["protocolo"].startswith("ATD-") and criado["tipo"]

    chamados = client.post("/api/meus-pedidos/solicitacoes/consulta", json={"email": MARIANA, "pin": PIN_DEMO}).json()
    chamado = next(c for c in chamados if c["id"] == criado["id"])
    assert chamado["pedidoNumero"] == numero
    assert chamado["mensagens"][0]["anexo"]["url"].startswith("data:image/png;base64,")
    assert "responsavel" not in chamado and "loja" not in chamado

    resposta = client.post(
        f"/api/meus-pedidos/solicitacoes/{criado['id']}/mensagens",
        json={"email": MARIANA, "pin": PIN_DEMO, "conteudo": "Posso trocar na loja Oscar Freire?"},
    )
    assert resposta.status_code == 200
    assert resposta.json()["mensagens"][-1]["autorTipo"] == "CLIENTE"


def test_cliente_nao_ve_pedido_nem_chamado_de_outro(client):
    numero_mariana = client.post("/api/meus-pedidos", json={"email": MARIANA, "pin": PIN_DEMO}).json()[0]["numero"]
    outro = "ricardo.fonseca@outlook.com"
    r = client.post(
        "/api/meus-pedidos/solicitacoes",
        json={
            "email": outro,
            "pin": PIN_DEMO,
            "numero": numero_mariana,
            "tipoSolicitacaoId": 1,
            "descricao": "Quero trocar esta peça.",
        },
    )
    assert r.status_code == 404
    chamado_mariana = client.post("/api/meus-pedidos/solicitacoes/consulta", json={"email": MARIANA, "pin": PIN_DEMO}).json()[0]
    r = client.post(
        f"/api/meus-pedidos/solicitacoes/{chamado_mariana['id']}/mensagens",
        json={"email": outro, "pin": PIN_DEMO, "conteudo": "Olá"},
    )
    assert r.status_code == 404


# ---------- Painel ----------


def test_pedidos_do_painel_exigem_login_e_modulo(client, operador, lojista):
    assert client.get("/api/pedidos").status_code == 401
    assert client.get("/api/pedidos", headers=operador).status_code == 200
    assert client.get("/api/pedidos", headers=lojista).status_code == 200


def _loja_sem_e_com_estoque(client, headers, variacao_id):
    estoques = client.get(f"/api/estoque?variacaoId={variacao_id}", headers=headers).json()
    sem = next((e["lojaId"] for e in estoques if e["quantidade"] == 0), None)
    return sem, {e["lojaId"]: e["quantidade"] for e in estoques}


def test_fluxo_completo_com_transferencia_automatica(client, admin):
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
    numero = client.post("/api/checkout", json=_compra(variacao_id)).json()["numero"]
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
    publico = client.post("/api/meus-pedidos", json={"email": "novo.cliente@exemplo.com", "pin": "4321"}).json()[0]
    assert [h["status"] for h in publico["historico"]] == ["PROCESSANDO", "PROCESSANDO", "ENVIADO", "ENTREGUE"]


def test_cancelar_estorna_e_cancela_transferencias_pendentes(client, admin):
    variacao_id, _ = _variacao_com_estoque(client)
    sem, _ = _loja_sem_e_com_estoque(client, admin, variacao_id)
    numero = client.post("/api/checkout", json=_compra(variacao_id)).json()["numero"]
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
