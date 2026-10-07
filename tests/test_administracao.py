"""Central administrativa (funcionários, lojas, log), frete configurável e custo/foto dos produtos."""

import base64

import pytest

from src.use_cases import administracao

SENHA = "lorenzi2026"
CEP_SP = "01310-100"
PNG_1X1 = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4d30000000049454e44ae426082"
    )
).decode()


@pytest.fixture
def links_na_resposta(monkeypatch):
    monkeypatch.setattr(administracao, "LINK_SENHA_NA_RESPOSTA", True)


def _login(client, email, senha=SENHA):
    return client.post("/api/auth/login", json={"email": email, "senha": senha})


def _log(client, admin, area):
    return client.get(f"/api/admin/log?area={area}", headers=admin).json()


# ---------- Permissões ----------


@pytest.mark.parametrize("rota", ["/api/admin/funcionarios", "/api/admin/lojas", "/api/admin/log", "/api/frete/config"])
def test_central_administrativa_e_so_do_administrador(client, admin, lojista, operador, mariana, rota):
    assert client.get(rota).status_code == 401
    assert client.get(rota, headers=mariana).status_code == 401
    assert client.get(rota, headers=lojista).status_code == 403
    assert client.get(rota, headers=operador).status_code == 403
    assert client.get(rota, headers=admin).status_code == 200


# ---------- Funcionários ----------


def test_funcionario_novo_entra_so_depois_de_criar_a_senha_pelo_convite(client, admin, links_na_resposta):
    r = client.post(
        "/api/admin/funcionarios",
        headers=admin,
        json={"nome": "Paula Vieira", "email": "Paula.Vieira@casalorenzi.com.br", "papel": "LOJISTA", "lojaId": 2},
    )
    assert r.status_code == 201, r.text
    funcionario, link = r.json()["funcionario"], r.json()["linkDemo"]
    assert funcionario["email"] == "paula.vieira@casalorenzi.com.br"
    assert funcionario["loja"] == {"id": 2, "nome": "Lago Norte"}
    assert funcionario["convitePendente"] and funcionario["ativo"]
    assert link.startswith("/login/nova-senha?token=")

    antes = _login(client, "paula.vieira@casalorenzi.com.br", "qualquer-coisa")
    assert antes.status_code == 401 and "convite" in antes.json()["detail"]

    token = link.split("token=")[1]
    assert (
        client.post(
            "/api/auth/redefinir-senha", json={"token": token, "senha": "senha-nova", "senhaConfirmacao": "senha-nova"}
        ).status_code
        == 200
    )
    depois = _login(client, "paula.vieira@casalorenzi.com.br", "senha-nova")
    assert depois.status_code == 200 and depois.json()["usuario"]["papel"] == "LOJISTA"

    lista = client.get("/api/admin/funcionarios?busca=paula", headers=admin).json()
    assert [f["convitePendente"] for f in lista] == [False]
    # Já criou a senha: não há convite para reenviar
    assert client.post(f"/api/admin/funcionarios/{funcionario['id']}/convite", headers=admin).status_code == 422

    registro = _log(client, admin, "FUNCIONARIOS")[0]
    assert registro["descricao"] == "Cadastrou Paula Vieira como Lojista · Lago Norte"
    assert registro["usuario"]["nome"] == "Helena Lorenzi"


def test_link_do_convite_nao_vem_na_resposta_com_a_opcao_desligada(client, admin, monkeypatch):
    monkeypatch.setattr(administracao, "LINK_SENHA_NA_RESPOSTA", False)
    r = client.post(
        "/api/admin/funcionarios",
        headers=admin,
        json={"nome": "Ana", "email": "ana@casalorenzi.com.br", "papel": "ADMINISTRADOR"},
    )
    assert r.status_code == 201 and r.json()["linkDemo"] is None
    assert r.json()["funcionario"]["lojaId"] is None


@pytest.mark.parametrize(
    ("dados", "status", "trecho"),
    [
        ({"nome": ""}, 422, "Informe o nome"),
        ({"email": "sem-arroba"}, 422, "e-mail válido"),
        ({"email": "rafael.monteiro@casalorenzi.com.br"}, 409, "já está em uso"),
        ({"email": "mariana.costa@gmail.com"}, 409, "já está em uso"),  # e-mail de cliente
        ({"papel": "GERENTE"}, 422, "Selecione o cargo"),
        ({"lojaId": None}, 422, "Selecione a loja"),
        ({"lojaId": 99}, 422, "Selecione a loja"),
    ],
)
def test_funcionario_valida_os_dados(client, admin, dados, status, trecho):
    corpo = {"nome": "Teste", "email": "teste@casalorenzi.com.br", "papel": "OPERADOR", "lojaId": 1, **dados}
    r = client.post("/api/admin/funcionarios", headers=admin, json=corpo)
    assert r.status_code == status
    assert trecho in r.json()["detail"]


def test_editar_funcionario_registra_o_que_mudou(client, admin):
    corpo = {"nome": "Rafael Monteiro", "email": "rafael.monteiro@casalorenzi.com.br", "papel": "OPERADOR", "lojaId": 3}
    r = client.put("/api/admin/funcionarios/2", headers=admin, json=corpo)
    assert r.status_code == 200 and r.json()["papel"] == "OPERADOR"
    registro = _log(client, admin, "FUNCIONARIOS")[0]
    assert registro["descricao"] == "Editou o cadastro de Rafael Monteiro"
    assert registro["alteracoes"] == [
        {"campo": "Cargo", "de": "Lojista", "para": "Operador"},
        {"campo": "Loja", "de": "Oscar Freire", "para": "Leblon"},
    ]


def test_desativar_funcionario_bloqueia_o_acesso(client, admin, lojista):
    r = client.patch("/api/admin/funcionarios/2/status", headers=admin, json={"ativo": False})
    assert r.status_code == 200 and r.json()["ativo"] is False
    # A sessão aberta deixa de valer
    assert client.get("/api/dashboard/resumo", headers=lojista).status_code == 401
    # Senha errada: a mesma resposta de sempre; senha certa: 403 de conta desativada
    assert _login(client, "rafael.monteiro@casalorenzi.com.br", "errada").status_code == 401
    certa = _login(client, "rafael.monteiro@casalorenzi.com.br")
    assert certa.status_code == 403 and "desativada" in certa.json()["detail"]
    # Desativado não recebe link de troca de senha
    assert client.post("/api/auth/esqueci-senha", json={"email": "rafael.monteiro@casalorenzi.com.br"}).json()["linkDemo"] is None

    assert client.patch("/api/admin/funcionarios/2/status", headers=admin, json={"ativo": True}).json()["ativo"] is True
    assert _login(client, "rafael.monteiro@casalorenzi.com.br").status_code == 200
    assert [r["acao"] for r in _log(client, admin, "FUNCIONARIOS")[:2]] == ["REATIVOU", "DESATIVOU"]


def test_sempre_fica_um_administrador_ativo(client, admin):
    assert client.patch("/api/admin/funcionarios/1/status", headers=admin, json={"ativo": False}).json()["detail"] == (
        "Você não pode desativar a sua própria conta."
    )
    rebaixar = {"nome": "Helena Lorenzi", "email": "helena@casalorenzi.com.br", "papel": "LOJISTA", "lojaId": 1}
    r = client.put("/api/admin/funcionarios/1", headers=admin, json=rebaixar)
    assert r.status_code == 422 and "pelo menos um Administrador" in r.json()["detail"]


# ---------- Lojas ----------


def test_lojas_publicas_trazem_os_detalhes_da_pagina_lojas(client):
    loja = next(lj for lj in client.get("/api/lojas").json() if lj["id"] == 2)
    assert loja["nome"] == "Lago Norte" and loja["ativa"] is True
    assert loja["endereco"].startswith("Shopping Iguatemi") and loja["telefone"] and loja["horarios"]


def test_loja_nova_nasce_com_estoque_zerado(client, admin):
    dados = {
        "nome": "Moinhos",
        "cidade": "Porto Alegre",
        "uf": "RS",
        "endereco": "Rua Padre Chagas, 300",
        "telefone": "+55 51 3000-0000",
        "horarios": ["Segunda a sábado: 10:00–20:00", "  "],
        "ativa": True,
    }
    r = client.post("/api/admin/lojas", headers=admin, json=dados)
    assert r.status_code == 201, r.text
    loja = r.json()
    assert loja["horarios"] == ["Segunda a sábado: 10:00–20:00"]
    assert loja["funcionariosAtivos"] == 0 and loja["pecasEmEstoque"] == 0
    estoque = client.get(f"/api/estoque?lojaId={loja['id']}", headers=admin).json()
    total_variacoes = sum(len(p["variacoes"]) for p in client.get("/api/produtos").json())
    assert len(estoque) == total_variacoes and all(e["quantidade"] == 0 for e in estoque)

    assert client.post("/api/admin/lojas", headers=admin, json={**dados, "nome": "MOINHOS"}).status_code == 409
    assert client.post("/api/admin/lojas", headers=admin, json={**dados, "nome": "Outra", "uf": "XX"}).status_code == 422
    assert _log(client, admin, "LOJAS")[0]["descricao"] == "Cadastrou a loja Moinhos (Porto Alegre, RS)"


def test_loja_desativada_sai_da_expedicao(client, admin, mariana):
    lojas = client.get("/api/admin/lojas", headers=admin).json()
    assert lojas[0]["pecasEmEstoque"] > 0 and lojas[0]["funcionariosAtivos"] > 0
    # Desativa todas menos a Belvedere: o pedido só pode sair de lá
    for loja in lojas:
        if loja["id"] != 5:
            r = client.put(f"/api/admin/lojas/{loja['id']}", headers=admin, json={**loja, "ativa": False})
            assert r.status_code == 200 and r.json()["ativa"] is False
    assert _log(client, admin, "LOJAS")[0]["descricao"].startswith("Editou e desativou a loja")

    variacao = next(v for p in client.get("/api/produtos?ativo=true").json() for v in p["variacoes"] if v["estoqueTotal"])
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
        "itens": [{"variacaoId": variacao["id"], "quantidade": 1}],
    }
    numero = client.post("/api/checkout", headers=mariana, json=compra).json()["numero"]
    pedido = client.get(f"/api/pedidos?busca={numero}", headers=admin).json()[0]
    assert pedido["loja"]["id"] == 5
    # Loja desativada também não doa peças por transferência automática
    assert pedido["transferencias"] == []
    # Também não dá para mandar a expedição para uma loja desativada
    assert client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"lojaId": 1}).status_code == 422


# ---------- Frete ----------


def _compra_sp(client, headers):
    variacao = next(v for p in client.get("/api/produtos?ativo=true").json() for v in p["variacoes"] if v["estoqueTotal"])
    return {
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
        "itens": [{"variacaoId": variacao["id"], "quantidade": 1}],
    }


def test_condicoes_publicas_nao_mostram_o_custo(client, admin):
    publico = client.get("/api/frete/condicoes").json()
    assert publico["gratisMinimo"] == 1000 and publico["expressoAtivo"] is True
    sp = publico["regioes"][0]
    assert sp == {
        "regiao": "SP",
        "nome": "Estado de São Paulo",
        "padrao": {"valor": 19.9, "prazoDias": 3},
        "expresso": {"valor": 39.9, "prazoDias": 1},
    }
    completo = client.get("/api/frete/config", headers=admin).json()
    assert completo["regioes"][0]["padrao"] == {"valor": 19.9, "prazoDias": 3, "custo": 16.5}


def test_frete_configurado_vale_no_checkout_e_o_custo_fica_no_pedido(client, admin, lojista, mariana):
    config = client.get("/api/frete/config", headers=admin).json()
    config["gratisMinimo"] = 99999
    config["regioes"][0]["padrao"] = {"valor": 25, "custo": 30, "prazoDias": 4}
    config["expressoAtivo"] = False
    r = client.put("/api/frete/config", headers=admin, json=config)
    assert r.status_code == 200, r.text

    registro = _log(client, admin, "FRETE")[0]
    assert registro["descricao"] == "Alterou a configuração de frete (5 valores)"
    assert {"campo": "Estado de São Paulo · Padrão · valor", "de": "R$ 19,90", "para": "R$ 25,00"} in registro["alteracoes"]

    simulacao = client.post("/api/frete/simulacao", headers=admin, json={"cep": CEP_SP, "subtotal": 500}).json()
    assert simulacao == [{"tipo": "PADRAO", "label": "Padrão", "valor": 25.0, "custo": 30.0, "prazoDias": 4, "resultado": -5.0}]

    compra = _compra_sp(client, mariana)
    pedido = client.post("/api/checkout", headers=mariana, json=compra).json()
    assert pedido["frete"] == {"tipo": "PADRAO", "label": "Padrão", "valor": 25.0, "prazoDias": 4}  # cliente não vê custo
    expresso = client.post("/api/checkout", headers=mariana, json={**compra, "freteTipo": "EXPRESSO"})
    assert expresso.status_code == 422  # Expresso desligado

    painel = client.get(f"/api/pedidos?busca={pedido['numero']}", headers=admin).json()[0]
    assert painel["frete"]["custo"] == 30.0
    if painel["lojaId"] != 1:  # o lojista de demonstração é da loja 1 e só vê os pedidos dela
        client.patch(f"/api/pedidos/{painel['id']}", headers=admin, json={"lojaId": 1})
    da_loja = client.get(f"/api/pedidos/{painel['id']}", headers=lojista).json()
    assert "custo" not in da_loja["frete"]


@pytest.mark.parametrize(
    ("alterar", "trecho"),
    [
        (lambda c: c.update(gratisMinimo=-1), "valor mínimo válido"),
        (lambda c: c["regioes"][1]["padrao"].update(custo="abc"), "Rio de Janeiro, Espírito Santo e Minas Gerais · Padrão"),
        (lambda c: c["regioes"][2]["expresso"].update(prazoDias=1.5), "prazo deve ser um número inteiro"),
        (lambda c: c["regioes"][0].update(regiao="LUA"), "Região de frete desconhecida"),
    ],
)
def test_configuracao_de_frete_valida_tudo_antes_de_gravar(client, admin, alterar, trecho):
    config = client.get("/api/frete/config", headers=admin).json()
    alterar(config)
    r = client.put("/api/frete/config", headers=admin, json=config)
    assert r.status_code == 422 and trecho in r.json()["detail"]
    assert client.get("/api/frete/condicoes").json()["gratisMinimo"] == 1000
    assert _log(client, admin, "FRETE") == []


# ---------- Produtos: custo e foto ----------


def test_preco_de_custo_so_aparece_para_o_administrador(client, admin, lojista):
    publico = client.get("/api/produtos/2").json()["variacoes"][0]
    assert "precoCusto" not in publico
    assert "precoCusto" not in client.get("/api/produtos/2", headers=lojista).json()["variacoes"][0]
    produto = client.get("/api/produtos/2", headers=admin).json()
    assert produto["variacoes"][0]["precoCusto"] == round(produto["precoBase"] * 0.4, 2)


def test_foto_do_produto_troca_e_volta_para_a_ilustracao(client, admin):
    produto = client.get("/api/produtos/2", headers=admin).json()
    assert produto["imagemUrl"] is None
    corpo = {
        "nome": produto["nome"],
        "categoria": produto["categoria"],
        "precoBase": produto["precoBase"],
        "ativo": True,
        "variacoes": [{c: v[c] for c in ("id", "sku", "tamanho", "cor", "precoCusto")} for v in produto["variacoes"]],
    }
    r = client.put(
        "/api/produtos/2",
        headers=admin,
        json={**corpo, "imagem": {"nome": "camisa.png", "tipo": "image/png", "conteudoBase64": PNG_1X1}},
    )
    assert r.status_code == 200, r.text
    url = r.json()["imagemUrl"]
    assert url.startswith("http://testserver/api/produtos/2/imagem?v=")

    foto = client.get(url.removeprefix("http://testserver"))
    assert foto.status_code == 200 and foto.headers["content-type"] == "image/png"
    assert foto.content == base64.b64decode(PNG_1X1)
    # A vitrine e os pedidos recebem o mesmo link
    assert next(p for p in client.get("/api/produtos").json() if p["id"] == 2)["imagemUrl"] == url

    registro = _log(client, admin, "PRODUTOS")[0]
    assert registro["alteracoes"] == [{"campo": "Foto", "de": "Ilustração", "para": "camisa.png"}]

    ruim = client.put(
        "/api/produtos/2",
        headers=admin,
        json={**corpo, "imagem": {"nome": "x.png", "tipo": "image/png", "conteudoBase64": "aGVsbG8="}},
    )
    assert ruim.status_code == 422

    sem_foto = client.put("/api/produtos/2", headers=admin, json={**corpo, "removerImagem": True})
    assert sem_foto.json()["imagemUrl"] is None
    assert client.get("/api/produtos/2/imagem").status_code == 404


def test_mudanca_de_preco_e_custo_vai_para_o_log(client, admin):
    produto = client.get("/api/produtos/2", headers=admin).json()
    variacoes = [{c: v[c] for c in ("id", "sku", "tamanho", "cor", "precoCusto")} for v in produto["variacoes"]]
    variacoes[0]["precoCusto"] = 123.45
    corpo = {"nome": produto["nome"], "categoria": produto["categoria"], "precoBase": 999, "ativo": True, "variacoes": variacoes}
    assert client.put("/api/produtos/2", headers=admin, json=corpo).status_code == 200
    registro = _log(client, admin, "PRODUTOS")[0]
    assert registro["descricao"] == f"Editou o produto {produto['nome']}"
    campos = [a["campo"] for a in registro["alteracoes"]]
    assert campos == ["Preço de venda", f"Custo {variacoes[0]['sku']}"]


# ---------- Log ----------


def test_log_registra_pedidos_transferencias_e_estoque(client, admin, mariana):
    numero = client.post("/api/checkout", headers=mariana, json=_compra_sp(client, mariana)).json()["numero"]
    pedido = client.get(f"/api/pedidos?busca={numero}", headers=admin).json()[0]
    assert client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"status": "CANCELADO"}).status_code == 200
    assert _log(client, admin, "PEDIDOS")[0]["descricao"] == f"Cancelou o pedido {numero} e estornou o pagamento"

    estoque = client.get("/api/estoque?lojaId=1", headers=admin).json()[0]
    mov = {"estoqueId": estoque["id"], "tipo": "ENTRADA", "quantidade": 3, "origem": "Reposição"}
    assert client.post("/api/movimentacoes", headers=admin, json=mov).status_code == 201
    assert _log(client, admin, "ESTOQUE")[0]["descricao"].startswith("Registrou +3 un. (entrada)")

    busca = client.get("/api/admin/log?busca=estornou", headers=admin).json()
    assert [r["area"] for r in busca] == ["PEDIDOS"]
    assert client.get("/api/admin/log?usuarioId=2", headers=admin).json() == []
    assert client.get("/api/admin/log?area=NADA", headers=admin).status_code == 422
