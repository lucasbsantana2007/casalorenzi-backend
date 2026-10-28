"""A Lúcia no WhatsApp (decisões 108 e 114): o n8n chama a API com o segredo do canal; a primeira mensagem recebe o
menu (respostas rápidas ou equipe); a equipe abre o chamado na hora e as mensagens seguintes entram nele; toda
resposta da Lúcia traz o botão da equipe; uma conversa por telefone e nada respondido duas vezes."""

from datetime import datetime

import pytest
from sqlalchemy import select

from src import models as m
from src.config import settings
from src.database.connection import SessionLocal
from src.entities import assistente as regra
from src.integrations import ia
from src.use_cases.assistente import canal_whatsapp as canal
from tests.ia_falsa import ProvedorFalso, texto

URL = "/api/canais/whatsapp/mensagens"
SEGREDO = "segredo-do-canal-de-teste"
TELEFONE = "5511987654321"


@pytest.fixture(autouse=True)
def segredo(monkeypatch):
    monkeypatch.setattr(settings, "CANAL_WHATSAPP_SEGREDO", SEGREDO)


def diga(client, mensagem=None, telefone=TELEFONE, id_mensagem=None, nome="Ana", botao=None):
    corpo = {"telefone": telefone, "texto": mensagem, "idMensagem": id_mensagem, "nome": nome, "botao": botao}
    resposta = client.post(URL, json=corpo, headers={"X-Canal-Segredo": SEGREDO})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def com_a_lucia(client, telefone=TELEFONE):
    """Abre a conversa e escolhe as respostas rápidas."""
    diga(client, "oi", telefone=telefone)
    return diga(client, botao="LUCIA", telefone=telefone)


def botoes(resposta) -> list[str]:
    mensagem = resposta["mensagem"]
    if mensagem["type"] != "interactive":
        return []
    return [b["reply"]["id"] for b in mensagem["interactive"]["action"]["buttons"]]


def chamado(protocolo) -> m.Atendimento:
    with SessionLocal() as db:
        atendimento = db.scalar(select(m.Atendimento).where(m.Atendimento.protocolo == protocolo))
        assert atendimento.mensagens is not None  # carrega antes de fechar a sessão
        return atendimento


# ---------- Segurança da rota ----------


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


# ---------- Menu ----------


def test_primeira_mensagem_recebe_o_menu_com_dois_botoes(client):
    resposta = diga(client, "oi", nome="Ana Souza 🌸")
    assert resposta["texto"].startswith(f"{canal.cumprimento()}, Ana! Aqui é a Lúcia")
    assert canal.OPCOES_DO_MENU in resposta["texto"] and botoes(resposta) == ["LUCIA", "EQUIPE"]
    assert resposta["mensagem"]["to"] == TELEFONE and resposta["mensagem"]["messaging_product"] == "whatsapp"
    titulos = [b["reply"]["title"] for b in resposta["mensagem"]["interactive"]["action"]["buttons"]]
    assert all(len(t) <= 20 for t in titulos)  # limite da Meta para o título do botão


def test_pergunta_feita_antes_da_escolha_e_respondida_depois(client):
    menu = diga(client, "tem camisa?")
    assert canal.OPCOES_DO_MENU in menu["texto"]
    resposta = diga(client, botao="LUCIA")
    assert "•" in resposta["texto"] and f"{settings.URL_FRONTEND}/produto/" in resposta["texto"]
    assert "EQUIPE" in botoes(resposta) or canal.DICA_DA_EQUIPE in resposta["texto"]


def test_responder_1_ou_2_vale_como_botao(client):
    diga(client, "oi")
    assert diga(client, "1")["texto"] == canal.LUCIA_PRONTA
    outro = "5521912345678"
    diga(client, "oi", telefone=outro)
    assert diga(client, "2", telefone=outro)["protocolo"]


def test_resposta_que_nao_e_opcao_repete_o_menu(client):
    diga(client, "oi")
    lembrete = diga(client, "hmm")
    assert lembrete["texto"] == canal.LEMBRETE_DO_MENU and botoes(lembrete) == ["LUCIA", "EQUIPE"]


def test_menu_pode_ser_pedido_de_novo(client):
    com_a_lucia(client)
    assert canal.OPCOES_DO_MENU in diga(client, "menu")["texto"]


# ---------- Equipe ----------


def test_escolher_a_equipe_abre_o_chamado_e_as_mensagens_seguintes_entram_nele(client):
    diga(client, "minha encomenda não chegou")
    resposta = diga(client, botao="EQUIPE", nome="Ana Souza")
    protocolo = resposta["protocolo"]
    assert protocolo and protocolo in resposta["texto"] and botoes(resposta) == ["LUCIA"]
    atendimento = chamado(protocolo)
    assert atendimento.canal == "WHATSAPP" and atendimento.contato == f"+{TELEFONE}" and atendimento.contato_nome == "Ana Souza"
    assert "minha encomenda não chegou" in atendimento.mensagens[0].conteudo

    seguinte = diga(client, "é o pedido CL-105093")
    assert seguinte["protocolo"] == protocolo and protocolo in seguinte["texto"]
    atendimento = chamado(protocolo)
    assert atendimento.mensagens[-1].conteudo == "é o pedido CL-105093" and atendimento.mensagens[-1].autor_tipo == "CLIENTE"
    with SessionLocal() as db:
        assert db.query(m.Atendimento).filter(m.Atendimento.canal == "WHATSAPP").count() == 1


def test_da_para_voltar_para_a_lucia_depois_de_chamar_a_equipe(client):
    diga(client, "oi")
    diga(client, botao="EQUIPE")
    assert diga(client, botao="LUCIA")["texto"] == canal.LUCIA_PRONTA
    assert "•" in diga(client, "tem camisa?")["texto"]


def test_equipe_a_qualquer_momento_com_a_lucia(client):
    com_a_lucia(client)
    resposta = diga(client, "2")
    assert resposta["protocolo"] and "Passei a sua conversa" in resposta["texto"]


def test_pedido_de_pessoa_no_meio_da_conversa_abre_o_chamado(client):
    com_a_lucia(client)
    resposta = diga(client, "quero falar com uma pessoa")
    assert resposta["protocolo"] and resposta["protocolo"] in resposta["texto"]
    assert "Toque" not in resposta["texto"] and "toque" not in resposta["texto"] and "Posso" not in resposta["texto"]
    de_novo = diga(client, botao="EQUIPE")
    assert de_novo["protocolo"] == resposta["protocolo"]
    with SessionLocal() as db:
        assert db.query(m.Atendimento).filter(m.Atendimento.canal == "WHATSAPP").count() == 1


def test_chamado_encerrado_volta_ao_menu(client):
    diga(client, "oi")
    protocolo = diga(client, botao="EQUIPE")["protocolo"]
    with SessionLocal() as db:
        db.query(m.Atendimento).filter(m.Atendimento.protocolo == protocolo).update({"status": "CONCLUIDO"})
        db.commit()
    assert canal.OPCOES_DO_MENU in diga(client, "oi de novo")["texto"]


# ---------- Respostas da Lúcia ----------


def test_toda_resposta_da_lucia_traz_a_equipe(client):
    com_a_lucia(client)
    resposta = diga(client, "qual o horário da loja de Curitiba?")
    assert "EQUIPE" in botoes(resposta) or canal.DICA_DA_EQUIPE in resposta["texto"]


def test_uma_conversa_por_telefone_sem_guardar_o_numero(client):
    primeira = com_a_lucia(client)
    segunda = diga(client, "tem camisa de linho?")
    outra = diga(client, "oi", telefone="5521912345678")
    assert segunda["conversaId"] == primeira["conversaId"] != outra["conversaId"]
    with SessionLocal() as db:
        for conversa in db.scalars(select(m.ConversaAssistente).where(m.ConversaAssistente.tipo == regra.CLIENTE)):
            assert TELEFONE not in (conversa.chave_hash or "") and TELEFONE not in str(conversa.contexto)
            assert conversa.cliente_id is None and conversa.marca == settings.CANAL_WHATSAPP_MARCA


def test_a_mesma_mensagem_entregue_de_novo_nao_e_respondida_duas_vezes(client):
    wamid = "wamid.HBgNNTUxMTk4NzY1NDMyMRUCABIYFDNBMDQ3QzZFNTQ2RkM5M0VGNkVBAA=="
    assert diga(client, "oi", id_mensagem=wamid)["responder"] is True
    repetida = diga(client, "oi", id_mensagem=wamid)
    assert repetida["responder"] is False and repetida["mensagem"] is None
    com_a_lucia(client, telefone="5521912345678")
    outro = "wamid.outra-mensagem"
    assert diga(client, "tem camisa?", telefone="5521912345678", id_mensagem=outro)["responder"] is True
    assert diga(client, "tem camisa?", telefone="5521912345678", id_mensagem=outro)["responder"] is False


def test_mensagem_sem_texto_e_longa_demais(client):
    assert diga(client, None)["texto"] == canal.SO_TEXTO
    com_a_lucia(client)
    assert diga(client, "a" * 900)["texto"] == canal.LONGA_DEMAIS


def test_limite_de_mensagens_por_telefone(client, monkeypatch):
    monkeypatch.setitem(regra.LIMITE_POR_CONVERSA, regra.CLIENTE, (2, 600))
    diga(client, "oi")
    diga(client, "1")
    assert diga(client, "e calça?")["texto"] == canal.LIMITE_DE_MENSAGENS


def test_conversa_parada_ha_mais_de_um_dia_comeca_outra(client):
    primeira = com_a_lucia(client)
    with SessionLocal() as db:
        conversa = db.get(m.ConversaAssistente, primeira["conversaId"])
        conversa.atualizada_em = conversa.atualizada_em.replace(year=conversa.atualizada_em.year - 1)
        db.commit()
    nova = diga(client, "oi de novo")
    assert nova["conversaId"] != primeira["conversaId"] and canal.OPCOES_DO_MENU in nova["texto"]


def test_o_modelo_sabe_que_esta_no_whatsapp(client):
    falso = ProvedorFalso(texto("Temos **camisas** de linho. Veja [a vitrine](/produtos)."))
    ia.definir_provedor(falso)
    diga(client, "quero uma camisa de linho")
    resposta = diga(client, botao="LUCIA")
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


def test_cumprimento_pelo_horario_e_sem_nome():
    manha = datetime(2026, 10, 30, 9, 0, tzinfo=settings.FUSO)
    tarde = datetime(2026, 10, 30, 15, 0, tzinfo=settings.FUSO)
    noite = datetime(2026, 10, 30, 21, 0, tzinfo=settings.FUSO)
    assert [canal.cumprimento(h) for h in (manha, tarde, noite)] == ["Bom dia", "Boa tarde", "Boa noite"]
    assert canal.texto_do_menu("Ana", manha).startswith("Bom dia, Ana! Aqui é a Lúcia")
    assert canal.texto_do_menu(None, noite).startswith("Boa noite! Aqui é a Lúcia")
    assert canal.texto_do_menu("123", noite).startswith("Boa noite! Aqui é a Lúcia")


# ---------- Formato da Meta ----------


def test_texto_longo_vira_mensagem_de_texto_com_a_dica_da_equipe():
    longo = "x" * 1500
    mensagem = canal.mensagem_da_meta(TELEFONE, longo, [canal.BOTAO_EQUIPE])
    assert mensagem["type"] == "text" and mensagem["text"]["body"].endswith(canal.DICA_DA_EQUIPE)


def test_texto_longo_e_cortado_no_limite_do_whatsapp():
    longo = "\n".join(f"linha {i} " + "x" * 80 for i in range(100))
    cortado = canal.texto_para_whatsapp(longo, [])
    assert len(cortado) <= canal.TAMANHO_MAXIMO and cortado.endswith("…")
