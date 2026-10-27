"""Assistente do site → WhatsApp do atendimento (decisão 81): o chamado nasce com o resumo da conversa e o
link wa.me leva o protocolo, com ou sem login."""

from urllib.parse import parse_qs, urlparse

import pytest

from src.config import settings
from src.entities.atendimento import link_whatsapp
from tests.util_assistente import abrir_site, blocos, diga, entrar, sql

MARIANA = 101
NUMERO = "5511999990000"


@pytest.fixture
def whatsapp(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_ATENDIMENTO", NUMERO)


def _texto_do_link(url: str) -> str:
    partes = urlparse(url)
    assert partes.scheme == "https" and partes.netloc == "wa.me" and partes.path == f"/{NUMERO}"
    return parse_qs(partes.query)["text"][0]


def test_link_leva_protocolo_e_assunto():
    texto = _texto_do_link(link_whatsapp(NUMERO, "ATD-026037", "Troca   da camisa\nno M"))
    assert texto == "Olá! Vim do assistente do site. Protocolo ATD-026037.\nAssunto: Troca da camisa no M"
    assert _texto_do_link(link_whatsapp(NUMERO, "ATD-026037")) == "Olá! Vim do assistente do site. Protocolo ATD-026037."


def test_sem_login_segue_pelo_whatsapp_com_o_resumo(client, whatsapp):
    conversa, chave = abrir_site(client, marca="VULTO")
    diga(client, conversa, chave, "camisa azul")
    oferta = blocos(diga(client, conversa, chave, "quero falar com um atendente"), "acao_atendimento")[0]
    assert oferta["whatsapp"] is True and oferta["precisaLogin"] is True

    r = client.post(
        f"/api/assistente/conversas/{conversa}/atendimento",
        json={"motivo": "Dúvida sobre tamanho", "canal": "WHATSAPP"},
        headers=chave,
    )
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["link"] is None  # sem conta, não há "Minha conta > Solicitações"
    assert corpo["protocolo"] in _texto_do_link(corpo["whatsappUrl"])

    canal, cliente_id, contato, marca, mensagem = sql(
        "SELECT a.canal, a.cliente_id, a.contato, a.marca, m.conteudo FROM atendimentos a "
        "JOIN mensagens m ON m.atendimento_id = a.id WHERE a.protocolo = :p",
        p=corpo["protocolo"],
    )[0]
    assert (canal, cliente_id, contato, marca) == ("WHATSAPP", None, "WhatsApp", "VULTO")
    assert "WhatsApp" in mensagem and "Dúvida sobre tamanho" in mensagem and "camisa azul" in mensagem

    # A conversa mostra o protocolo e o link; pedir de novo devolve o mesmo chamado
    historico = client.get(f"/api/assistente/conversas/{conversa}", headers=chave).json()["mensagens"]
    aberto = [b for msg in historico for b in msg["blocos"] if b["tipo"] == "atendimento_aberto"][0]
    assert aberto["protocolo"] == corpo["protocolo"] and aberto["whatsappUrl"].startswith(f"https://wa.me/{NUMERO}")
    de_novo = client.post(f"/api/assistente/conversas/{conversa}/atendimento", json={"canal": "WHATSAPP"}, headers=chave).json()
    assert de_novo["protocolo"] == corpo["protocolo"]


def test_chamado_do_whatsapp_passa_a_ser_do_cliente_que_entra(client, whatsapp):
    conversa, chave = abrir_site(client)
    diga(client, conversa, chave, "quero falar com uma pessoa")
    protocolo = client.post(
        f"/api/assistente/conversas/{conversa}/atendimento", json={"canal": "WHATSAPP"}, headers=chave
    ).json()["protocolo"]

    logado = {**chave, **entrar(client, "mariana.costa@gmail.com")}
    r = client.post(f"/api/assistente/conversas/{conversa}/atendimento", json={}, headers=logado)
    assert r.status_code == 201 and r.json()["protocolo"] == protocolo
    assert sql("SELECT cliente_id FROM atendimentos WHERE protocolo = :p", p=protocolo)[0][0] == MARIANA


def test_logado_tambem_pode_seguir_pelo_whatsapp(client, whatsapp):
    token = entrar(client, "mariana.costa@gmail.com")
    conversa, chave = abrir_site(client, token=token)
    oferta = blocos(diga(client, conversa, chave, "quero falar com um atendente"), "acao_atendimento")[0]
    assert oferta["whatsapp"] is True and oferta["precisaLogin"] is False
    corpo = client.post(f"/api/assistente/conversas/{conversa}/atendimento", json={"canal": "WHATSAPP"}, headers=chave).json()
    assert corpo["link"] == f"/cliente/solicitacoes/{corpo['atendimentoId']}"
    assert sql("SELECT canal, cliente_id FROM atendimentos WHERE protocolo = :p", p=corpo["protocolo"])[0] == (
        "WHATSAPP",
        MARIANA,
    )


def test_sem_numero_configurado_nao_oferece_whatsapp(client, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_ATENDIMENTO", "")
    conversa, chave = abrir_site(client)
    oferta = blocos(diga(client, conversa, chave, "quero falar com um atendente"), "acao_atendimento")[0]
    assert oferta["whatsapp"] is False
    r = client.post(f"/api/assistente/conversas/{conversa}/atendimento", json={"canal": "WHATSAPP"}, headers=chave)
    assert r.status_code == 422
    assert sql("SELECT count(*) FROM atendimentos WHERE canal = 'WHATSAPP' AND contato = 'WhatsApp'")[0][0] == 0
