"""Ações da conta pelo chat da Lúcia (decisões 95 a 97): a ferramenta só prepara o cartão; a ação acontece na rota
da conta quando o cliente confirma. Cancelar só em separação (o mesmo cancelamento do painel), devolução até 30
dias do recebimento (abre a solicitação; a equipe faz o estorno) e e-mail com a senha atual."""

from src.database.seed import SENHA_DEMO
from src.integrations import ia
from tests.ia_falsa import ProvedorFalso, ferramenta, texto
from tests.util_assistente import abrir_site, blocos, diga, entrar, sql

MARIANA = 101


def _logada(client) -> tuple[str, dict, dict]:
    token = entrar(client, "mariana.costa@gmail.com")
    conversa, chave = abrir_site(client, token=token)
    return conversa, chave, token


def _concluir(client, conversa, chave, mensagem_id, acao, detalhe=""):
    r = client.post(
        f"/api/assistente/conversas/{conversa}/eventos",
        json={"tipo": "ACAO_CONCLUIDA", "mensagemId": mensagem_id, "acao": acao, "detalhe": detalhe},
        headers=chave,
    )
    assert r.status_code == 204, r.text


def _estado(client, conversa, chave, tipo):
    historico = client.get(f"/api/assistente/conversas/{conversa}", headers=chave).json()["mensagens"]
    return [b for m in historico for b in m["blocos"] if b["tipo"] == tipo][-1]["estado"]


def _recebido_ha(numero: str, dias: int) -> None:
    sql(
        "UPDATE eventos_pedido SET criado_em = now() - make_interval(days => :d) "
        "WHERE status = 'ENTREGUE' AND pedido_id = (SELECT id FROM pedidos WHERE numero = :n)",
        d=dias,
        n=numero,
    )
    sql("UPDATE pedidos SET criado_em = now() - make_interval(days => :d) WHERE numero = :n", d=dias + 3, n=numero)


# ---------- Cancelar ----------


def test_cancela_pedido_em_separacao_pelo_cartao(client):
    sql("UPDATE pedidos SET status = 'PROCESSANDO', codigo_rastreio = NULL WHERE numero = 'CL-105093'")
    conversa, chave, token = _logada(client)
    resposta = diga(client, conversa, chave, "quero cancelar o pedido CL-105093")
    [cartao] = blocos(resposta, "confirmar_cancelamento")
    assert cartao["numero"] == "CL-105093" and cartao["estado"] == "PENDENTE"
    assert sql("SELECT status FROM pedidos WHERE numero = 'CL-105093'")[0][0] == "PROCESSANDO"  # nada feito ainda

    r = client.post("/api/conta/pedidos/CL-105093/cancelamento", headers=token)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CANCELADO" and r.json()["valorEstornado"] > 0
    pagamento, evento = sql(
        "SELECT pg.status, e.observacao FROM pedidos p JOIN pagamentos pg ON pg.pedido_id = p.id "
        "JOIN eventos_pedido e ON e.pedido_id = p.id AND e.status = 'CANCELADO' WHERE p.numero = 'CL-105093'"
    )[0]
    assert pagamento == "ESTORNADO" and "cliente" in evento
    _concluir(client, conversa, chave, resposta["id"], "CANCELAMENTO", "CL-105093")
    assert _estado(client, conversa, chave, "confirmar_cancelamento") == "CONCLUIDO"
    # De novo: já está cancelado
    assert client.post("/api/conta/pedidos/CL-105093/cancelamento", headers=token).status_code == 409


def test_pedido_enviado_nao_cancela_e_a_lucia_oferece_devolucao(client):
    conversa, chave, token = _logada(client)
    resposta = diga(client, conversa, chave, "quero cancelar o pedido CL-105037")  # já foi enviado
    assert blocos(resposta, "confirmar_cancelamento") == []
    assert "devolução" in resposta["texto"] and "solicitar_devolucao" not in resposta["texto"]
    assert client.post("/api/conta/pedidos/CL-105037/cancelamento", headers=token).status_code == 409


def test_nao_cancela_pedido_de_outra_pessoa(client):
    _, _, token = _logada(client)
    assert client.post("/api/conta/pedidos/CL-105044/cancelamento", headers=token).status_code == 404  # é do Ricardo
    assert sql("SELECT status FROM pedidos WHERE numero = 'CL-105044'")[0][0] != "CANCELADO"


def test_sem_numero_a_lucia_pergunta_qual_pedido(client):
    conversa, chave, _ = _logada(client)
    resposta = diga(client, conversa, chave, "cancela minha compra")
    assert "Qual pedido" in resposta["texto"] and blocos(resposta, "confirmar_cancelamento") == []


# ---------- Devolução ----------


def test_devolucao_abre_a_solicitacao_com_as_pecas(client):
    _recebido_ha("CL-104981", 5)
    conversa, chave, token = _logada(client)
    resposta = diga(client, conversa, chave, "quero devolver o pedido CL-104981, ficou grande")
    [cartao] = blocos(resposta, "confirmar_devolucao")
    assert cartao["numero"] == "CL-104981" and cartao["pecas"] and "ficou grande" in cartao["motivo"]
    peca = cartao["pecas"][0]

    corpo = {"pecas": [{"itemPedidoId": peca["itemPedidoId"], "quantidade": 1}], "motivo": "Ficou grande"}
    r = client.post("/api/conta/pedidos/CL-104981/devolucao", json=corpo, headers=token)
    assert r.status_code == 201, r.text
    protocolo = r.json()["protocolo"]
    tipo, pedido, mensagem = sql(
        "SELECT t.conta_pos_venda, p.numero, m.conteudo FROM atendimentos a JOIN tipos_solicitacao t ON t.id = a.tipo_solicitacao_id "
        "JOIN pedidos p ON p.id = a.pedido_id JOIN mensagens m ON m.atendimento_id = a.id WHERE a.protocolo = :p",
        p=protocolo,
    )[0]
    assert (tipo, pedido) == ("DEVOLUCAO", "CL-104981")
    assert "Ficou grande" in mensagem and peca["nome"] in mensagem
    # Pedir de novo devolve a mesma solicitação
    assert client.post("/api/conta/pedidos/CL-104981/devolucao", json=corpo, headers=token).json()["protocolo"] == protocolo
    _concluir(client, conversa, chave, resposta["id"], "DEVOLUCAO", protocolo)
    assert _estado(client, conversa, chave, "confirmar_devolucao") == "CONCLUIDO"


def test_devolucao_fora_do_prazo_ou_quantidade_errada(client):
    _recebido_ha("CL-104981", 40)
    conversa, chave, token = _logada(client)
    resposta = diga(client, conversa, chave, "quero devolver o pedido CL-104981")
    assert blocos(resposta, "confirmar_devolucao") == [] and "prazo" in resposta["texto"]
    item = sql("SELECT i.id FROM itens_pedido i JOIN pedidos p ON p.id = i.pedido_id WHERE p.numero = 'CL-104981' LIMIT 1")[0][0]
    corpo = {"pecas": [{"itemPedidoId": item, "quantidade": 1}], "motivo": "Ficou grande"}
    assert client.post("/api/conta/pedidos/CL-104981/devolucao", json=corpo, headers=token).status_code == 409
    _recebido_ha("CL-104981", 5)
    corpo["pecas"][0]["quantidade"] = 99
    assert client.post("/api/conta/pedidos/CL-104981/devolucao", json=corpo, headers=token).status_code == 422


# ---------- E-mail ----------


def test_troca_de_email_pelo_cartao_com_a_senha(client):
    conversa, chave, token = _logada(client)
    resposta = diga(client, conversa, chave, "quero trocar meu e-mail para mariana.nova@gmail.com")
    [cartao] = blocos(resposta, "confirmar_email")
    assert cartao["emailNovo"] == "mariana.nova@gmail.com"
    assert sql("SELECT email FROM clientes WHERE id = :c", c=MARIANA)[0][0] == "mariana.costa@gmail.com"  # nada feito

    conta = client.get("/api/conta", headers=token).json()
    errada = {**conta, "email": "mariana.nova@gmail.com", "senhaAtual": "errada123"}
    assert client.put("/api/conta", json=errada, headers=token).status_code == 422
    certa = {**errada, "senhaAtual": SENHA_DEMO}
    assert client.put("/api/conta", json=certa, headers=token).status_code == 200
    assert sql("SELECT email FROM clientes WHERE id = :c", c=MARIANA)[0][0] == "mariana.nova@gmail.com"
    _concluir(client, conversa, chave, resposta["id"], "EMAIL", "mariana.nova@gmail.com")
    assert _estado(client, conversa, chave, "confirmar_email") == "CONCLUIDO"


def test_email_invalido_ou_sem_email_novo(client):
    conversa, chave, _ = _logada(client)
    assert "e-mail novo" in diga(client, conversa, chave, "quero trocar meu email")["texto"]
    resposta = diga(client, conversa, chave, "quero trocar meu email para mariana@semponto")
    assert blocos(resposta, "confirmar_email") == []


def test_sem_login_as_acoes_pedem_o_login(client):
    conversa, chave = abrir_site(client)
    resposta = diga(client, conversa, chave, "quero cancelar o pedido CL-105093")
    assert blocos(resposta, "entrar") == [{"tipo": "entrar"}]


def test_modelo_so_prepara_o_cartao(client):
    sql("UPDATE pedidos SET status = 'PROCESSANDO' WHERE numero = 'CL-105093'")
    ia.definir_provedor(
        ProvedorFalso(ferramenta("cancelar_pedido", {"numero_pedido": "CL-105093"}), texto("Confirme no cartão abaixo."))
    )
    conversa, chave, _ = _logada(client)
    resposta = diga(client, conversa, chave, "cancela o meu pedido 105093")
    assert blocos(resposta, "confirmar_cancelamento")[0]["numero"] == "CL-105093"
    assert sql("SELECT status FROM pedidos WHERE numero = 'CL-105093'")[0][0] == "PROCESSANDO"
