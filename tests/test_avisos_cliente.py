"""E-mails automáticos ao cliente (decisões 98 a 100): pedido enviado e entregue, "Avise-me quando chegar" e
lembrete de sacola abandonada. Nada sai de verdade: o envio é trocado por uma lista."""

from datetime import timedelta

import pytest

from src.config import settings
from src.use_cases import automacoes, avisos_cliente, pedidos
from src.utils.datas import agora
from tests.util_assistente import sql

MARIANA = 101
EMAIL_MARIANA = "mariana.costa@gmail.com"
CEP_SP = "01310-100"


def _compra(variacao_id):
    return {
        "endereco": {
            "cep": CEP_SP,
            "rua": "Av. Paulista",
            "numero": "1000",
            "bairro": "Bela Vista",
            "cidade": "São Paulo",
            "uf": "SP",
        },
        "freteTipo": "PADRAO",
        "pagamento": {"metodo": "CARTAO", "parcelas": 1},
        "itens": [{"variacaoId": variacao_id, "quantidade": 1}],
    }


def _produto_com_estoque(client):
    """(produto, variação) à venda no site, com peça disponível."""
    for produto in client.get("/api/produtos?ativo=true").json():
        for v in produto["variacoes"]:
            if v["disponivel"] >= 2:
                return produto, v
    raise AssertionError("nenhuma peça disponível")


def _esgotar(variacao_id: int) -> int:
    """Zera a peça em todas as lojas (só no banco de testes). Devolve um item de estoque dela."""
    sql("UPDATE estoques SET quantidade = 0 WHERE variacao_id = :v", v=variacao_id)
    [(estoque_id,)] = sql(
        "SELECT e.id FROM estoques e JOIN lojas l ON l.id = e.loja_id WHERE e.variacao_id = :v AND l.ativa ORDER BY e.id LIMIT 1",
        v=variacao_id,
    )
    return estoque_id


@pytest.fixture
def caixa(monkeypatch):
    """Liga os dois avisos, troca o Resend por uma lista e roda a conferência "na hora" sem thread."""
    enviados = []
    monkeypatch.setattr(settings, "AVISO_ESTOQUE_ENVIAR", True)
    monkeypatch.setattr(settings, "LEMBRETE_SACOLA_ENVIAR", True)
    monkeypatch.setattr(settings, "AVISOS_TESTE_PARA", "")
    monkeypatch.setattr(avisos_cliente, "PAUSA_ENTRE_ENVIOS", 0)
    monkeypatch.setattr(avisos_cliente, "_enviar_de_verdade", enviados.append)

    class Imediata:
        def submit(self, funcao, *args):
            funcao(*args)

    monkeypatch.setattr(avisos_cliente, "_fila", Imediata())
    # Modo real: só quem criou a conta no site recebe (decisão 128)
    sql("UPDATE clientes SET canal_cadastro = 'E-commerce' WHERE id = :c", c=MARIANA)
    return enviados


# ---------- Pedido enviado e entregue ----------


def test_cliente_recebe_email_quando_o_pedido_sai_e_quando_chega(client, admin, mariana, monkeypatch):
    emails = []
    monkeypatch.setattr(pedidos, "enviar_email", emails.append)
    _, variacao = _produto_com_estoque(client)
    numero = client.post("/api/checkout", json=_compra(variacao["id"]), headers=mariana).json()["numero"]
    [resumo] = client.get(f"/api/pedidos?busca={numero}", headers=admin).json()
    # Garante a peça na loja de expedição (o envio exige)
    sql(
        "UPDATE estoques SET quantidade = quantidade + 1 WHERE variacao_id = :v AND loja_id = (SELECT loja_id FROM pedidos WHERE id = :p)",
        v=variacao["id"],
        p=resumo["id"],
    )

    r = client.patch(f"/api/pedidos/{resumo['id']}", headers=admin, json={"status": "ENVIADO", "codigoRastreio": "br123sp"})
    assert r.status_code == 200, r.text
    [enviado] = emails
    assert enviado.para == EMAIL_MARIANA and f"Pedido {numero} enviado" in enviado.assunto
    assert "BR123SP" in enviado.texto and "/cliente/pedidos" in enviado.texto

    client.patch(f"/api/pedidos/{resumo['id']}", headers=admin, json={"status": "ENTREGUE"})
    assert len(emails) == 2
    assert f"Pedido {numero} entregue" in emails[1].assunto and "30 dias" in emails[1].texto


def test_venda_de_loja_nao_recebe_email_de_andamento(monkeypatch):
    """Só pedidos do site (CL-): vendas de loja e pedidos migrados da Vulto não recebem."""
    from src import models as m

    emails = []
    monkeypatch.setattr(pedidos, "enviar_email", emails.append)
    cliente = m.Cliente(nome="Mariana Costa", email=EMAIL_MARIANA)
    for numero in ("S100234", "APP-7001205"):
        pedidos.avisar_andamento(m.Pedido(numero=numero, status="ENVIADO", cliente=cliente, codigo_rastreio="X"))
    assert emails == []
    pedidos.avisar_andamento(m.Pedido(numero="CL-1", status="ENVIADO", cliente=cliente, codigo_rastreio="X"))
    assert len(emails) == 1


# ---------- Avise-me quando chegar ----------


def test_pedir_aviso_exige_login_e_peca_esgotada(client, mariana):
    produto, variacao = _produto_com_estoque(client)
    assert client.post("/api/conta/avisos-estoque", json={"variacaoId": variacao["id"]}).status_code == 401
    r = client.post("/api/conta/avisos-estoque", json={"variacaoId": variacao["id"]}, headers=mariana)
    assert r.status_code == 409  # disponível: pode comprar
    assert client.post("/api/conta/avisos-estoque", json={"variacaoId": 999999}, headers=mariana).status_code == 404

    _esgotar(variacao["id"])
    for _ in range(2):  # pedir de novo não duplica
        r = client.post("/api/conta/avisos-estoque", json={"variacaoId": variacao["id"]}, headers=mariana)
        assert r.status_code == 201 and r.json()["variacaoIds"] == [variacao["id"]]
    assert client.get("/api/conta/avisos-estoque", headers=mariana).json()["variacaoIds"] == [variacao["id"]]

    assert client.delete(f"/api/conta/avisos-estoque/{variacao['id']}", headers=mariana).status_code == 204
    assert client.get("/api/conta/avisos-estoque", headers=mariana).json()["variacaoIds"] == []


def test_desligado_por_padrao_nao_avisa(client, admin, mariana, monkeypatch):
    monkeypatch.setattr(settings, "AVISO_ESTOQUE_ENVIAR", False)
    _, variacao = _produto_com_estoque(client)
    estoque_id = _esgotar(variacao["id"])
    client.post("/api/conta/avisos-estoque", json={"variacaoId": variacao["id"]}, headers=mariana)
    client.post("/api/movimentacoes", headers=admin, json={"estoqueId": estoque_id, "tipo": "ENTRADA", "quantidade": 3})
    execucao = automacoes.executar("aviso_estoque")
    assert execucao.status == "SUCESSO" and "desligado" in execucao.detalhe
    assert sql("SELECT avisado_em FROM avisos_estoque") == [(None,)]


def test_entrada_de_estoque_avisa_na_hora_e_uma_vez(client, admin, mariana, caixa):
    produto, variacao = _produto_com_estoque(client)
    estoque_id = _esgotar(variacao["id"])
    client.post("/api/conta/avisos-estoque", json={"variacaoId": variacao["id"]}, headers=mariana)

    r = client.post("/api/movimentacoes", headers=admin, json={"estoqueId": estoque_id, "tipo": "ENTRADA", "quantidade": 3})
    assert r.status_code == 201, r.text
    [email] = caixa
    assert email.para == EMAIL_MARIANA and "voltou ao estoque" in email.assunto
    assert produto["nome"] in email.texto and f"/produto/{produto['id']}" in email.texto
    [(avisado_em, modo, para)] = sql("SELECT avisado_em, modo, email FROM avisos_estoque")
    assert avisado_em is not None and modo == "REAL" and para == EMAIL_MARIANA
    assert client.get("/api/conta/avisos-estoque", headers=mariana).json()["variacaoIds"] == []

    # Outra entrada e a automação: ninguém recebe de novo
    client.post("/api/movimentacoes", headers=admin, json={"estoqueId": estoque_id, "tipo": "ENTRADA", "quantidade": 1})
    automacoes.executar("aviso_estoque", forcar=True)
    assert len(caixa) == 1


def test_automacao_pega_o_que_voltou_sem_movimentacao(client, mariana, caixa):
    _, variacao = _produto_com_estoque(client)
    _esgotar(variacao["id"])
    client.post("/api/conta/avisos-estoque", json={"variacaoId": variacao["id"]}, headers=mariana)
    automacoes.executar("aviso_estoque")
    assert caixa == []  # ainda esgotada

    sql("UPDATE estoques SET quantidade = 2 WHERE variacao_id = :v", v=variacao["id"])
    execucao = automacoes.executar("aviso_estoque", forcar=True)
    assert execucao.criados == 1 and len(caixa) == 1


def test_modo_teste_manda_para_o_time(client, admin, mariana, caixa, monkeypatch):
    monkeypatch.setattr(settings, "AVISOS_TESTE_PARA", "time@exemplo.com")
    _, variacao = _produto_com_estoque(client)
    estoque_id = _esgotar(variacao["id"])
    client.post("/api/conta/avisos-estoque", json={"variacaoId": variacao["id"]}, headers=mariana)
    client.post("/api/movimentacoes", headers=admin, json={"estoqueId": estoque_id, "tipo": "ENTRADA", "quantidade": 1})
    [email] = caixa
    assert email.para == "time@exemplo.com" and EMAIL_MARIANA in email.assunto
    assert sql("SELECT modo FROM avisos_estoque") == [("TESTE",)]


def test_falha_no_envio_deixa_o_aviso_pendente(client, admin, mariana, caixa, monkeypatch):
    def falha(_email):
        raise RuntimeError("Resend fora do ar")

    monkeypatch.setattr(avisos_cliente, "_enviar_de_verdade", falha)
    _, variacao = _produto_com_estoque(client)
    estoque_id = _esgotar(variacao["id"])
    client.post("/api/conta/avisos-estoque", json={"variacaoId": variacao["id"]}, headers=mariana)
    r = client.post("/api/movimentacoes", headers=admin, json={"estoqueId": estoque_id, "tipo": "ENTRADA", "quantidade": 1})
    assert r.status_code == 201  # a entrada de estoque não depende do e-mail
    assert sql("SELECT avisado_em FROM avisos_estoque") == [(None,)]


# ---------- Sacola abandonada ----------


def _sacola_parada(client, headers, variacao_id, horas=25):
    assert (
        client.put(
            "/api/conta/sacola", headers=headers, json={"itens": [{"variacaoId": variacao_id, "quantidade": 2}]}
        ).status_code
        == 204
    )
    sql("UPDATE sacolas SET atualizada_em = :t", t=agora() - timedelta(hours=horas))


def test_sacola_guardada_volta_com_os_dados_da_peca(client, mariana):
    produto, variacao = _produto_com_estoque(client)
    assert client.put("/api/conta/sacola", json={"itens": []}).status_code == 401
    itens = [{"variacaoId": variacao["id"], "quantidade": 9}, {"variacaoId": 999999, "quantidade": 1}]
    assert client.put("/api/conta/sacola", headers=mariana, json={"itens": itens}).status_code == 204
    [item] = client.get("/api/conta/sacola", headers=mariana).json()["itens"]
    assert item["variacaoId"] == variacao["id"] and item["nome"] == produto["nome"]
    assert item["quantidade"] == 5  # o mesmo limite do site; a peça inexistente foi ignorada

    client.put("/api/conta/sacola", headers=mariana, json={"itens": []})
    assert sql("SELECT count(*) FROM sacolas") == [(0,)]


def test_lembrete_so_para_quem_aceita_e_uma_vez(client, mariana, caixa):
    produto, variacao = _produto_com_estoque(client)
    sql("UPDATE clientes SET aceita_marketing = false WHERE id = :c", c=MARIANA)
    _sacola_parada(client, mariana, variacao["id"])
    automacoes.executar("lembrete_sacola")
    assert caixa == []  # sem consentimento

    assert client.put("/api/conta/preferencias", headers=mariana, json={"aceitaMarketing": True}).json() == {
        "aceitaMarketing": True
    }
    assert client.get("/api/conta/preferencias", headers=mariana).json() == {"aceitaMarketing": True}
    execucao = automacoes.executar("lembrete_sacola", forcar=True)
    assert execucao.criados == 1
    [email] = caixa
    assert email.para == EMAIL_MARIANA and "sacola" in email.assunto
    assert f"2 × {produto['nome']}" in email.texto and "?sacola=abrir" in email.texto and "Minha conta" in email.texto

    automacoes.executar("lembrete_sacola", forcar=True)
    assert len(caixa) == 1


def test_sem_lembrete_antes_de_1h_ou_depois_da_compra(client, mariana, caixa):
    _, variacao = _produto_com_estoque(client)
    sql("UPDATE clientes SET aceita_marketing = true WHERE id = :c", c=MARIANA)
    _sacola_parada(client, mariana, variacao["id"], horas=0.5)  # meia hora: ainda não é sacola abandonada
    automacoes.executar("lembrete_sacola")
    assert caixa == []

    _sacola_parada(client, mariana, variacao["id"], horas=25)
    client.post("/api/checkout", json=_compra(variacao["id"]), headers=mariana)
    sql("UPDATE pedidos SET criado_em = :t WHERE cliente_id = :c AND numero LIKE 'CL-%'", t=agora(), c=MARIANA)
    automacoes.executar("lembrete_sacola", forcar=True)
    assert caixa == []  # comprou depois de mexer na sacola


def test_excluir_a_conta_apaga_sacola_e_avisos(client, mariana):
    _, variacao = _produto_com_estoque(client)
    client.put("/api/conta/sacola", headers=mariana, json={"itens": [{"variacaoId": variacao["id"], "quantidade": 1}]})
    _esgotar(variacao["id"])
    client.post("/api/conta/avisos-estoque", json={"variacaoId": variacao["id"]}, headers=mariana)
    from src.database.seed import SENHA_DEMO

    assert client.post("/api/conta/exclusao", headers=mariana, json={"senha": SENHA_DEMO}).status_code == 204
    assert sql("SELECT (SELECT count(*) FROM sacolas) + (SELECT count(*) FROM avisos_estoque)") == [(0,)]
