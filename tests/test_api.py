"""Regras de negócio e permissões das rotas que alteram dados.

Os formatos de resposta seguem os mocks do frontend (src/services/mock).
"""


# ---------- Autenticação e permissões ----------

def test_login_devolve_token_e_usuario(client):
    r = client.post("/api/auth/login", json={"email": " HELENA@casalorenzi.com.br ", "senha": "lorenzi2026"})
    assert r.status_code == 200
    assert r.json()["usuario"] == {
        "id": 1, "nome": "Helena Lorenzi", "email": "helena@casalorenzi.com.br", "papel": "ADMINISTRADOR", "lojaId": None,
    }


def test_login_com_senha_errada(client):
    r = client.post("/api/auth/login", json={"email": "helena@casalorenzi.com.br", "senha": "errada"})
    assert r.status_code == 401
    assert r.json() == {"detail": "E-mail ou senha incorretos."}


def test_rotas_internas_exigem_token(client):
    assert client.get("/api/estoque").status_code == 401
    assert client.get("/api/estoque", headers={"Authorization": "Bearer invalido"}).status_code == 401


def test_rotas_publicas_da_vitrine(client):
    for rota in ("/api/produtos?ativo=true", "/api/lojas", "/api/categorias", "/api/tipos-solicitacao"):
        assert client.get(rota).status_code == 200, rota


def test_permissoes_por_papel(client, lojista, operador, cliente):
    assert client.get("/api/financeiro/resumo", headers=lojista).status_code == 403
    assert client.get("/api/transferencias", headers=lojista).status_code == 403
    assert client.get("/api/atendimentos", headers=operador).status_code == 403
    assert client.get("/api/estoque", headers=cliente).status_code == 403
    assert client.post("/api/produtos", headers=operador, json={}).status_code == 403


def test_lojista_ve_dashboard_so_da_propria_loja(client, lojista):
    r = client.get("/api/dashboard/resumo?lojaId=3", headers=lojista)
    assert r.status_code == 200
    assert [item["loja"]["id"] for item in r.json()["resumoPorLoja"]] == [1]


# ---------- Produtos ----------

def _novo_produto(**extra):
    return {
        "nome": "Camisa Teste", "categoria": "Camisaria", "precoBase": 199.9, "ativo": True,
        "variacoes": [{"sku": "cl-tst-azu-m", "tamanho": "M", "cor": "Azul"}], **extra,
    }


def test_criar_produto_gera_estoque_zerado_nas_lojas(client, admin):
    r = client.post("/api/produtos", headers=admin, json=_novo_produto())
    assert r.status_code == 201, r.text
    produto = r.json()
    assert produto["variacoes"][0]["sku"] == "CL-TST-AZU-M"
    assert produto["estoqueTotal"] == 0
    estoques = client.get(f"/api/estoque?variacaoId={produto['variacoes'][0]['id']}", headers=admin).json()
    assert len(estoques) == 4
    assert {e["status"] for e in estoques} == {"SEM_ESTOQUE"}


def test_criar_produto_valida_sku_duplicado(client, admin):
    r = client.post("/api/produtos", headers=admin, json=_novo_produto(variacoes=[{"sku": "CL-CML-BRA-P", "tamanho": "P", "cor": "Branco"}]))
    assert r.status_code == 422
    assert r.json()["detail"] == "O SKU CL-CML-BRA-P já está em uso."


def test_atualizar_produto_preserva_genero_e_adiciona_variacao(client, admin):
    atual = client.get("/api/produtos/2").json()
    variacoes = [{"id": v["id"], "sku": v["sku"], "tamanho": v["tamanho"], "cor": v["cor"]} for v in atual["variacoes"]]
    variacoes.append({"sku": "CL-COX-BRA-P", "tamanho": "P", "cor": "Branco"})
    r = client.put("/api/produtos/2", headers=admin, json={
        "nome": "Camisa Oxford Slim", "categoria": "Camisaria", "precoBase": 399, "ativo": True, "variacoes": variacoes,
    })
    assert r.status_code == 200, r.text
    produto = r.json()
    assert produto["precoBase"] == 399
    assert produto["genero"] == "Masculino"
    assert len(produto["variacoes"]) == 4


# ---------- Estoque ----------

def test_registrar_movimentacao_atualiza_saldo(client, operador):
    item = client.get("/api/estoque/1", headers=operador).json()
    r = client.post("/api/movimentacoes", headers=operador, json={
        "estoqueId": 1, "tipo": "ENTRADA", "quantidade": 5, "origem": "NF 123", "usuarioId": 999,
    })
    assert r.status_code == 201, r.text
    mov = r.json()
    assert mov["saldoResultante"] == item["quantidade"] + 5
    assert mov["usuario"]["id"] == 6  # o autor vem do token, não do corpo
    assert client.get("/api/estoque/1", headers=operador).json()["quantidade"] == item["quantidade"] + 5


def test_movimentacao_nao_deixa_saldo_negativo(client, operador):
    item = client.get("/api/estoque/1", headers=operador).json()
    r = client.post("/api/movimentacoes", headers=operador, json={
        "estoqueId": 1, "tipo": "VENDA", "quantidade": -(item["quantidade"] + 1), "origem": "",
    })
    assert r.status_code == 422
    assert "Saldo insuficiente" in r.json()["detail"]


def test_posicao_em_data_bate_com_saldo_atual(client, admin):
    from datetime import date

    hoje = date.today().isoformat()
    posicao = client.get(f"/api/estoque/posicao?data={hoje}&lojaId=1", headers=admin).json()
    assert all(item["quantidadeNaData"] == item["quantidade"] for item in posicao["itens"])


# ---------- Transferências ----------

def test_fluxo_completo_de_transferencia(client, operador):
    origem = client.get("/api/estoque?lojaId=1&status=NORMAL", headers=operador).json()[0]
    destino = client.get(f"/api/estoque?lojaId=2&variacaoId={origem['variacaoId']}", headers=operador).json()[0]

    r = client.post("/api/transferencias", headers=operador, json={
        "variacaoId": origem["variacaoId"], "lojaOrigemId": 1, "lojaDestinoId": 2, "quantidade": 1, "observacao": "teste",
    })
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "SOLICITADA" and t["codigo"] == f"TRF-{t['id']:04d}"

    r = client.patch(f"/api/transferencias/{t['id']}", headers=operador, json={"status": "EM_TRANSITO"})
    assert r.json()["status"] == "EM_TRANSITO"
    assert client.get(f"/api/estoque/{origem['id']}", headers=operador).json()["quantidade"] == origem["quantidade"] - 1

    r = client.patch(f"/api/transferencias/{t['id']}", headers=operador, json={"status": "CONCLUIDA"})
    assert r.json()["status"] == "CONCLUIDA"
    assert client.get(f"/api/estoque/{destino['id']}", headers=operador).json()["quantidade"] == destino["quantidade"] + 1

    r = client.patch(f"/api/transferencias/{t['id']}", headers=operador, json={"status": "CANCELADA"})
    assert r.status_code == 409


def test_transferencia_valida_quantidade_disponivel(client, operador):
    origem = client.get("/api/estoque/1", headers=operador).json()
    r = client.post("/api/transferencias", headers=operador, json={
        "variacaoId": origem["variacaoId"], "lojaOrigemId": 1, "lojaDestinoId": 2, "quantidade": origem["quantidade"] + 1,
    })
    assert r.status_code == 422


# ---------- Atendimento ----------

def test_cliente_abre_e_responde_solicitacao(client, cliente, lojista):
    pedido = client.get("/api/clientes/101/pedidos", headers=cliente).json()[0]
    r = client.post("/api/atendimentos", headers=cliente, json={
        "clienteId": 101, "tipoSolicitacaoId": 1, "pedidoId": pedido["id"], "descricao": "Quero trocar o tamanho, por favor.",
    })
    assert r.status_code == 201, r.text
    atd = r.json()
    assert atd["status"] == "ABERTO" and atd["protocolo"] == f"ATD-{26000 + atd['id'] * 37:06d}"
    assert atd["mensagens"][0]["autorTipo"] == "CLIENTE"

    r = client.post(f"/api/atendimentos/{atd['id']}/mensagens", headers=lojista, json={"conteudo": "Separamos para você!"})
    corpo = r.json()
    assert corpo["status"] == "AGUARDANDO_CLIENTE" and corpo["responsavelId"] == 2

    r = client.post(f"/api/atendimentos/{atd['id']}/mensagens", headers=cliente, json={
        "conteudo": "Obrigada!", "autorId": 101, "autorTipo": "CLIENTE",
    })
    assert r.json()["status"] == "EM_ANDAMENTO"


def test_solicitacao_exige_pedido_quando_o_tipo_pede(client, cliente):
    r = client.post("/api/atendimentos", headers=cliente, json={"tipoSolicitacaoId": 1, "descricao": "Descrição longa o bastante"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Este tipo de solicitação exige o número do pedido."


def test_atualizar_atendimento_registra_eventos(client, admin):
    r = client.patch("/api/atendimentos/3", headers=admin, json={"responsavelId": 2, "status": "EM_ANDAMENTO"})
    assert r.status_code == 200
    eventos = [m["conteudo"] for m in r.json()["mensagens"] if m["autorTipo"] == "SISTEMA"]
    assert eventos[-2:] == ["Atendimento atribuído a Rafael Monteiro.", 'Status alterado para "em andamento".']

    r = client.patch("/api/atendimentos/3", headers=admin, json={"responsavelId": None})
    assert r.json()["responsavelId"] is None


def test_cliente_nao_ve_dados_de_outro_cliente(client, cliente):
    assert client.get("/api/clientes/102", headers=cliente).status_code == 404
    assert client.get("/api/clientes/102/pedidos", headers=cliente).status_code == 404
    assert client.get("/api/atendimentos/3", headers=cliente).status_code == 404  # é do cliente 102
    assert client.get("/api/clientes/101/atendimentos/3", headers=cliente).status_code == 404


def test_consulta_de_pedido_aceita_numero_sem_prefixo(client, cliente):
    numero = client.get("/api/clientes/101/pedidos", headers=cliente).json()[0]["numero"]
    r = client.get(f"/api/clientes/101/pedidos/{numero.replace('CL-', '')}", headers=cliente)
    assert r.status_code == 200 and r.json()["numero"] == numero
