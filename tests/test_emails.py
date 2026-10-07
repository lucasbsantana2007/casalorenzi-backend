"""E-mails pelo Resend: o que cada fluxo envia e o formato da chamada à API do Resend."""

import json

import httpx
import pytest

from src.integrations import email as integracao_email
from src.use_cases import administracao, autenticacao, checkout


@pytest.fixture
def enviados(monkeypatch):
    """Captura os e-mails em vez de mandar (cada use case importa a função `enviar_email`)."""
    caixa = []
    for modulo in (autenticacao, administracao, checkout):
        monkeypatch.setattr(modulo, "enviar_email", caixa.append)
    return caixa


def test_esqueci_a_senha_manda_o_link_por_email(client, enviados):
    client.post("/api/auth/esqueci-senha", json={"email": "ninguem@exemplo.com"})
    assert enviados == []  # conta inexistente: nada sai (a resposta da API é a mesma)

    client.post("/api/auth/esqueci-senha", json={"email": "Ricardo.Fonseca@outlook.com"})
    [email] = enviados
    assert email.para == "ricardo.fonseca@outlook.com" and "nova senha" in email.assunto
    link = next(p for p in email.texto.split() if "/login/nova-senha?token=" in p)
    assert link.startswith("http://localhost:5173/login/nova-senha?token=")
    token = link.split("token=")[1]
    r = client.post(
        "/api/auth/redefinir-senha", json={"token": token, "senha": "senha-nova-1", "senhaConfirmacao": "senha-nova-1"}
    )
    assert r.status_code == 200  # o link do e-mail funciona


def test_convite_de_funcionario_vai_por_email(client, admin, enviados):
    dados = {"nome": "Paula Reis", "email": "paula.reis@casalorenzi.com.br", "papel": "LOJISTA", "lojaId": 2}
    r = client.post("/api/admin/funcionarios", headers=admin, json=dados)
    assert r.status_code == 201, r.text
    [email] = enviados
    assert email.para == "paula.reis@casalorenzi.com.br" and "Lojista" in email.texto and "7 dias" in email.texto

    client.post(f"/api/admin/funcionarios/{r.json()['funcionario']['id']}/convite", headers=admin)
    assert len(enviados) == 2  # reenviar manda outro


def test_checkout_manda_a_confirmacao_do_pedido(client, mariana, enviados):
    variacao = next(v for p in client.get("/api/produtos?ativo=true").json() for v in p["variacoes"] if v["estoqueTotal"] > 0)
    compra = {
        "endereco": {
            "cep": "01310-100",
            "rua": "Av. Paulista",
            "numero": "1",
            "bairro": "Bela Vista",
            "cidade": "São Paulo",
            "uf": "SP",
        },
        "freteTipo": "PADRAO",
        "pagamento": {"metodo": "PIX", "parcelas": 1},
        "itens": [{"variacaoId": variacao["id"], "quantidade": 1}],
    }
    numero = client.post("/api/checkout", headers=mariana, json=compra).json()["numero"]
    [email] = enviados
    assert email.para == "mariana.costa@gmail.com" and numero in email.assunto and "R$" in email.texto


def test_chamada_ao_resend(monkeypatch):
    recebido = {}

    def resend(request: httpx.Request) -> httpx.Response:
        recebido["auth"] = request.headers["Authorization"]
        recebido["corpo"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "abc123"})

    monkeypatch.setattr(integracao_email, "RESEND_API_KEY", "re_teste")
    email = integracao_email.Email(para="ana@exemplo.com", assunto="Oi", texto="texto", html="<p>texto</p>")
    with httpx.Client(transport=httpx.MockTransport(resend)) as http:
        assert integracao_email.enviar_agora(email, http) == "abc123"
    assert recebido["auth"] == "Bearer re_teste"
    assert recebido["corpo"]["to"] == ["ana@exemplo.com"] and recebido["corpo"]["subject"] == "Oi"

    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="domínio não verificado"))) as http:
        with pytest.raises(RuntimeError, match="403"):
            integracao_email.enviar_agora(email, http)


def test_sem_chave_o_email_vai_para_o_log(monkeypatch):
    registros = []
    monkeypatch.setattr(integracao_email, "RESEND_API_KEY", "")
    monkeypatch.setattr(integracao_email.log, "info", lambda msg, *args: registros.append(msg % args))
    integracao_email.enviar(integracao_email.Email(para="ana@exemplo.com", assunto="Oi", texto="corpo", html=""))
    assert len(registros) == 1 and "não enviado" in registros[0] and "corpo" in registros[0]
