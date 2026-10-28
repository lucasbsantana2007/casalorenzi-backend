"""Duas falhas seguidas → pessoa (decisão 99): quando a Lúcia falha duas vezes seguidas (não entende, não consegue
responder, o cliente diz que não serviu ou repete a pergunta), ela mesma oferece a equipe, com o resumo."""

from src.integrations import ia
from src.use_cases.assistente import escalonamento
from tests.ia_falsa import ProvedorFalso, texto
from tests.util_assistente import abrir_site, blocos, diga, entrar, sql


def _memoria(conversa: str) -> dict:
    return sql("SELECT contexto FROM conversas_assistente WHERE id = :c", c=conversa)[0][0]


def _auditoria(resposta: dict) -> dict | None:
    return sql("SELECT auditoria FROM mensagens_assistente WHERE id = :m", m=resposta["id"])[0][0]


def test_duas_vezes_sem_entender_oferece_a_equipe(client):
    conversa, chave = abrir_site(client)
    primeira = diga(client, conversa, chave, "asdf qwer zxcv")
    assert blocos(primeira, "acao_atendimento") == [] and _memoria(conversa)["falhasSeguidas"] == 1
    segunda = diga(client, conversa, chave, "hjkl uiop vbnm")
    assert segunda["texto"].startswith(escalonamento.OFERTA)
    assert "Não entendi" not in segunda["texto"]  # a resposta que falhou não volta: sai só a oferta
    [botao] = blocos(segunda, "acao_atendimento")
    assert "duas tentativas" in botao["motivo"] and "hjkl uiop vbnm" in botao["motivo"]
    assert "falhasSeguidas" not in _memoria(conversa)  # a contagem recomeça
    assert _auditoria(segunda) == {"falhou": True, "ofereceuPessoa": True}


def test_um_acerto_no_meio_zera_a_contagem(client):
    conversa, chave = abrir_site(client)
    diga(client, conversa, chave, "asdf qwer zxcv")
    diga(client, conversa, chave, "camisa azul")
    assert "falhasSeguidas" not in _memoria(conversa)
    terceira = diga(client, conversa, chave, "hjkl uiop vbnm")
    assert blocos(terceira, "acao_atendimento") == [] and _memoria(conversa)["falhasSeguidas"] == 1


def test_a_mesma_pergunta_de_novo_conta_como_falha(client):
    conversa, chave = abrir_site(client)
    diga(client, conversa, chave, "quanto é o frete para Manaus?")
    segunda = diga(client, conversa, chave, "quanto é o frete pra Manaus??")
    assert blocos(segunda, "acao_atendimento") == []
    assert _auditoria(segunda) == {"sinalDoCliente": "REPETICAO"}
    terceira = diga(client, conversa, chave, "quanto e o frete pra manaus")
    assert blocos(terceira, "acao_atendimento")
    # A resposta continua (ela respondeu a política de frete) e a oferta vem depois
    assert not terceira["texto"].startswith(escalonamento.OFERTA) and escalonamento.OFERTA in terceira["texto"]


def test_outra_pergunta_parecida_nao_e_repeticao():
    assert escalonamento.repetiu("quanto é o frete pra Manaus?", "qual o frete para manaus")
    assert not escalonamento.repetiu("tem camisa azul M?", "tem camisa azul G?")
    assert not escalonamento.repetiu("sim", "sim")
    assert not escalonamento.repetiu("camisa azul", "calça preta")


def test_modelo_que_nao_entende_e_cliente_frustrado(client):
    ia.definir_provedor(
        ProvedorFalso(
            texto("Encontrei duas camisas azuis."),
            texto("Desculpe, não entendi. Pode reformular a pergunta?"),
        )
    )
    conversa, chave = abrir_site(client)
    diga(client, conversa, chave, "camisa azul")
    # "Não foi isso" (o cliente) + "não entendi" (a Lúcia) na mesma mensagem: duas falhas
    resposta = diga(client, conversa, chave, "não foi isso que eu perguntei")
    assert blocos(resposta, "acao_atendimento")
    assert resposta["texto"].startswith("Desculpe, não entendi.") and escalonamento.OFERTA in resposta["texto"]
    auditoria = _auditoria(resposta)
    assert auditoria["sinalDoCliente"] == "FRUSTRACAO" and auditoria["ofereceuPessoa"] is True
    assert auditoria["verificacao"] == "CONFERIDA"


def test_nao_oferece_de_novo_quando_a_resposta_ja_tem_a_equipe(client):
    conversa, chave = abrir_site(client)
    diga(client, conversa, chave, "asdf qwer zxcv")
    resposta = diga(client, conversa, chave, "quero falar com uma pessoa")
    assert len(blocos(resposta, "acao_atendimento")) == 1
    assert escalonamento.OFERTA not in resposta["texto"] and "falhasSeguidas" not in _memoria(conversa)


def test_conversa_ja_encaminhada_lembra_o_protocolo(client):
    token = entrar(client, "mariana.costa@gmail.com")
    conversa, chave = abrir_site(client, token=token)
    r = client.post(f"/api/assistente/conversas/{conversa}/atendimento", json={"motivo": "Troca"}, headers=chave)
    assert r.status_code in (200, 201), r.text
    protocolo = r.json()["protocolo"]
    chamados = sql("SELECT count(*) FROM atendimentos WHERE cliente_id = 101")[0][0]
    diga(client, conversa, chave, "asdf qwer zxcv")
    resposta = diga(client, conversa, chave, "hjkl uiop vbnm")
    assert protocolo in resposta["texto"] and blocos(resposta, "acao_atendimento") == []
    assert sql("SELECT count(*) FROM atendimentos WHERE cliente_id = 101")[0][0] == chamados  # nenhum chamado a mais
