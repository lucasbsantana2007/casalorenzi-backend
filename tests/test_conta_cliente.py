"""Conta do cliente: cadastro com CPF, login, troca de senha e a área do cliente."""

import base64

import pytest

from src.entities.cliente import cpf_valido
from src.use_cases import autenticacao

MARIANA_ID = "15881399803"  # o id público do cliente é o CPF
RICARDO = "ricardo.fonseca@outlook.com"
PNG_1X1 = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4d30000000049454e44ae426082"
    )
).decode()


def _cadastro(**extra):
    dados = {
        "nome": "Ana Beatriz Souza",
        "cpf": "529.982.247-25",
        "email": "ana.souza@exemplo.com",
        "telefone": "(61) 98888-7777",
        "senha": "minha-senha",
        "senhaConfirmacao": "minha-senha",
    }
    return {**dados, **extra}


def test_cpf_valido():
    assert cpf_valido("529.982.247-25") and cpf_valido("15881399803")
    assert not cpf_valido("111.111.111-11") and not cpf_valido("12345678900") and not cpf_valido("1234")


def test_cadastro_cria_conta_e_ja_entra(client):
    r = client.post("/api/auth/cadastro", json=_cadastro())
    assert r.status_code == 201, r.text
    usuario = r.json()["usuario"]
    assert (
        usuario["papel"] == "CLIENTE"
        and usuario["id"] == usuario["cpf"] == "52998224725"
        and usuario["nome"] == "Ana Beatriz Souza"
    )

    login = client.post("/api/auth/login", json={"email": "ANA.SOUZA@exemplo.com", "senha": "minha-senha"})
    assert login.status_code == 200 and login.json()["usuario"]["id"] == usuario["id"]


@pytest.mark.parametrize(
    ("alteracao", "status", "trecho"),
    [
        ({"nome": "  "}, 422, "nome completo"),
        ({"cpf": "123.456.789-00"}, 422, "CPF inválido"),
        ({"email": "ana@"}, 422, "e-mail válido"),
        ({"senha": "curta", "senhaConfirmacao": "curta"}, 422, "8 caracteres"),
        ({"senhaConfirmacao": "outra-senha"}, 422, "não conferem"),
        ({"cpf": "158.813.998-03"}, 409, "com este CPF"),  # Mariana
        ({"email": "MARIANA.COSTA@gmail.com"}, 409, "com este e-mail"),
        ({"email": "helena@casalorenzi.com.br"}, 409, "com este e-mail"),  # e-mail da equipe
    ],
)
def test_cadastro_valida_os_dados(client, alteracao, status, trecho):
    r = client.post("/api/auth/cadastro", json=_cadastro(**alteracao))
    assert r.status_code == status
    assert trecho in r.json()["detail"]


def test_login_errado_tem_a_mesma_mensagem(client):
    errada = client.post("/api/auth/login", json={"email": RICARDO, "senha": "nao-e-essa"})
    inexistente = client.post("/api/auth/login", json={"email": "ninguem@exemplo.com", "senha": "nao-e-essa"})
    assert errada.status_code == inexistente.status_code == 401
    assert errada.json() == inexistente.json()


def test_esqueci_e_redefinir_senha(client, monkeypatch):
    monkeypatch.setattr(autenticacao, "LINK_SENHA_NA_RESPOSTA", True)
    # Mesma resposta exista ou não a conta
    assert client.post("/api/auth/esqueci-senha", json={"email": "ninguem@exemplo.com"}).json() == {
        "enviado": True,
        "linkDemo": None,
    }
    link = client.post("/api/auth/esqueci-senha", json={"email": RICARDO}).json()["linkDemo"]
    assert link.startswith("/login/nova-senha?token=")
    token = link.split("token=")[1]

    nao_confere = {"token": token, "senha": "nova-senha-1", "senhaConfirmacao": "nova-senha-2"}
    assert client.post("/api/auth/redefinir-senha", json=nao_confere).status_code == 422
    r = client.post("/api/auth/redefinir-senha", json={"token": token, "senha": "nova-senha", "senhaConfirmacao": "nova-senha"})
    assert r.status_code == 200 and r.json() == {"email": RICARDO}

    assert client.post("/api/auth/login", json={"email": RICARDO, "senha": "lorenzi2026"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": RICARDO, "senha": "nova-senha"}).status_code == 200
    reuso = client.post(
        "/api/auth/redefinir-senha", json={"token": token, "senha": "outra-senha", "senhaConfirmacao": "outra-senha"}
    )
    assert reuso.status_code == 410


def test_link_da_senha_nao_vem_na_resposta_com_a_opcao_desligada(client, monkeypatch):
    monkeypatch.setattr(autenticacao, "LINK_SENHA_NA_RESPOSTA", False)
    assert client.post("/api/auth/esqueci-senha", json={"email": RICARDO}).json() == {"enviado": True, "linkDemo": None}


def test_esqueci_a_senha_limita_tentativas(client):
    # Por e-mail: 3 pedidos em 15 minutos; o 4º é recusado, exista ou não a conta
    for email in (RICARDO, "ninguem@exemplo.com"):
        for _ in range(3):
            assert client.post("/api/auth/esqueci-senha", json={"email": email}).status_code == 200
        r = client.post("/api/auth/esqueci-senha", json={"email": email})
        assert r.status_code == 429 and "Muitas tentativas" in r.json()["detail"]
    # Por IP: no máximo 10 pedidos, mesmo trocando o e-mail
    codigos = [client.post("/api/auth/esqueci-senha", json={"email": f"pessoa{i}@exemplo.com"}).status_code for i in range(6)]
    assert codigos == [200, 200, 200, 200, 429, 429]  # 6 já usados acima (3 + 3) + 4 = 10


def test_area_do_cliente_so_mostra_o_que_e_dele(client, mariana):
    conta = client.get(f"/api/clientes/{MARIANA_ID}", headers=mariana)
    assert conta.status_code == 200 and conta.json()["totalPedidos"] >= 1
    pedidos = client.get(f"/api/clientes/{MARIANA_ID}/pedidos", headers=mariana).json()
    numero = pedidos[0]["numero"]
    # Número com ou sem o prefixo
    for termo in (numero, numero.removeprefix("CL-")):
        r = client.get(f"/api/clientes/{MARIANA_ID}/pedidos/{termo}", headers=mariana)
        assert r.status_code == 200 and r.json()["numero"] == numero
    nao_achou = client.get(f"/api/clientes/{MARIANA_ID}/pedidos/999999", headers=mariana)
    assert nao_achou.status_code == 404 and "esse número" in nao_achou.json()["detail"]

    # Outro cliente: aparece como inexistente
    for rota in ("", "/pedidos", "/atendimentos", f"/pedidos/{numero}"):
        assert client.get(f"/api/clientes/69879730917{rota}", headers=mariana).status_code == 404
    # Sem sessão
    assert client.get(f"/api/clientes/{MARIANA_ID}").status_code == 401


def test_cliente_abre_chamado_com_foto_e_conversa_com_a_equipe(client, mariana, admin):
    pedido = client.get(f"/api/clientes/{MARIANA_ID}/pedidos", headers=mariana).json()[0]
    tipos = client.get("/api/tipos-solicitacao").json()
    tipo = next(t for t in tipos if t["exigeVenda"])
    r = client.post(
        "/api/atendimentos",
        headers=mariana,
        json={
            "clienteId": "69879730917",  # ignorado: o chamado é de quem está logado
            "tipoSolicitacaoId": tipo["id"],
            "pedidoId": pedido["id"],
            "descricao": "A camisa veio com um botão solto.",
            "anexo": {"nome": "botao.png", "tipo": "image/png", "conteudoBase64": PNG_1X1},
        },
    )
    assert r.status_code == 201, r.text
    chamado = r.json()
    assert chamado["cliente"]["id"] == MARIANA_ID
    assert chamado["mensagens"][0]["autorTipo"] == "CLIENTE" and chamado["mensagens"][0]["anexo"]

    detalhe = client.get(f"/api/clientes/{MARIANA_ID}/atendimentos/{chamado['id']}", headers=mariana)
    assert detalhe.status_code == 200 and detalhe.json()["protocolo"] == chamado["protocolo"]

    # A equipe responde; o cliente responde de volta (autor vem do token)
    assert (
        client.post(f"/api/atendimentos/{chamado['id']}/mensagens", headers=admin, json={"conteudo": "Vamos trocar."}).status_code
        == 201
    )
    resposta = client.post(
        f"/api/atendimentos/{chamado['id']}/mensagens", headers=mariana, json={"conteudo": "Obrigada!", "autorTipo": "ATENDENTE"}
    )
    assert resposta.status_code == 201
    assert [m["autorTipo"] for m in resposta.json()["mensagens"] if m["autorTipo"] != "SISTEMA"][-2:] == ["ATENDENTE", "CLIENTE"]


def test_cliente_nao_ve_nem_responde_chamado_de_outro(client, mariana, admin):
    outro = client.get("/api/clientes/69879730917/atendimentos", headers=admin).json()
    if not outro:
        pytest.skip("Ricardo sem chamados no seed")
    chamado_id = outro[0]["id"]
    assert client.get(f"/api/clientes/{MARIANA_ID}/atendimentos/{chamado_id}", headers=mariana).status_code == 404
    r = client.post(f"/api/atendimentos/{chamado_id}/mensagens", headers=mariana, json={"conteudo": "Olá"})
    assert r.status_code == 404
    # Rotas só da equipe continuam fechadas para o cliente
    assert client.patch(f"/api/atendimentos/{chamado_id}", headers=mariana, json={"status": "CONCLUIDO"}).status_code == 401
