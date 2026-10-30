"""A Lúcia no WhatsApp (decisões 108, 116 e 117): o n8n chama a API com o segredo do canal; a primeira mensagem recebe o
menu (respostas rápidas ou equipe); a equipe abre o chamado na hora, com a conversa inteira, e as mensagens seguintes
entram nele sem resposta automática; a Lúcia responde sem botões e oferece a equipe só depois de falhar (decisão 121);
uma conversa por telefone e nada respondido duas vezes."""

from datetime import datetime, timedelta

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
    assert botoes(resposta) == [] and canal.DICA_DA_EQUIPE not in resposta["texto"]


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
    assert protocolo and protocolo in resposta["texto"] and botoes(resposta) == []
    atendimento = chamado(protocolo)
    assert atendimento.canal == "WHATSAPP" and atendimento.contato == f"+{TELEFONE}" and atendimento.contato_nome == "Ana Souza"
    assert "minha encomenda não chegou" in atendimento.mensagens[0].conteudo

    # As mensagens seguintes só entram no chamado: sem "Recebi!" a cada uma (decisão 121)
    seguinte = diga(client, "é o pedido CL-105093")
    assert seguinte["responder"] is False and seguinte["mensagem"] is None and seguinte["protocolo"] == protocolo
    assert diga(client, "2")["responder"] is False  # no meio do atendimento, "2" é mensagem para a equipe
    atendimento = chamado(protocolo)
    assert [msg.conteudo for msg in atendimento.mensagens[-2:]] == ["é o pedido CL-105093", "2"]
    assert atendimento.mensagens[-1].autor_tipo == "CLIENTE"
    with SessionLocal() as db:
        assert db.query(m.Atendimento).filter(m.Atendimento.canal == "WHATSAPP").count() == 1


def test_da_para_voltar_para_a_lucia_depois_de_chamar_a_equipe(client):
    diga(client, "oi")
    diga(client, botao="EQUIPE")
    assert diga(client, botao="LUCIA")["texto"] == canal.LUCIA_PRONTA
    assert "•" in diga(client, "tem camisa?")["texto"]


def test_equipe_a_qualquer_momento_com_a_lucia(client):
    com_a_lucia(client)
    resposta = diga(client, "atendente")
    assert resposta["protocolo"] and "Passei a sua conversa" in resposta["texto"]


def test_com_a_lucia_1_e_2_nao_sao_opcoes_do_menu(client):
    com_a_lucia(client)
    resposta = diga(client, "2")
    assert resposta["protocolo"] is None and resposta["texto"] != canal.LUCIA_PRONTA


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


def test_resposta_da_lucia_sai_sem_botoes(client):
    assert botoes(com_a_lucia(client)) == []
    resposta = diga(client, "qual o horário da loja de Curitiba?")
    assert botoes(resposta) == [] and resposta["protocolo"] is None


def test_duas_falhas_oferecem_a_equipe_sem_abrir_o_chamado(client):
    com_a_lucia(client)
    assert botoes(diga(client, "asdf qwer zxcv")) == []
    oferta = diga(client, "hjkl uiop vbnm")
    assert botoes(oferta) == ["EQUIPE"] and canal.OFERTA_DA_EQUIPE in oferta["texto"]
    assert oferta["protocolo"] is None and "Toque" not in oferta["texto"] and "Posso" not in oferta["texto"]
    with SessionLocal() as db:
        assert db.query(m.Atendimento).filter(m.Atendimento.canal == "WHATSAPP").count() == 0
    aceita = diga(client, botao="EQUIPE")
    assert aceita["protocolo"] and "Passei a sua conversa" in aceita["texto"]


def test_chamado_leva_a_conversa_inteira_com_a_lucia(client):
    com_a_lucia(client)
    perguntas = [f"tem camisa tamanho {t}?" for t in ("PP", "P", "M", "G", "GG", "XG")]
    for pergunta in perguntas:
        diga(client, pergunta)
    protocolo = diga(client, "atendente")["protocolo"]
    resumo = chamado(protocolo).mensagens[0].conteudo
    assert "Conversa com a assistente:" in resumo
    assert all(f"- Cliente: {pergunta}" in resumo for pergunta in perguntas)  # mais que as 8 últimas mensagens


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


def test_peca_ja_escrita_pelo_modelo_nao_se_repete():
    # Decisão 121: o modelo citou as duas camisas com o link; a lista não repete
    bloco = {
        "tipo": "produtos",
        "itens": [
            {"nome": "Camisa de Linho Toscana", "precoFormatado": "R$ 489,00", "link": "/produto/1"},
            {"nome": "Camisa de Linho Positano", "precoFormatado": "R$ 369,00", "link": "/produto/2"},
        ],
    }
    citadas = "Encontrei a **Camisa de Linho Toscana** e a Camisa de Linho Positano, ambas no M."
    assert canal.texto_para_whatsapp(citadas, [bloco]).count("Toscana") == 1
    assert "•" not in canal.texto_para_whatsapp(citadas, [bloco])
    so_uma = canal.texto_para_whatsapp(f"Veja: {settings.URL_FRONTEND}/produto/1", [bloco])
    assert "Toscana" not in so_uma and "• *Camisa de Linho Positano*" in so_uma
    resumo = canal.texto_para_whatsapp("Encontrei duas camisas de linho azul no M:", [bloco])
    assert resumo.count("•") == 2


def test_texto_longo_e_cortado_no_limite_do_whatsapp():
    longo = "\n".join(f"linha {i} " + "x" * 80 for i in range(100))
    cortado = canal.texto_para_whatsapp(longo, [])
    assert len(cortado) <= canal.TAMANHO_MAXIMO and cortado.endswith("…")


# ---------- Atendimento humano num lugar só (decisão 117) ----------


@pytest.fixture
def entregas(monkeypatch):
    """O que a API mandou para o webhook de envio do n8n (sem rede)."""
    enviadas = []

    class Resposta:
        status_code = 200

    def post(url, json, headers, timeout):
        enviadas.append({"url": url, "corpo": json, "segredo": headers.get("X-Canal-Segredo")})
        return Resposta()

    monkeypatch.setattr(settings, "N8N_ENVIO_URL", "https://n8n.exemplo/webhook/envio")
    monkeypatch.setattr(canal.httpx, "post", post)
    return enviadas


def _atendimento_id(protocolo) -> int:
    with SessionLocal() as db:
        return db.scalar(select(m.Atendimento.id).where(m.Atendimento.protocolo == protocolo))


def _equipe_responde(client, admin, protocolo, texto="Oi, Ana! Vou verificar o seu pedido."):
    resposta = client.post(f"/api/atendimentos/{_atendimento_id(protocolo)}/mensagens", json={"conteudo": texto}, headers=admin)
    assert resposta.status_code == 201, resposta.text


def _envelhecer(protocolo, autor_tipo, horas):
    """Recua no tempo as mensagens de um autor do chamado (e a conversa do WhatsApp ligada a ele)."""
    with SessionLocal() as db:
        atendimento = db.scalar(select(m.Atendimento).where(m.Atendimento.protocolo == protocolo))
        for mensagem in atendimento.mensagens:
            if mensagem.autor_tipo == autor_tipo:
                mensagem.enviado_em = mensagem.enviado_em - timedelta(hours=horas)
        for conversa in db.scalars(select(m.ConversaAssistente).where(m.ConversaAssistente.atendimento_id == atendimento.id)):
            conversa.atualizada_em = conversa.atualizada_em - timedelta(hours=horas)
        db.commit()


def test_cliente_que_vem_do_site_cai_no_mesmo_chamado(client):
    from src.use_cases import atendimentos

    with SessionLocal() as db:
        tipo = db.scalar(select(m.TipoSolicitacao).where(m.TipoSolicitacao.titulo == "Dúvida sobre produto"))
        aberto = atendimentos.abrir_pelo_whatsapp(
            db, None, marca="LORENZI", tipo_solicitacao_id=tipo.id, descricao="Resumo do site: cliente quer saber do cinto."
        )
        db.commit()
        protocolo = aberto.protocolo
    resposta = diga(client, f"Olá! Vim do assistente do site. Protocolo {protocolo}.", nome="Ana Souza")
    assert resposta["protocolo"] == protocolo and protocolo in resposta["texto"] and "Ana" in resposta["texto"]
    atendimento = chamado(protocolo)
    assert atendimento.contato == f"+{TELEFONE}" and atendimento.contato_nome == "Ana Souza"
    assert atendimento.mensagens[-1].conteudo.startswith("Olá! Vim do assistente do site")
    assert diga(client, "é sobre o cinto preto")["protocolo"] == protocolo
    with SessionLocal() as db:
        assert db.query(m.Atendimento).filter(m.Atendimento.canal == "WHATSAPP").count() == 1


def test_resposta_da_equipe_no_painel_vai_para_o_whatsapp(client, admin, entregas):
    diga(client, "oi")
    protocolo = diga(client, botao="EQUIPE")["protocolo"]
    _equipe_responde(client, admin, protocolo)
    assert len(entregas) == 1
    mensagem = entregas[0]["corpo"]["mensagem"]
    assert entregas[0]["segredo"] == SEGREDO and mensagem["to"] == TELEFONE
    # Mensagem comum, sem assinatura, protocolo nem botão (decisão 121)
    assert mensagem["type"] == "text" and mensagem["text"]["body"] == "Oi, Ana! Vou verificar o seu pedido."


def test_chamado_do_site_nao_vai_para_o_whatsapp(client, admin, entregas):
    with SessionLocal() as db:
        site = db.scalar(select(m.Atendimento).where(m.Atendimento.canal == "SITE", m.Atendimento.status != "CONCLUIDO").limit(1))
    resposta = client.post(f"/api/atendimentos/{site.id}/mensagens", json={"conteudo": "Oi!"}, headers=admin)
    assert resposta.status_code == 201 and entregas == []


def test_fora_da_janela_de_24_horas_nao_envia_e_avisa_no_chamado(client, admin, entregas):
    diga(client, "oi")
    protocolo = diga(client, botao="EQUIPE")["protocolo"]
    _envelhecer(protocolo, "CLIENTE", 25)
    _equipe_responde(client, admin, protocolo)
    assert entregas == []
    assert "24 h" in chamado(protocolo).mensagens[-1].conteudo and chamado(protocolo).mensagens[-1].autor_tipo == "SISTEMA"


def test_ciclo_fecha_com_4_horas_sem_resposta_do_cliente(client, admin, entregas):
    diga(client, "oi")
    protocolo = diga(client, botao="EQUIPE")["protocolo"]
    _equipe_responde(client, admin, protocolo)
    _envelhecer(protocolo, "CLIENTE", 6)  # a ordem se mantém: o cliente escreveu antes da equipe
    _envelhecer(protocolo, "ATENDENTE", 5)
    with SessionLocal() as db:
        # Com a checagem acompanhando (decisão 125), o fechamento antigo não age: ela fecha, com um aviso só
        assert canal.encerrar_ciclos(db) == 0
        # Chamado sem checagem (de antes da decisão 125): o fechamento antigo fecha
        for conversa in db.scalars(select(m.ConversaAssistente).where(m.ConversaAssistente.atendimento_id.is_not(None))):
            conversa.contexto = {k: v for k, v in conversa.contexto.items() if k != "whatsappRespondidoEm"}
        db.commit()
        assert canal.encerrar_ciclos(db) == 1
    atendimento = chamado(protocolo)
    assert atendimento.status == "CONCLUIDO" and "4 horas" in atendimento.mensagens[-1].conteudo
    aviso = entregas[-1]["corpo"]["mensagem"]
    assert aviso["type"] == "text" and "encerramos este atendimento" in aviso["text"]["body"]
    assert canal.OPCOES_DO_MENU in diga(client, "oi de novo")["texto"]


def test_ciclo_nao_fecha_se_a_equipe_deve_a_resposta(client, entregas):
    diga(client, "oi")
    protocolo = diga(client, botao="EQUIPE")["protocolo"]
    _envelhecer(protocolo, "CLIENTE", 5)
    with SessionLocal() as db:
        assert canal.encerrar_ciclos(db) == 0
    assert chamado(protocolo).status != "CONCLUIDO"


def test_cliente_que_volta_depois_de_4_horas_recomeca_pelo_menu(client, admin, entregas):
    diga(client, "oi")
    protocolo = diga(client, botao="EQUIPE")["protocolo"]
    _equipe_responde(client, admin, protocolo)
    _envelhecer(protocolo, "CLIENTE", 6)  # a ordem se mantém: o cliente escreveu antes da equipe
    _envelhecer(protocolo, "ATENDENTE", 5)
    resposta = diga(client, "voltei")
    assert canal.OPCOES_DO_MENU in resposta["texto"] and resposta["protocolo"] is None
    assert chamado(protocolo).status == "CONCLUIDO"


def test_resposta_da_equipe_renova_o_ciclo(client, admin, entregas):
    diga(client, "oi")
    protocolo = diga(client, botao="EQUIPE")["protocolo"]
    _envelhecer(protocolo, "CLIENTE", 5)  # a conversa ficou 5 h parada esperando a equipe
    _equipe_responde(client, admin, protocolo)
    seguinte = diga(client, "obrigada, aguardo")
    assert seguinte["protocolo"] == protocolo and seguinte["responder"] is False
    assert chamado(protocolo).mensagens[-1].conteudo == "obrigada, aguardo"


# ---------- Depois da resposta: a checagem e o fim (decisão 125) ----------


def _recuar_espera(conversa_id, minutos):
    """Recua no tempo a resposta (da Lúcia ou da equipe) e a checagem, como se o cliente estivesse calado."""
    with SessionLocal() as db:
        conversa = db.get(m.ConversaAssistente, conversa_id)
        contexto = dict(conversa.contexto)
        for chave in ("whatsappRespondidoEm", "whatsappChecagemEm"):
            if contexto.get(chave):
                contexto[chave] = (datetime.fromisoformat(contexto[chave]) - timedelta(minutes=minutos)).isoformat()
        conversa.contexto = contexto
        db.commit()


def _rotina(client):
    resposta = client.post(f"{URL.rsplit('/', 1)[0]}/rotina", headers={"X-Canal-Segredo": SEGREDO})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def test_quinze_minutos_depois_da_lucia_vem_a_checagem(client, entregas):
    com_a_lucia(client)
    resposta = diga(client, "qual o horário da loja de Curitiba?")
    assert _rotina(client) == {"checagens": 0, "finalizadas": 0}  # ainda não deu 15 min
    _recuar_espera(resposta["conversaId"], 16)
    assert _rotina(client)["checagens"] == 1
    checagem = entregas[-1]["corpo"]["mensagem"]
    assert checagem["to"] == TELEFONE and checagem["interactive"]["body"]["text"] == canal.CHECAGEM
    assert [b["reply"]["id"] for b in checagem["interactive"]["action"]["buttons"]] == ["FINALIZAR"]
    assert _rotina(client)["checagens"] == 0  # uma vez só


def test_cliente_que_responde_nao_recebe_a_checagem(client, entregas):
    com_a_lucia(client)
    resposta = diga(client, "tem camisa?")
    _recuar_espera(resposta["conversaId"], 10)
    diga(client, "obrigada")  # cortesia: a Lúcia responde e a espera recomeça do zero
    _recuar_espera(resposta["conversaId"], 10)
    assert _rotina(client)["checagens"] == 0 and entregas == []


def test_sem_resposta_por_mais_3h45_finaliza_e_avisa(client, entregas):
    com_a_lucia(client)
    resposta = diga(client, "tem camisa?")
    _recuar_espera(resposta["conversaId"], 16)
    _rotina(client)
    _recuar_espera(resposta["conversaId"], 3 * 60 + 46)
    assert _rotina(client)["finalizadas"] == 1
    assert entregas[-1]["corpo"]["mensagem"]["text"]["body"] == canal.SEM_RESPOSTA
    with SessionLocal() as db:
        assert db.get(m.ConversaAssistente, resposta["conversaId"]).status == regra.ENCERRADA
    nova = diga(client, "oi")
    assert nova["conversaId"] != resposta["conversaId"] and canal.OPCOES_DO_MENU in nova["texto"]


def test_depois_da_equipe_tambem_e_o_chamado_fecha(client, admin, entregas):
    diga(client, "oi")
    aberto = diga(client, botao="EQUIPE")
    _equipe_responde(client, admin, aberto["protocolo"])
    _recuar_espera(aberto["conversaId"], 16)
    assert _rotina(client)["checagens"] == 1
    _recuar_espera(aberto["conversaId"], 3 * 60 + 46)
    assert _rotina(client)["finalizadas"] == 1
    assert chamado(aberto["protocolo"]).status == "CONCLUIDO"
    assert aberto["protocolo"] in entregas[-1]["corpo"]["mensagem"]["text"]["body"]


def test_botao_finalizar_encerra_na_hora(client, admin, entregas):
    diga(client, "oi")
    aberto = diga(client, botao="EQUIPE")
    _equipe_responde(client, admin, aberto["protocolo"])
    fim = diga(client, botao="FINALIZAR")
    assert fim["texto"] == canal.FINALIZADO and botoes(fim) == []
    assert chamado(aberto["protocolo"]).status == "CONCLUIDO"
    assert "Finalizado pelo cliente" in chamado(aberto["protocolo"]).mensagens[-1].conteudo
    assert _rotina(client) == {"checagens": 0, "finalizadas": 0}


def test_rotina_exige_o_segredo(client):
    assert client.post(f"{URL.rsplit('/', 1)[0]}/rotina").status_code == 401


# ---------- Protocolo do site e chamado concluído ----------


def _chamado_do_site(descricao="Resumo do site: cliente quer falar com humano.") -> str:
    from src.use_cases import atendimentos

    with SessionLocal() as db:
        tipo = db.scalar(select(m.TipoSolicitacao).where(m.TipoSolicitacao.titulo == "Dúvida sobre produto"))
        aberto = atendimentos.abrir_pelo_whatsapp(db, None, marca="LORENZI", tipo_solicitacao_id=tipo.id, descricao=descricao)
        db.commit()
        return aberto.protocolo


def _concluir(protocolo):
    with SessionLocal() as db:
        db.query(m.Atendimento).filter(m.Atendimento.protocolo == protocolo).update({"status": "CONCLUIDO"})
        db.commit()


def test_protocolo_do_site_vale_mesmo_com_outro_chamado_aberto(client):
    diga(client, "oi")
    antigo = diga(client, botao="EQUIPE")["protocolo"]
    novo = _chamado_do_site()
    resposta = diga(client, f"Olá! Vim do assistente do site. Protocolo {novo}.")
    assert resposta["protocolo"] == novo and novo in resposta["texto"]
    assert diga(client, "é sobre a troca")["protocolo"] == novo
    assert chamado(novo).mensagens[-1].conteudo == "é sobre a troca"
    assert chamado(antigo).mensagens[-1].conteudo != "é sobre a troca"


def test_protocolo_do_proprio_chamado_so_entra_nele(client):
    diga(client, "oi")
    protocolo = diga(client, botao="EQUIPE")["protocolo"]
    resposta = diga(client, f"Meu protocolo é {protocolo}")
    assert resposta["responder"] is False and chamado(protocolo).mensagens[-1].conteudo == f"Meu protocolo é {protocolo}"


def test_depois_do_chamado_concluido_pedir_a_equipe_abre_outro(client):
    diga(client, "oi")
    antigo = diga(client, botao="EQUIPE")["protocolo"]
    _concluir(antigo)
    menu = diga(client, "quero falar com humano")
    assert canal.OPCOES_DO_MENU in menu["texto"] and menu["protocolo"] is None
    novo = diga(client, botao="EQUIPE")
    assert novo["protocolo"] and novo["protocolo"] != antigo and "Passei a sua conversa" in novo["texto"]


def test_equipe_atrasada_avisa_uma_vez_por_espera(client, admin, entregas):
    diga(client, "oi")
    protocolo = diga(client, botao="EQUIPE")["protocolo"]
    assert diga(client, "alguém aí?")["responder"] is False  # ainda no prazo: silêncio
    _envelhecer(protocolo, "CLIENTE", 1)  # o cliente espera há 1 h
    aviso = diga(client, "oi?")
    assert aviso["texto"] == canal.AVISO_DE_ESPERA and chamado(protocolo).mensagens[-1].conteudo == "oi?"
    assert diga(client, "???")["responder"] is False  # na mesma espera, um aviso só
    _equipe_responde(client, admin, protocolo)  # a equipe respondeu: a espera recomeça
    assert diga(client, "obrigada")["responder"] is False


def test_todo_botao_cabe_no_limite_da_meta():
    # A Meta recusa em silêncio botão com título acima de 20 caracteres
    for botao in (canal.BOTAO_LUCIA, canal.BOTAO_EQUIPE, canal.BOTAO_FINALIZAR):
        assert len(botao["title"]) <= 20, botao


def test_um_aviso_de_encerramento_so(client, admin, entregas):
    diga(client, "oi")
    aberto = diga(client, botao="EQUIPE")
    _equipe_responde(client, admin, aberto["protocolo"])
    _envelhecer(aberto["protocolo"], "CLIENTE", 6)  # a ordem se mantém: o cliente escreveu antes da equipe
    _envelhecer(aberto["protocolo"], "ATENDENTE", 5)  # o fechamento antigo também já valeria
    _recuar_espera(aberto["conversaId"], 16)
    _rotina(client)
    _recuar_espera(aberto["conversaId"], 3 * 60 + 46)
    _rotina(client)
    _rotina(client)
    avisos = [
        e for e in entregas if e["corpo"]["mensagem"]["type"] == "text" and "encerramos" in e["corpo"]["mensagem"]["text"]["body"]
    ]
    assert len(avisos) == 1 and chamado(aberto["protocolo"]).status == "CONCLUIDO"
