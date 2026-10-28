"""Saudação personalizada (decisão 100): para o cliente logado, a Lúcia começa do ponto dele, com os pontos Lupe+
que vencem nos próximos 30 dias, o pedido em andamento e o tamanho que ele costuma levar. Só lê: abrir o chat não
lança vencimento de pontos."""

from datetime import timedelta

from src.database.connection import SessionLocal
from src.integrations import ia
from src.use_cases import fidelidade
from src.use_cases.assistente.formatacao import data
from src.use_cases.assistente.prompts import BOAS_VINDAS
from src.utils.datas import agora
from tests.ia_falsa import ProvedorFalso, texto
from tests.util_assistente import diga, entrar, sql

MARIANA = 101


def _credito(quantidade: int, dias_atras: int) -> str:
    """Lança o crédito e devolve a data em que ele vence (dd/mm/aaaa)."""
    quando = agora() - timedelta(days=dias_atras)
    with SessionLocal() as db:
        fidelidade.travar(db, MARIANA)
        fidelidade.lancar(db, MARIANA, "CREDITO", quantidade, quando, obs="teste")
        db.commit()
    return data(fidelidade.vence_em(quando))


def _abrir(client, token=None) -> dict:
    r = client.post("/api/assistente/conversas", json={}, headers=token or {})
    assert r.status_code == 201, r.text
    return r.json()


def _sugestoes(conversa: dict) -> list[str]:
    return conversa["mensagens"][0]["blocos"][0]["itens"]


def test_cliente_logado_e_lembrado_dos_pontos_que_vao_vencer(client):
    vence = _credito(300, dias_atras=350)  # ganhos há quase 12 meses: vencem em cerca de 15 dias
    conversa = _abrir(client, entrar(client, "mariana.costa@gmail.com"))
    saudacao = conversa["mensagens"][0]["texto"]
    assert saudacao.startswith("Oi, Mariana! Aqui é a Lúcia")
    assert f"300 pontos Lupe+ que vencem em {vence}" in saudacao and "checkout" in saudacao
    sugestoes = _sugestoes(conversa)
    assert sugestoes[0] == "Como uso meus pontos Lupe+?"
    assert "Onde está o pedido CL-105093?" in sugestoes  # o pedido dela ainda a caminho
    assert "Jaquetas no 50" in sugestoes  # o tipo que ela mais compra, no tamanho que ela leva
    assert len(sugestoes) == 4 and not any(s == "Quantos pontos Lupe+ eu tenho?" for s in sugestoes)


def test_pontos_longe_de_vencer_nao_entram_na_saudacao(client):
    _credito(300, dias_atras=30)
    saudacao = _abrir(client, entrar(client, "mariana.costa@gmail.com"))["mensagens"][0]["texto"]
    assert "pontos Lupe+ que vencem" not in saudacao and saudacao.startswith("Oi, Mariana!")


def test_sem_login_a_saudacao_e_a_de_sempre(client):
    assert _abrir(client)["mensagens"][0]["texto"] == BOAS_VINDAS["CLIENTE"]


def test_abrir_o_chat_nao_lanca_vencimento(client):
    _credito(200, dias_atras=400)  # já venceu, mas o vencimento ainda não foi lançado
    antes = sql("SELECT count(*) FROM movimentos_pontos WHERE cliente_id = :c", c=MARIANA)[0][0]
    saudacao = _abrir(client, entrar(client, "mariana.costa@gmail.com"))["mensagens"][0]["texto"]
    assert sql("SELECT count(*) FROM movimentos_pontos WHERE cliente_id = :c", c=MARIANA)[0][0] == antes
    assert "200 pontos" not in saudacao  # vencido não é "a vencer"


def test_busca_sem_tamanho_sugere_o_que_ela_costuma_levar(client):
    token = entrar(client, "mariana.costa@gmail.com")
    conversa = _abrir(client, token)
    chave = {"X-Conversa-Chave": conversa["chave"], **token}
    resposta = diga(client, conversa["id"], chave, "tem camisa de linho?")
    assert "Qual tamanho você procura? Nas suas compras, você costuma levar G." in resposta["texto"]
    # Sem login, não há o que sugerir
    anonima = _abrir(client)
    resposta = diga(client, anonima["id"], {"X-Conversa-Chave": anonima["chave"]}, "tem camisa de linho?")
    assert "costuma levar" not in resposta["texto"]


def test_o_modelo_recebe_o_perfil_no_contexto(client):
    _credito(300, dias_atras=350)
    falso = ProvedorFalso(texto("Posso ajudar com camisas no G."))
    ia.definir_provedor(falso)
    token = entrar(client, "mariana.costa@gmail.com")
    conversa = _abrir(client, token)
    diga(client, conversa["id"], {"X-Conversa-Chave": conversa["chave"], **token}, "quero uma camisa")
    contexto = falso.pedidos[0]["sistema"][1]["text"]
    assert "Tamanhos que o cliente costuma comprar: jaquetas 50; camisas G" in contexto
    assert "300 pontos Lupe+ que vencem em" in contexto and "Pedido em andamento mais recente: CL-105093" in contexto
