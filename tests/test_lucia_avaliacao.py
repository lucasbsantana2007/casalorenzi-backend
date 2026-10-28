"""Avaliação das respostas (decisão 104): o cliente marca se a resposta ajudou (com comentário no "não ajudou") e o
painel Uso da IA mostra a qualidade: números conferidos, reescritos e trocados, falhas, ofertas da equipe e as
avaliações com os últimos comentários."""

from src.integrations import ia
from tests.ia_falsa import ProvedorFalso, ferramenta, texto
from tests.util_assistente import abrir_site, diga, entrar


def _avaliar(client, conversa, chave, mensagem_id, nota, comentario=None):
    corpo = {"nota": nota, **({"comentario": comentario} if comentario is not None else {})}
    return client.post(f"/api/assistente/conversas/{conversa}/mensagens/{mensagem_id}/avaliacao", json=corpo, headers=chave)


def _mensagens(client, conversa, chave) -> list[dict]:
    return client.get(f"/api/assistente/conversas/{conversa}", headers=chave).json()["mensagens"]


def test_cliente_avalia_a_resposta_e_pode_mudar_de_ideia(client):
    conversa, chave = abrir_site(client)
    resposta = diga(client, conversa, chave, "camisa azul")
    assert resposta["avaliavel"] is True and resposta["avaliacao"] is None
    assert _avaliar(client, conversa, chave, resposta["id"], "AJUDOU", "ótimo").status_code == 204
    ultima = _mensagens(client, conversa, chave)[-1]
    assert ultima["avaliacao"] == "AJUDOU"
    assert _avaliar(client, conversa, chave, resposta["id"], "NAO_AJUDOU", "queria ver no tamanho M").status_code == 204
    assert _mensagens(client, conversa, chave)[-1]["avaliacao"] == "NAO_AJUDOU"


def test_so_as_respostas_desta_conversa_podem_ser_avaliadas(client):
    conversa, chave = abrir_site(client)
    saudacao = _mensagens(client, conversa, chave)[0]
    assert saudacao["avaliavel"] is False
    assert _avaliar(client, conversa, chave, saudacao["id"], "AJUDOU").status_code == 404
    resposta = diga(client, conversa, chave, "camisa azul")
    outra, chave_outra = abrir_site(client)
    assert _avaliar(client, outra, chave_outra, resposta["id"], "NAO_AJUDOU").status_code == 404
    assert _avaliar(client, conversa, {}, resposta["id"], "NAO_AJUDOU").status_code == 404  # sem a chave
    assert _avaliar(client, conversa, chave, resposta["id"], "TALVEZ").status_code == 422


def test_painel_mostra_a_qualidade_da_lucia(client):
    ia.definir_provedor(
        ProvedorFalso(
            ferramenta("buscar_produtos", {"tipo_peca": "camisa", "cor": "azul"}),
            texto("Achei 2 camisas azuis."),
            texto("O frete para Manaus é R$ 19,90."),  # sem consulta: número sem fonte
            texto("O frete fica R$ 19,90."),  # errou de novo: trocada por "não consegui confirmar" (1ª falha)
            texto("Desculpe, não entendi."),  # 2ª falha seguida: oferece a equipe e zera
            texto("Não entendi, pode reformular?"),  # 1ª falha da nova contagem
        )
    )
    conversa, chave = abrir_site(client)
    certa = diga(client, conversa, chave, "camisa azul")
    trocada = diga(client, conversa, chave, "quanto é o frete pra Manaus?")
    diga(client, conversa, chave, "asdf qwer")
    diga(client, conversa, chave, "zxcv uiop")
    _avaliar(client, conversa, chave, certa["id"], "AJUDOU")
    _avaliar(client, conversa, chave, trocada["id"], "NAO_AJUDOU", "não disse o valor do frete")

    uso = client.get("/api/copiloto/uso", headers=entrar(client, "helena@casalorenzi.com.br")).json()
    q = uso["qualidade"]["CLIENTE"]
    assert q["verificacao"] == {"CONFERIDA": 3, "REESCRITA": 0, "SUBSTITUIDA": 1}
    assert q["comNumeros"] == 1  # o frete ("2 camisas" é contagem pequena, não conferida)
    assert q["falhas"] == 3 and q["ofereceuPessoa"] == 1  # trocada sem texto pronto + os dois "não entendi"
    assert q["avaliacoes"] == {"ajudou": 1, "naoAjudou": 1}
    [comentario] = q["comentarios"]
    assert comentario["comentario"] == "não disse o valor do frete" and comentario["pergunta"] == "quanto é o frete pra Manaus?"


def test_so_o_administrador_ve_o_painel(client):
    diego = entrar(client, "diego.almeida@casalorenzi.com.br")  # Operador
    assert client.get("/api/copiloto/uso", headers=diego).status_code == 403
