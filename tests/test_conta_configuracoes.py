"""Configurações da conta do cliente: ver e editar dados, trocar a senha e excluir a conta."""

import pytest

MARIANA = "mariana.costa@gmail.com"
SENHA = "lorenzi2026"


def _login(client, email, senha=SENHA):
    return client.post("/api/auth/login", json={"email": email, "senha": senha})


def test_cliente_ve_os_proprios_dados(client, mariana):
    r = client.get("/api/conta", headers=mariana)
    assert r.status_code == 200
    assert r.json() == {
        "id": 101,
        "nome": "Mariana Costa",
        "email": MARIANA,
        "cpf": "15881399803",
        "telefone": r.json()["telefone"],
        "clienteDesde": r.json()["clienteDesde"],
    }
    assert r.json()["telefone"] and r.json()["clienteDesde"]


def test_so_o_cliente_usa_as_configuracoes_da_conta(client, admin):
    assert client.get("/api/conta").status_code == 401
    assert client.get("/api/conta", headers=admin).status_code == 401


def test_editar_nome_e_telefone(client, mariana):
    r = client.put(
        "/api/conta", headers=mariana, json={"nome": "Mariana C. Lima", "email": MARIANA, "telefone": "(11) 98888-0000"}
    )
    assert r.status_code == 200
    assert r.json()["nome"] == "Mariana C. Lima" and r.json()["telefone"] == "(11) 98888-0000"
    assert client.get("/api/conta", headers=mariana).json()["nome"] == "Mariana C. Lima"


def test_trocar_email_pede_a_senha_atual(client, mariana):
    novo = {"nome": "Mariana Costa", "email": "Mariana.Nova@exemplo.com", "telefone": ""}
    sem_senha = client.put("/api/conta", headers=mariana, json=novo)
    assert sem_senha.status_code == 422 and "senha atual" in sem_senha.json()["detail"]
    errada = client.put("/api/conta", headers=mariana, json={**novo, "senhaAtual": "errada"})
    assert errada.status_code == 422 and errada.json()["detail"] == "A senha atual está incorreta."

    r = client.put("/api/conta", headers=mariana, json={**novo, "senhaAtual": SENHA})
    assert r.status_code == 200 and r.json()["email"] == "mariana.nova@exemplo.com"
    assert _login(client, MARIANA).status_code == 401
    assert _login(client, "mariana.nova@exemplo.com").status_code == 200


@pytest.mark.parametrize(
    ("dados", "status", "trecho"),
    [
        ({"nome": "  "}, 422, "nome completo"),
        ({"email": "sem-arroba"}, 422, "e-mail válido"),
        ({"email": "ricardo.fonseca@outlook.com", "senhaAtual": SENHA}, 409, "Já existe uma conta"),
        ({"email": "helena@casalorenzi.com.br", "senhaAtual": SENHA}, 409, "Já existe uma conta"),
    ],
)
def test_editar_dados_valida(client, mariana, dados, status, trecho):
    r = client.put("/api/conta", headers=mariana, json={"nome": "Mariana Costa", "email": MARIANA, "telefone": "", **dados})
    assert r.status_code == status and trecho in r.json()["detail"]


def test_cpf_nao_muda(client, mariana):
    r = client.put("/api/conta", headers=mariana, json={"nome": "Mariana Costa", "email": MARIANA, "cpf": "52998224725"})
    assert r.status_code == 200 and r.json()["cpf"] == "15881399803"


def test_trocar_senha(client, mariana):
    def trocar(**dados):
        corpo = {"senhaAtual": SENHA, "senha": "nova-senha-1", "senhaConfirmacao": "nova-senha-1", **dados}
        return client.put("/api/conta/senha", headers=mariana, json=corpo)

    assert trocar(senhaAtual="errada").json()["detail"] == "A senha atual está incorreta."
    assert "8 caracteres" in trocar(senha="curta", senhaConfirmacao="curta").json()["detail"]
    assert "não conferem" in trocar(senhaConfirmacao="outra-coisa").json()["detail"]
    assert "diferente da atual" in trocar(senha=SENHA, senhaConfirmacao=SENHA).json()["detail"]

    assert trocar().status_code == 204
    assert _login(client, MARIANA).status_code == 401
    assert _login(client, MARIANA, "nova-senha-1").status_code == 200


def test_excluir_conta_apaga_os_dados_e_encerra_o_acesso(client, mariana, admin):
    errada = client.post("/api/conta/exclusao", headers=mariana, json={"senha": "errada"})
    assert errada.status_code == 422
    pedidos_antes = [p["numero"] for p in client.get("/api/clientes/101/pedidos", headers=admin).json()]

    assert client.post("/api/conta/exclusao", headers=mariana, json={"senha": SENHA}).status_code == 204
    # O token deixa de valer e o login não entra mais
    assert client.get("/api/conta", headers=mariana).status_code == 401
    assert _login(client, MARIANA).status_code == 401
    # O e-mail e o CPF ficam livres para uma conta nova
    nova = {
        "nome": "Mariana Costa",
        "cpf": "158.813.998-03",
        "email": MARIANA,
        "telefone": "",
        "senha": "outra-senha",
        "senhaConfirmacao": "outra-senha",
    }
    assert client.post("/api/auth/cadastro", json=nova).status_code == 201

    # Para a equipe: dados pessoais apagados, pedidos mantidos (anônimos) e fora da busca de clientes
    antiga = client.get("/api/clientes/101", headers=admin).json()
    assert antiga["nome"] == "Cliente excluído" and antiga["cpf"] is None and antiga["telefone"] is None and antiga["excluido"]
    pedidos = client.get("/api/clientes/101/pedidos", headers=admin).json()
    assert [p["numero"] for p in pedidos] == pedidos_antes and pedidos_antes
    assert {p["contato"]["nome"] for p in pedidos} == {"Cliente excluído"}
    assert [c["id"] for c in client.get("/api/clientes?busca=Cliente exclu", headers=admin).json()] == []
