"""Remover produto do catálogo: some da loja, do painel e do estoque; o histórico continua."""

from datetime import date

NOVO = {
    "nome": "Camisa Removível",
    "categoria": "Camisaria",
    "precoBase": 300,
    "ativo": True,
    "genero": "Masculino",
    "variacoes": [{"sku": "CL-RMV-AZU-M", "tamanho": "M", "cor": "Azul", "precoCusto": 120}],
}
CEP_SP = "01310-100"


def _criar(client, admin):
    r = client.post("/api/produtos", headers=admin, json=NOVO)
    assert r.status_code == 201, r.text
    return r.json()


def test_remover_tira_o_produto_da_loja_do_painel_e_do_estoque(client, admin):
    produto = _criar(client, admin)
    variacao_id = produto["variacoes"][0]["id"]
    estoque_id = client.get(f"/api/estoque?variacaoId={variacao_id}", headers=admin).json()[0]["id"]

    assert client.delete(f"/api/produtos/{produto['id']}", headers=admin).status_code == 204

    assert produto["id"] not in [p["id"] for p in client.get("/api/produtos").json()]
    assert produto["id"] not in [p["id"] for p in client.get("/api/produtos", headers=admin).json()]
    assert client.get(f"/api/produtos/{produto['id']}").status_code == 404
    assert client.get(f"/api/estoque?variacaoId={variacao_id}", headers=admin).json() == []
    assert client.put(f"/api/produtos/{produto['id']}", headers=admin, json=NOVO).status_code == 404
    assert client.delete(f"/api/produtos/{produto['id']}", headers=admin).status_code == 404

    # Estoque e transferências da peça removida ficam bloqueados
    mov = {"estoqueId": estoque_id, "tipo": "ENTRADA", "quantidade": 2, "origem": "Teste"}
    assert client.post("/api/movimentacoes", headers=admin, json=mov).status_code == 409
    transf = {"variacaoId": variacao_id, "lojaOrigemId": 1, "lojaDestinoId": 2, "quantidade": 1}
    assert client.post("/api/transferencias", headers=admin, json=transf).status_code == 409

    # O SKU continua reservado (é do histórico)
    outro = client.post("/api/produtos", headers=admin, json={**NOVO, "nome": "Outra"})
    assert outro.status_code == 422 and "produto removido" in outro.json()["detail"]

    registro = client.get("/api/admin/log?area=PRODUTOS", headers=admin).json()[0]
    assert registro["acao"] == "REMOVEU" and registro["descricao"] == "Removeu o produto Camisa Removível"


def test_so_o_administrador_remove(client, admin, lojista, operador, mariana):
    produto = _criar(client, admin)
    assert client.delete(f"/api/produtos/{produto['id']}").status_code == 401
    assert client.delete(f"/api/produtos/{produto['id']}", headers=mariana).status_code == 401
    assert client.delete(f"/api/produtos/{produto['id']}", headers=lojista).status_code == 403
    assert client.delete(f"/api/produtos/{produto['id']}", headers=operador).status_code == 403


def test_pedido_em_andamento_impede_remover_e_o_historico_continua(client, admin, mariana):
    produto = _criar(client, admin)
    variacao_id = produto["variacoes"][0]["id"]
    estoque = client.get(f"/api/estoque?variacaoId={variacao_id}&lojaId=1", headers=admin).json()[0]
    client.post(
        "/api/movimentacoes", headers=admin, json={"estoqueId": estoque["id"], "tipo": "ENTRADA", "quantidade": 5, "origem": "NF"}
    )
    compra = {
        "endereco": {
            "cep": CEP_SP,
            "rua": "Av. Paulista",
            "numero": "1",
            "bairro": "Bela Vista",
            "cidade": "São Paulo",
            "uf": "SP",
        },
        "freteTipo": "PADRAO",
        "pagamento": {"metodo": "PIX"},
        "itens": [{"variacaoId": variacao_id, "quantidade": 1}],
    }
    numero = client.post("/api/checkout", headers=mariana, json=compra).json()["numero"]

    bloqueado = client.delete(f"/api/produtos/{produto['id']}", headers=admin)
    assert bloqueado.status_code == 409 and "1 pedido em processamento" in bloqueado.json()["detail"]

    pedido = client.get(f"/api/pedidos?busca={numero}", headers=admin).json()[0]
    assert client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"status": "CANCELADO"}).status_code == 200
    assert client.delete(f"/api/produtos/{produto['id']}", headers=admin).status_code == 204
    registro = client.get("/api/admin/log?area=PRODUTOS", headers=admin).json()[0]
    assert registro["descricao"] == "Removeu o produto Camisa Removível (5 peças em estoque saíram do catálogo)"

    # O pedido antigo continua com a peça, para o histórico e o financeiro
    depois = client.get(f"/api/pedidos/{pedido['id']}", headers=admin).json()
    assert depois["itens"][0]["variacao"]["produto"]["nome"] == "Camisa Removível"
    assert numero in [p["numero"] for p in client.get("/api/clientes/101/pedidos", headers=mariana).json()]
    # E a posição de estoque numa data passada ainda mostra a peça
    posicao = client.get(f"/api/estoque/posicao?data={date.today().isoformat()}&busca=Removível", headers=admin).json()
    assert posicao, "a posição em data reconstrói o passado, inclusive de produtos removidos"
