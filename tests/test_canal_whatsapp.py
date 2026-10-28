"""A Lúcia no WhatsApp (decisão 108): o n8n chama a API com o segredo do canal; uma conversa por telefone, a mesma
mensagem não é respondida duas vezes, os cards viram texto com links e o pedido de pessoa abre o chamado na hora."""

import pytest
from sqlalchemy import select

from src import models as m
from src.config import settings
from src.database.connection import SessionLocal
from src.entities import assistente as regra
from src.integrations import ia
from src.use_cases.assistente import canal_whatsapp
from tests.ia_falsa import ProvedorFalso, texto

URL = "/api/canais/whatsapp/mensagens"
SEGREDO = "segredo-do-canal-de-teste"
TELEFONE = "5511987654321"


@pytest.fixture(autouse=True)
def canal(monkeypatch):
    monkeypatch.setattr(settings, "CANAL_WHATSAPP_SEGREDO", SEGREDO)


def diga(client, mensagem, telefone=TELEFONE, id_mensagem=None, nome="Ana"):
    corpo = {"telefone": telefone, "texto": mensagem, "idMensagem": id_mensagem, "nome": nome}
    resposta = client.post(URL, json=corpo, headers={"X-Canal-Segredo": SEGREDO})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def conversas_do_canal() -> list[m.ConversaAssistente]:
    with SessionLocal() as db:
        return list(db.scalars(select(m.ConversaAssistente).where(m.ConversaAssistente.tipo == regra.CLIENTE)))


def test_sem_segredo_configurado_a_rota_nao_existe(client, monkeypatch):
    monkeypatch.setattr(settings, "CANAL_WHATSAPP_SEGREDO", "")
    assert client.post(URL, json={"telefone": TELEFONE, "texto": "oi"}, headers={"X-Canal-Segredo": ""}).status_code == 404


def test_segredo_errado_ou_ausente(client):
    assert client.post(URL, json={"telefone": TELEFONE, "texto": "oi"}).status_code == 401
    errado = client.post(URL, json={"telefone": TELEFONE, "texto": "oi"}, headers={"X-Canal-Segredo": "outro"})
    assert errado.status_code == 401


def test_telefone_invalido(client):
    resposta = client.post(URL, json={"telefone": "123", "texto": "oi"}, headers={"X-Canal-Segredo": SEGREDO})
    assert resposta.status_code == 422


def test_uma_conversa_por_telefone_sem_guardar_o_numero(client):
    primeira = diga(client, "oi")
    assert primeira["responder"] and primeira["texto"]
    segunda = diga(client, "tem camisa de linho?")
    outra = diga(client, "oi", telefone="5521912345678")
    assert segunda["conversaId"] == primeira["conversaId"] != outra["conversaId"]
    for conversa in conversas_do_canal():
        assert TELEFONE not in (conversa.chave_hash or "") and conversa.cliente_id is None
        assert conversa.marca == settings.CANAL_WHATSAPP_MARCA


def test_pecas_viram_texto_com_link(client):
    resposta = diga(client, "tem camisa?")
    assert "•" in resposta["texto"] and f"{settings.URL_FRONTEND}/produto/" in resposta["texto"]
    assert "**" not in resposta["texto"]


def test_a_mesma_mensagem_entregue_de_novo_nao_e_respondida_duas_vezes(client):
    primeira = diga(client, "tem camisa?", id_mensagem="wamid.HBgNNTUxMTk4NzY1NDMyMRUCABIYFDNBMDQ3QzZFNTQ2RkM5M0VGNkVBAA==")
    repetida = diga(client, "tem camisa?", id_mensagem="wamid.HBgNNTUxMTk4NzY1NDMyMRUCABIYFDNBMDQ3QzZFNTQ2RkM5M0VGNkVBAA==")
    assert primeira["responder"] is True and repetida["responder"] is False and repetida["texto"] == ""
    with SessionLocal() as db:
        perguntas = db.scalars(
            select(m.MensagemAssistente).where(
                m.MensagemAssistente.conversa_id == primeira["conversaId"], m.MensagemAssistente.papel == regra.USUARIO
            )
        ).all()
    assert len(perguntas) == 1


def test_pedido_de_pessoa_abre_o_chamado_na_hora_e_uma_vez_so(client):
    resposta = diga(client, "quero falar com uma pessoa", nome="Ana Souza")
    assert resposta["protocolo"] and resposta["protocolo"] in resposta["texto"]
    assert "Toque" not in resposta["texto"] and "toque" not in resposta["texto"] and "Posso" not in resposta["texto"]
    with SessionLocal() as db:
        atendimento = db.scalar(select(m.Atendimento).where(m.Atendimento.protocolo == resposta["protocolo"]))
        assert atendimento.canal == "WHATSAPP" and atendimento.contato == f"+{TELEFONE}"
        assert atendimento.contato_nome == "Ana Souza" and atendimento.cliente_id is None
        resumo = atendimento.mensagens[0].conteudo
        assert f"+{TELEFONE}" in resumo and "quero falar com uma pessoa" in resumo
        total = db.query(m.Atendimento).count()
    de_novo = diga(client, "alguém da equipe, por favor")
    assert de_novo["protocolo"] == resposta["protocolo"] and "já está com a nossa equipe" in de_novo["texto"]
    with SessionLocal() as db:
        assert db.query(m.Atendimento).count() == total


def test_mensagem_sem_texto_e_longa_demais(client):
    assert diga(client, None)["texto"] == canal_whatsapp.SO_TEXTO
    assert diga(client, "a" * 900)["texto"] == canal_whatsapp.LONGA_DEMAIS


def test_limite_de_mensagens_por_telefone(client, monkeypatch):
    monkeypatch.setitem(regra.LIMITE_POR_CONVERSA, regra.CLIENTE, (2, 600))
    diga(client, "oi")
    diga(client, "tem camisa?")
    assert diga(client, "e calça?")["texto"] == canal_whatsapp.LIMITE_DE_MENSAGENS


def test_conversa_parada_ha_mais_de_um_dia_comeca_outra(client):
    primeira = diga(client, "oi")
    with SessionLocal() as db:
        conversa = db.get(m.ConversaAssistente, primeira["conversaId"])
        conversa.atualizada_em = conversa.atualizada_em.replace(year=conversa.atualizada_em.year - 1)
        db.commit()
    assert diga(client, "oi de novo")["conversaId"] != primeira["conversaId"]


def test_o_modelo_sabe_que_esta_no_whatsapp(client):
    falso = ProvedorFalso(texto("Temos **camisas** de linho. Veja [a vitrine](/produtos)."))
    ia.definir_provedor(falso)
    resposta = diga(client, "quero uma camisa de linho")
    contexto = falso.pedidos[0]["sistema"][1]["text"]
    assert "Canal: WhatsApp" in contexto and f"{settings.URL_FRONTEND}/login" in contexto
    assert resposta["texto"].startswith("Temos *camisas* de linho.")
    assert f"a vitrine: {settings.URL_FRONTEND}/produtos" in resposta["texto"]


def test_no_site_nada_muda(client):
    falso = ProvedorFalso(texto("Temos camisas."))
    ia.definir_provedor(falso)
    conversa = client.post("/api/assistente/conversas", json={}).json()
    client.post(
        f"/api/assistente/conversas/{conversa['id']}/mensagens",
        json={"texto": "quero uma camisa"},
        headers={"X-Conversa-Chave": conversa["chave"]},
    )
    assert "Canal: WhatsApp" not in falso.pedidos[0]["sistema"][1]["text"]


def test_texto_longo_e_cortado_no_limite_do_whatsapp():
    longo = "\n".join(f"linha {i} " + "x" * 80 for i in range(100))
    cortado = canal_whatsapp.texto_para_whatsapp(longo, [])
    assert len(cortado) <= canal_whatsapp.TAMANHO_MAXIMO and cortado.endswith("…")
