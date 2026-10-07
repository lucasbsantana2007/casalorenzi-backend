"""Regras de negócio e permissões das rotas que alteram dados.

Os formatos de resposta seguem os mocks do frontend (src/services/mock).
"""

import pytest

# ---------- Autenticação e permissões ----------


def test_login_devolve_token_e_usuario(client):
    r = client.post("/api/auth/login", json={"email": " HELENA@casalorenzi.com.br ", "senha": "lorenzi2026"})
    assert r.status_code == 200
    assert r.json()["usuario"] == {
        "id": 1,
        "nome": "Helena Lorenzi",
        "email": "helena@casalorenzi.com.br",
        "papel": "ADMINISTRADOR",
        "lojaId": None,
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


def test_permissoes_por_papel(client, lojista, operador):
    assert client.get("/api/financeiro/resumo", headers=lojista).status_code == 403
    assert client.get("/api/transferencias", headers=lojista).status_code == 403
    assert client.get("/api/atendimentos", headers=operador).status_code == 403
    assert client.get("/api/clientes", headers=operador).status_code == 403
    assert client.post("/api/produtos", headers=operador, json={}).status_code == 403


def test_cliente_entra_no_mesmo_login_e_nao_acessa_o_painel(client, mariana):
    eu = client.get("/api/auth/me", headers=mariana).json()
    assert eu["papel"] == "CLIENTE" and eu["cpf"] == "15881399803"
    assert client.get("/api/dashboard/resumo", headers=mariana).status_code == 401
    assert client.get("/api/clientes", headers=mariana).status_code == 401
    assert client.get("/api/atendimentos", headers=mariana).status_code == 401


def test_lojista_ve_dashboard_so_da_propria_loja(client, lojista):
    r = client.get("/api/dashboard/resumo?lojaId=3", headers=lojista)
    assert r.status_code == 200
    assert [item["loja"]["id"] for item in r.json()["resumoPorLoja"]] == [1]


# ---------- Produtos ----------


def _novo_produto(**extra):
    return {
        "nome": "Camisa Teste",
        "categoria": "Camisaria",
        "precoBase": 199.9,
        "ativo": True,
        "genero": "Masculino",
        "variacoes": [{"sku": "cl-tst-azu-m", "tamanho": "M", "cor": "Azul", "precoCusto": 80}],
        **extra,
    }


def test_produto_novo_entra_na_vitrine_da_colecao_escolhida(client, admin):
    r = client.post("/api/produtos", headers=admin, json=_novo_produto(genero="Feminino", estacao="Verão"))
    assert r.status_code == 201, r.text
    vitrine = client.get("/api/produtos?ativo=true").json()
    novo = next(p for p in vitrine if p["id"] == r.json()["id"])
    assert (novo["genero"], novo["estacao"]) == ("Feminino", "Verão")


def test_estacao_padrao_e_atemporal(client, admin):
    r = client.post("/api/produtos", headers=admin, json=_novo_produto())
    assert r.status_code == 201 and r.json()["estacao"] == "Atemporal"


@pytest.mark.parametrize(
    ("alteracao", "trecho"),
    [
        ({"genero": None}, "Selecione a coleção do produto"),
        ({"genero": "Infantil"}, "Coleção inválida"),
        ({"estacao": "Primavera"}, "Estação inválida"),
    ],
)
def test_cadastro_exige_colecao_valida(client, admin, alteracao, trecho):
    r = client.post("/api/produtos", headers=admin, json=_novo_produto(**alteracao))
    assert r.status_code == 422 and trecho in r.json()["detail"]


def test_trocar_a_colecao_muda_a_vitrine_e_vai_para_o_log(client, admin):
    produto = client.get("/api/produtos/2", headers=admin).json()
    corpo = {
        "nome": produto["nome"],
        "categoria": produto["categoria"],
        "precoBase": produto["precoBase"],
        "ativo": True,
        "variacoes": [{c: v[c] for c in ("id", "sku", "tamanho", "cor", "precoCusto")} for v in produto["variacoes"]],
    }
    # Sem coleção no corpo (ou com null), mantém a atual
    assert client.put("/api/produtos/2", headers=admin, json={**corpo, "genero": None}).json()["genero"] == "Masculino"
    r = client.put("/api/produtos/2", headers=admin, json={**corpo, "genero": "Feminino", "estacao": "Inverno"})
    assert (r.json()["genero"], r.json()["estacao"]) == ("Feminino", "Inverno")
    registro = client.get("/api/admin/log?area=PRODUTOS", headers=admin).json()[0]
    assert {"campo": "Coleção", "de": "Masculino", "para": "Feminino"} in registro["alteracoes"]


def test_criar_produto_gera_estoque_zerado_nas_lojas(client, admin):
    r = client.post("/api/produtos", headers=admin, json=_novo_produto())
    assert r.status_code == 201, r.text
    produto = r.json()
    assert produto["variacoes"][0]["sku"] == "CL-TST-AZU-M"
    assert produto["estoqueTotal"] == 0
    estoques = client.get(f"/api/estoque?variacaoId={produto['variacoes'][0]['id']}", headers=admin).json()
    assert len(estoques) == len(client.get("/api/lojas").json())
    assert {e["status"] for e in estoques} == {"SEM_ESTOQUE"}


def test_criar_produto_valida_sku_duplicado(client, admin):
    r = client.post(
        "/api/produtos", headers=admin, json=_novo_produto(variacoes=[{"sku": "CL-CML-BRA-P", "tamanho": "P", "cor": "Branco"}])
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "O SKU CL-CML-BRA-P já está em uso."


def test_atualizar_produto_preserva_genero_e_adiciona_variacao(client, admin):
    atual = client.get("/api/produtos/2", headers=admin).json()
    campos = ("id", "sku", "tamanho", "cor", "precoCusto")
    variacoes = [{c: v[c] for c in campos} for v in atual["variacoes"]]
    variacoes.append({"sku": "CL-COX-BRA-P", "tamanho": "P", "cor": "Branco", "precoCusto": 150})
    r = client.put(
        "/api/produtos/2",
        headers=admin,
        json={
            "nome": "Camisa de Linho Positano",
            "categoria": "Camisaria",
            "precoBase": 399,
            "ativo": True,
            "variacoes": variacoes,
        },
    )
    assert r.status_code == 200, r.text
    produto = r.json()
    assert produto["precoBase"] == 399
    assert produto["genero"] == "Masculino"
    assert len(produto["variacoes"]) == 4


# ---------- Estoque ----------


def test_registrar_movimentacao_atualiza_saldo(client, operador):
    item = client.get("/api/estoque/1", headers=operador).json()
    r = client.post(
        "/api/movimentacoes",
        headers=operador,
        json={
            "estoqueId": 1,
            "tipo": "ENTRADA",
            "quantidade": 5,
            "origem": "NF 123",
            "usuarioId": 999,
        },
    )
    assert r.status_code == 201, r.text
    mov = r.json()
    assert mov["saldoResultante"] == item["quantidade"] + 5
    assert mov["usuario"]["id"] == 6  # o autor vem do token, não do corpo
    assert client.get("/api/estoque/1", headers=operador).json()["quantidade"] == item["quantidade"] + 5


def test_movimentacao_nao_deixa_saldo_negativo(client, operador):
    item = client.get("/api/estoque/1", headers=operador).json()
    r = client.post(
        "/api/movimentacoes",
        headers=operador,
        json={
            "estoqueId": 1,
            "tipo": "VENDA",
            "quantidade": -(item["quantidade"] + 1),
            "origem": "",
        },
    )
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

    r = client.post(
        "/api/transferencias",
        headers=operador,
        json={
            "variacaoId": origem["variacaoId"],
            "lojaOrigemId": 1,
            "lojaDestinoId": 2,
            "quantidade": 1,
            "observacao": "teste",
        },
    )
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
    r = client.post(
        "/api/transferencias",
        headers=operador,
        json={
            "variacaoId": origem["variacaoId"],
            "lojaOrigemId": 1,
            "lojaDestinoId": 2,
            "quantidade": origem["quantidade"] + 1,
        },
    )
    assert r.status_code == 422


# ---------- Atendimento ----------


def test_equipe_abre_solicitacao_para_cliente_e_responde(client, admin, lojista):
    pedido = client.get("/api/clientes/101/pedidos", headers=admin).json()[0]
    r = client.post(
        "/api/atendimentos",
        headers=admin,
        json={
            "clienteId": 101,
            "tipoSolicitacaoId": 1,
            "pedidoId": pedido["id"],
            "descricao": "Quero trocar o tamanho, por favor.",
        },
    )
    assert r.status_code == 201, r.text
    atd = r.json()
    assert atd["status"] == "ABERTO" and atd["protocolo"] == f"ATD-{26000 + atd['id'] * 37:06d}"
    assert atd["cliente"]["id"] == 101 and atd["clienteId"] == 101
    # A descrição é a fala do cliente (sem autor da equipe); quem abriu fica registrado pelo sistema
    assert atd["mensagens"][0]["autorTipo"] == "CLIENTE" and atd["mensagens"][0]["autorId"] is None
    assert atd["mensagens"][1]["conteudo"] == "Aberto por Helena Lorenzi em nome do cliente."

    r = client.post(
        f"/api/atendimentos/{atd['id']}/mensagens",
        headers=lojista,
        json={
            "conteudo": "Separamos para você!",
            "autorId": 101,
            "autorTipo": "CLIENTE",
        },
    )
    corpo = r.json()
    assert corpo["status"] == "AGUARDANDO_CLIENTE" and corpo["responsavelId"] == 2
    assert corpo["mensagens"][-1]["autorTipo"] == "ATENDENTE"  # autor e tipo vêm do token


def test_solicitacao_exige_cliente_valido(client, admin):
    r = client.post(
        "/api/atendimentos",
        headers=admin,
        json={"clienteId": 9999, "tipoSolicitacaoId": 3, "descricao": "Descrição longa o bastante"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Informe um cliente válido."


def test_solicitacao_exige_pedido_quando_o_tipo_pede(client, admin):
    r = client.post(
        "/api/atendimentos",
        headers=admin,
        json={"clienteId": 101, "tipoSolicitacaoId": 1, "descricao": "Descrição longa o bastante"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Este tipo de solicitação exige o número do pedido."


def test_atualizar_atendimento_registra_eventos(client, admin):
    r = client.patch("/api/atendimentos/3", headers=admin, json={"responsavelId": 2, "status": "EM_ANDAMENTO"})
    assert r.status_code == 200
    eventos = [m["conteudo"] for m in r.json()["mensagens"] if m["autorTipo"] == "SISTEMA"]
    assert eventos[-2:] == ["Atendimento atribuído a Rafael Monteiro.", 'Status alterado para "em andamento".']

    r = client.patch("/api/atendimentos/3", headers=admin, json={"responsavelId": None})
    assert r.json()["responsavelId"] is None


def test_painel_consulta_cliente(client, admin):
    r = client.get("/api/clientes?busca=mariana", headers=admin)
    assert [c["id"] for c in r.json()] == [101]
    perfil = client.get("/api/clientes/101", headers=admin).json()
    assert perfil["email"] == "mariana.costa@gmail.com" and perfil["temPin"] is True
    assert "pinHash" not in perfil and "pin_hash" not in perfil
    assert perfil["totalPedidos"] == len(client.get("/api/clientes/101/pedidos", headers=admin).json())
    assert client.get("/api/clientes/9999", headers=admin).status_code == 404
