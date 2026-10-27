"""Lúcia consulta a conta do cliente (decisão 93): detalhe do pedido, reembolsos e devoluções, extrato de pontos,
solicitações e frete por CEP. Sempre os dados do cliente do token; o caso do cliente separado da política."""

from datetime import timedelta

from src.database.connection import SessionLocal
from src.entities import assistente as regra
from src.integrations import ia
from src.use_cases import fidelidade
from src.utils.datas import agora
from tests.ia_falsa import ProvedorFalso, ferramenta, texto
from tests.util_assistente import abrir_site, blocos, diga, entrar, sql

MARIANA = 101


def _logada(client) -> tuple[str, dict]:
    return abrir_site(client, token=entrar(client, "mariana.costa@gmail.com"))


def test_detalhe_do_pedido_pelo_numero(client):
    conversa, chave = _logada(client)
    resposta = diga(client, conversa, chave, "como está o pedido CL-105093?")
    [pedido] = blocos(resposta, "pedido_detalhe")
    assert pedido["numero"] == "CL-105093" and pedido["statusRotulo"] == "Enviado" and pedido["itens"]
    assert "CL-105093" in resposta["texto"]


def test_pedido_de_outra_pessoa_nao_aparece(client):
    conversa, chave = _logada(client)
    resposta = diga(client, conversa, chave, "e o pedido CL-105044?")  # é do Ricardo
    assert blocos(resposta, "pedido_detalhe") == []
    assert "não está entre os pedidos" in resposta["texto"]


def test_modelo_aceita_so_os_digitos_do_pedido(client):
    ia.definir_provedor(ProvedorFalso(ferramenta("ver_pedido", {"numero_pedido": "105037"}), texto("Seu pedido foi enviado.")))
    conversa, chave = _logada(client)
    resposta = diga(client, conversa, chave, "meu pedido 105037")
    assert resposta["modo"] == regra.LLM
    assert blocos(resposta, "pedido_detalhe")[0]["numero"] == "CL-105037"


def test_reembolso_e_o_caso_dela_nao_a_politica(client):
    sql("UPDATE pedidos SET status = 'CANCELADO' WHERE numero = 'CL-105037'")
    sql("UPDATE pagamentos SET status = 'ESTORNADO' WHERE pedido_id = (SELECT id FROM pedidos WHERE numero = 'CL-105037')")
    item, variacao, loja, preco = sql(
        "SELECT i.id, i.variacao_id, p.loja_id, i.preco_unitario FROM itens_pedido i JOIN pedidos p ON p.id = i.pedido_id "
        "WHERE p.numero = 'CL-104981' LIMIT 1"
    )[0]
    sql(
        "INSERT INTO devolucoes (item_pedido_id, pedido_id, variacao_id, loja_id, quantidade, valor_devolvido, motivo, criada_em) "
        "SELECT :i, id, :v, :l, 1, :preco, 'Ficou grande', now() FROM pedidos WHERE numero = 'CL-104981'",
        i=item,
        v=variacao,
        l=loja,
        preco=preco,
    )
    conversa, chave = _logada(client)
    resposta = diga(client, conversa, chave, "como está a minha situação de reembolso?")
    [reembolsos] = blocos(resposta, "reembolsos")
    assert reembolsos["estornos"][0]["pedido"] == "CL-105037"
    assert reembolsos["devolucoes"][0]["pedido"] == "CL-104981"
    assert "CL-105037" in resposta["texto"] or "CL-104981" in resposta["texto"]
    # Pergunta de regra continua indo para a política, sem abrir a conta
    politica = diga(client, conversa, chave, "como funciona a devolução?")
    assert blocos(politica, "reembolsos") == [] and "30 dias" in politica["texto"]


def test_troca_em_andamento_e_sem_nada(client):
    conversa, chave = _logada(client)
    # No seed, a Mariana tem uma troca em andamento: aparece como em análise
    resposta = diga(client, conversa, chave, "cadê meu estorno?")
    [reembolsos] = blocos(resposta, "reembolsos")
    assert reembolsos["estornos"] == [] and reembolsos["emAnalise"][0]["assunto"] == "Troca de produto"
    # Sem nada em aberto, diz que não achou e oferece a devolução
    sql("UPDATE atendimentos SET status = 'CONCLUIDO' WHERE cliente_id = :c", c=MARIANA)
    resposta = diga(client, conversa, chave, "cadê meu estorno?")
    assert "Não encontrei reembolso" in resposta["texto"]


def test_extrato_mostra_para_onde_foram_os_pontos(client):
    with SessionLocal() as db:
        fidelidade.travar(db, MARIANA)
        fidelidade.lancar(db, MARIANA, "CREDITO", 1200, agora() - timedelta(days=30), obs="teste")
        db.commit()
    conversa, chave = _logada(client)
    resposta = diga(client, conversa, chave, "meus pontos sumiram!")
    [extrato] = blocos(resposta, "extrato")
    assert extrato["saldo"] == 1200 and extrato["itens"][0]["pontos"] == 1200
    assert extrato["itens"][0]["tipo"] == "Pontos de compra"


def test_minhas_solicitacoes(client):
    conversa, chave = _logada(client)
    diga(client, conversa, chave, "quero falar com um atendente")
    protocolo = client.post(f"/api/assistente/conversas/{conversa}/atendimento", json={}, headers=chave).json()["protocolo"]
    resposta = diga(client, conversa, chave, "minha solicitação foi respondida?")
    itens = blocos(resposta, "solicitacoes")[0]["itens"]
    assert itens[0]["protocolo"] == protocolo and itens[0]["link"].startswith("/cliente/solicitacoes/")


def test_frete_pelo_cep_sem_login(client):
    conversa, chave = abrir_site(client)
    resposta = diga(client, conversa, chave, "quanto é o frete para o CEP 69000-000?")
    [frete] = blocos(resposta, "frete")
    assert frete["cep"] == "69000-000" and frete["opcoes"]
    assert "dias úteis" in resposta["texto"]


def test_sem_login_as_consultas_pedem_o_login_no_chat(client):
    conversa, chave = abrir_site(client)
    for pergunta in ("cadê meu reembolso?", "quero ver meu extrato", "pedido CL-105093"):
        assert blocos(diga(client, conversa, chave, pergunta), "entrar") == [{"tipo": "entrar"}], pergunta


def test_cliente_irritado_vai_direto_para_uma_pessoa(client):
    conversa, chave = abrir_site(client)
    resposta = diga(client, conversa, chave, "vocês são uma porcaria, quero meu dinheiro de volta AGORA")
    assert resposta["texto"].startswith("Sinto muito pelo transtorno")
    assert blocos(resposta, "acao_atendimento")
