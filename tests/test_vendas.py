"""Pagamentos, devoluções (com volta ao estoque), financeiro das devoluções e anexos do atendimento.

Pedidos do seed usados aqui (src/database/seed/gerador.py, mesmos dos mocks do frontend):
- cliente 101: pedidos ENTREGUE com um item de 1 peça (e-commerce, loja 1);
- cliente 102: pedido 9, loja física, loja 2, dois itens de 1 peça;
- cliente 103: pedido 18, CANCELADO.
"""

import base64

from src.database.connection import SessionLocal
from src.models import Pedido

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _pedidos(client, headers, cliente_id):
    return client.get(f"/api/clientes/{cliente_id}/pedidos", headers=headers).json()


def _pedido_entregue_com_um_item(client, headers):
    return next(p for p in _pedidos(client, headers, 101) if p["status"] == "ENTREGUE" and len(p["itens"]) == 1)


def _estoque(client, headers, loja_id, variacao_id):
    return client.get(f"/api/estoque?lojaId={loja_id}&variacaoId={variacao_id}", headers=headers).json()[0]


def _devolver(client, headers, pedido_id, **corpo):
    return client.post(f"/api/pedidos/{pedido_id}/devolucoes", headers=headers, json={"motivo": "Não serviu", **corpo})


# ---------- Pagamentos ----------


def test_pedido_do_seed_tem_pagamento(client, admin):
    pedido = _pedido_entregue_com_um_item(client, admin)
    r = client.get(f"/api/pedidos/{pedido['id']}/pagamentos", headers=admin)
    assert r.status_code == 200, r.text
    pagamentos = r.json()
    assert len(pagamentos) == 1
    assert pagamentos[0]["status"] == "APROVADO" and pagamentos[0]["valor"] == pedido["total"]
    assert pedido["pagamento"]["status"] == "APROVADO"


def test_pedido_cancelado_tem_pagamento_estornado(client, admin):
    cancelado = next(p for p in _pedidos(client, admin, 103) if p["status"] == "CANCELADO")
    pagamentos = client.get(f"/api/pedidos/{cancelado['id']}/pagamentos", headers=admin).json()
    assert [p["status"] for p in pagamentos] == ["ESTORNADO"]


def test_pagamentos_de_pedido_inexistente(client, admin):
    assert client.get("/api/pedidos/99999/pagamentos", headers=admin).status_code == 404


# ---------- Devoluções ----------


def test_devolucao_volta_peca_ao_estoque_e_grava_movimentacao(client, admin):
    pedido = _pedido_entregue_com_um_item(client, admin)
    item = pedido["itens"][0]
    antes = _estoque(client, admin, 2, item["variacaoId"])

    r = _devolver(client, admin, pedido["id"], itemPedidoId=item["id"], quantidade=1, lojaId=2)
    assert r.status_code == 201, r.text
    devolucao = r.json()
    assert devolucao["quantidade"] == 1 and devolucao["lojaId"] == 2
    assert devolucao["valorDevolvido"] == item["precoUnitario"]
    assert devolucao["usuario"]["id"] == 1  # quem registrou vem do token

    depois = _estoque(client, admin, 2, item["variacaoId"])
    assert depois["quantidade"] == antes["quantidade"] + 1

    movs = client.get(f"/api/movimentacoes?estoqueId={depois['id']}&tipo=DEVOLUCAO", headers=admin).json()
    assert movs[0]["id"] == devolucao["movimentacaoId"]
    assert movs[0]["quantidade"] == 1 and movs[0]["saldoResultante"] == depois["quantidade"]
    assert pedido["numero"] in movs[0]["origem"]

    lista = client.get("/api/devolucoes?lojaId=2", headers=admin).json()
    assert [d["id"] for d in lista] == [devolucao["id"]]
    assert client.get("/api/devolucoes?lojaId=3", headers=admin).json() == []


def test_devolucao_pela_variacao_usa_loja_do_pedido_por_padrao(client, admin):
    pedido = _pedido_entregue_com_um_item(client, admin)
    item = pedido["itens"][0]
    r = _devolver(client, admin, pedido["id"], itemVariacaoId=item["variacaoId"], quantidade=1)
    assert r.status_code == 201, r.text
    assert r.json()["itemPedidoId"] == item["id"]
    assert r.json()["lojaId"] == pedido["lojaId"]  # admin não tem loja: volta para a loja do pedido


def test_nao_deixa_devolver_acima_do_comprado(client, admin):
    pedido = _pedido_entregue_com_um_item(client, admin)
    item = pedido["itens"][0]

    r = _devolver(client, admin, pedido["id"], itemPedidoId=item["id"], quantidade=item["quantidade"] + 1)
    assert r.status_code == 422
    assert "Só é possível devolver 1 unidade(s)" in r.json()["detail"]

    assert _devolver(client, admin, pedido["id"], itemPedidoId=item["id"], quantidade=1).status_code == 201
    r = _devolver(client, admin, pedido["id"], itemPedidoId=item["id"], quantidade=1)
    assert r.status_code == 422
    assert "já devolvido: 1" in r.json()["detail"]


def test_pedido_cancelado_recusa_devolucao(client, admin):
    cancelado = next(p for p in _pedidos(client, admin, 103) if p["status"] == "CANCELADO")
    item = cancelado["itens"][0]
    antes = _estoque(client, admin, cancelado["lojaId"], item["variacaoId"])

    r = _devolver(client, admin, cancelado["id"], itemPedidoId=item["id"], quantidade=1)
    assert r.status_code == 409
    assert "cancelado" in r.json()["detail"]
    assert _estoque(client, admin, cancelado["lojaId"], item["variacaoId"])["quantidade"] == antes["quantidade"]


def test_pedido_ainda_nao_enviado_recusa_devolucao(client, admin):
    pedido = _pedido_entregue_com_um_item(client, admin)
    with SessionLocal() as db:
        db.get(Pedido, pedido["id"]).status = "PROCESSANDO"
        db.commit()
    r = _devolver(client, admin, pedido["id"], itemPedidoId=pedido["itens"][0]["id"], quantidade=1)
    assert r.status_code == 409


def test_devolucao_valida_item_quantidade_e_motivo(client, admin):
    pedido = _pedido_entregue_com_um_item(client, admin)
    item = pedido["itens"][0]
    assert _devolver(client, admin, pedido["id"], quantidade=1).status_code == 422  # sem item
    assert _devolver(client, admin, pedido["id"], itemPedidoId=999999, quantidade=1).status_code == 422
    assert _devolver(client, admin, pedido["id"], itemPedidoId=item["id"], quantidade=0).status_code == 422
    r = client.post(
        f"/api/pedidos/{pedido['id']}/devolucoes",
        headers=admin,
        json={"itemPedidoId": item["id"], "quantidade": 1, "motivo": " "},
    )
    assert r.status_code == 422
    assert _devolver(client, admin, 99999, itemPedidoId=item["id"], quantidade=1).status_code == 404


def test_devolucao_total_estorna_pagamento_e_parcial_nao(client, admin):
    pedido = next(p for p in _pedidos(client, admin, 102) if p["status"] == "ENTREGUE" and len(p["itens"]) == 2)
    primeiro, segundo = pedido["itens"]

    assert _devolver(client, admin, pedido["id"], itemPedidoId=primeiro["id"], quantidade=1).status_code == 201
    status = [p["status"] for p in client.get(f"/api/pedidos/{pedido['id']}/pagamentos", headers=admin).json()]
    assert status == ["APROVADO"]

    assert _devolver(client, admin, pedido["id"], itemPedidoId=segundo["id"], quantidade=1).status_code == 201
    status = [p["status"] for p in client.get(f"/api/pedidos/{pedido['id']}/pagamentos", headers=admin).json()]
    assert status == ["ESTORNADO"]


def test_devolucao_ligada_a_atendimento_do_cliente(client, admin):
    pedido = _pedido_entregue_com_um_item(client, admin)
    item_id = pedido["itens"][0]["id"]
    # Atendimento de outro cliente não pode ser ligado à devolução
    outro = client.post(
        "/api/atendimentos",
        headers=admin,
        json={
            "clienteId": 102,
            "tipoSolicitacaoId": 6,
            "descricao": "Qual a composição da camisa?",
        },
    ).json()
    r = _devolver(client, admin, pedido["id"], itemPedidoId=item_id, quantidade=1, atendimentoId=outro["id"])
    assert r.status_code == 422
    assert r.json()["detail"] == "Atendimento não encontrado entre os do cliente do pedido."

    atd = client.post(
        "/api/atendimentos",
        headers=admin,
        json={
            "clienteId": 101,
            "tipoSolicitacaoId": 2,
            "pedidoId": pedido["id"],
            "descricao": "Quero devolver a peça, não serviu.",
        },
    ).json()
    r = _devolver(client, admin, pedido["id"], itemPedidoId=item_id, quantidade=1, atendimentoId=atd["id"])
    assert r.status_code == 201, r.text
    assert r.json()["atendimentoId"] == atd["id"]
    eventos = [m["conteudo"] for m in client.get(f"/api/atendimentos/{atd['id']}", headers=admin).json()["mensagens"]]
    assert eventos[-1].startswith("Devolução registrada: 1 un.")


def test_devolucoes_exigem_modulo_pedidos(client):
    assert client.get("/api/devolucoes").status_code == 401
    assert client.post("/api/pedidos/1/devolucoes", json={}).status_code == 401


# ---------- Financeiro ----------


def test_financeiro_soma_devolucoes(client, admin):
    pedido = _pedido_entregue_com_um_item(client, admin)  # loja 1
    resumo = client.get("/api/financeiro/resumo", headers=admin).json()
    assert resumo["devolucoesValor"] == 0 and resumo["devolucoesValorAnterior"] == 0
    receita = resumo["receita"]

    item = pedido["itens"][0]
    assert _devolver(client, admin, pedido["id"], itemPedidoId=item["id"], quantidade=1, lojaId=3).status_code == 201

    resumo = client.get("/api/financeiro/resumo", headers=admin).json()
    assert resumo["devolucoesValor"] == item["precoUnitario"]
    assert resumo["devolucoesValorAnterior"] == 0
    assert resumo["receita"] == receita  # a receita continua bruta

    # Filtro de lojas olha a loja do pedido (1), não a loja que recebeu a peça (3)
    assert client.get("/api/financeiro/resumo?lojas=1", headers=admin).json()["devolucoesValor"] == item["precoUnitario"]
    assert client.get("/api/financeiro/resumo?lojas=3", headers=admin).json()["devolucoesValor"] == 0
    assert client.get("/api/financeiro/resumo?comparar=nenhum", headers=admin).json()["devolucoesValorAnterior"] is None


# ---------- Anexos do atendimento ----------


def _anexo(dados: bytes, tipo="image/png", nome="foto.png"):
    return {"nome": nome, "tipo": tipo, "conteudoBase64": base64.b64encode(dados).decode()}


def test_mensagem_com_anexo_volta_como_data_url(client, lojista):
    r = client.post(
        "/api/atendimentos/1/mensagens",
        headers=lojista,
        json={"conteudo": "Segue a foto.", "anexo": _anexo(PNG, nome="C:\\fotos\\etiqueta.png")},
    )
    assert r.status_code == 201, r.text
    anexo = r.json()["mensagens"][-1]["anexo"]
    assert anexo["nome"] == "etiqueta.png" and anexo["tipo"] == "image/png"
    assert anexo["url"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert r.json()["mensagens"][0]["anexo"] is None


def test_anexo_aceita_data_url_e_mensagem_so_com_imagem(client, lojista):
    anexo = {"nome": "foto.png", "tipo": "image/png", "conteudoBase64": "data:image/png;base64," + base64.b64encode(PNG).decode()}
    r = client.post("/api/atendimentos/1/mensagens", headers=lojista, json={"conteudo": "", "anexo": anexo})
    assert r.status_code == 201, r.text


def test_anexo_recusa_tipo_nao_permitido(client, lojista):
    r = client.post(
        "/api/atendimentos/1/mensagens",
        headers=lojista,
        json={"conteudo": "Segue.", "anexo": _anexo(b"%PDF-1.7", tipo="application/pdf", nome="nota.pdf")},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "O anexo deve ser uma imagem JPG, PNG ou WEBP."


def test_anexo_recusa_conteudo_diferente_do_tipo(client, lojista):
    r = client.post(
        "/api/atendimentos/1/mensagens",
        headers=lojista,
        json={"conteudo": "Segue.", "anexo": _anexo(b"<script>alert(1)</script>")},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "O conteúdo do anexo não corresponde ao tipo informado."


def test_anexo_recusa_acima_de_2mb(client, lojista):
    grande = PNG + b"\x00" * (2 * 1024 * 1024 - len(PNG) + 1)
    r = client.post("/api/atendimentos/1/mensagens", headers=lojista, json={"conteudo": "Segue.", "anexo": _anexo(grande)})
    assert r.status_code == 422
    assert r.json()["detail"] == "O anexo deve ter no máximo 2 MB."

    no_limite = PNG + b"\x00" * (2 * 1024 * 1024 - len(PNG))
    r = client.post("/api/atendimentos/1/mensagens", headers=lojista, json={"conteudo": "Segue.", "anexo": _anexo(no_limite)})
    assert r.status_code == 201, r.text


def test_anexo_recusa_base64_invalido(client, lojista):
    anexo = {"nome": "foto.png", "tipo": "image/png", "conteudoBase64": "isto não é base64!"}
    r = client.post("/api/atendimentos/1/mensagens", headers=lojista, json={"conteudo": "Segue.", "anexo": anexo})
    assert r.status_code == 422
