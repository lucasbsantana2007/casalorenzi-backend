"""Servidor MCP do copiloto (decisão 106): tokens pessoais, o protocolo nas duas gerações (2026-07-28 e as de 2025),
as mesmas permissões do painel por papel e marca, só ferramentas da equipe e a auditoria de cada chamada."""

import base64
import json
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from src import models as m
from src.database.connection import SessionLocal
from src.entities import assistente as regra
from src.use_cases.assistente import ferramentas_cliente, ferramentas_gerenciais
from src.utils.datas import agora
from tests.conftest import _entrar

MODERNA = "2026-07-28"
LEGADA = "2025-06-18"
URL = "/api/conector-mcp"


@pytest.fixture
def paula(client):
    return _entrar(client, "paula.ferraz@vulto.com.br")  # Administradora só da Vulto


@pytest.fixture
def outro_do_grupo(client):
    """Um segundo Administrador do grupo (no seed, só a Helena é): o Otávio passa a ver as duas marcas."""
    with SessionLocal() as db:
        db.execute(text("UPDATE usuarios SET marca = 'GRUPO' WHERE email = 'otavio.vasconcelos@casalorenzi.com.br'"))
        db.commit()
    return _entrar(client, "otavio.vasconcelos@casalorenzi.com.br")


def criar_token(client, headers, nome="Claude Code do notebook") -> str:
    resposta = client.post("/api/mcp/tokens", json={"nome": nome}, headers=headers)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["token"]


def legado(client, token, metodo, params=None, id_=1, versao=LEGADA, **extra):
    """Requisição de um cliente MCP de 2025: versão no cabeçalho, sem _meta."""
    corpo = {"jsonrpc": "2.0", "id": id_, "method": metodo}
    if params is not None:
        corpo["params"] = params
    cabecalhos = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    if versao:
        cabecalhos["MCP-Protocol-Version"] = versao
    cabecalhos.update(extra)
    return client.post(URL, json=corpo, headers=cabecalhos)


def moderno(client, token, metodo, params=None, id_=1, versao=MODERNA, cabecalhos=None, meta=None):
    """Requisição de um cliente MCP 2026-07-28: versão e capacidades em _meta, espelhadas nos cabeçalhos."""
    params = dict(params or {})
    params["_meta"] = meta or {
        "io.modelcontextprotocol/protocolVersion": versao,
        "io.modelcontextprotocol/clientInfo": {"name": "teste-moderno", "version": "1.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    enviados = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": versao,
        "Mcp-Method": metodo,
    }
    if metodo == "tools/call":
        enviados["Mcp-Name"] = params["name"]
    enviados.update(cabecalhos or {})
    enviados = {k: v for k, v in enviados.items() if v is not None}
    return client.post(URL, json={"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params}, headers=enviados)


def chamar(client, token, nome, argumentos=None):
    resposta = legado(client, token, "tools/call", {"name": nome, "arguments": argumentos or {}})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()["result"]


def nomes(client, token) -> list[str]:
    return [f["name"] for f in legado(client, token, "tools/list").json()["result"]["tools"]]


def chamadas_mcp() -> list[m.ChamadaMcp]:
    with SessionLocal() as db:
        return list(db.scalars(select(m.ChamadaMcp).order_by(m.ChamadaMcp.id)))


# ---------- Tokens ----------


def test_token_aparece_uma_vez_e_o_banco_guarda_so_o_hash(client, admin):
    texto = criar_token(client, admin)
    assert texto.startswith("clmcp_") and len(texto) > 40
    lista = client.get("/api/mcp/tokens", headers=admin).json()
    assert len(lista) == 1 and lista[0]["situacao"] == "ATIVO" and lista[0]["prefixo"] == texto[:12]
    assert "token" not in lista[0] and texto not in json.dumps(lista)
    with SessionLocal() as db:
        salvo = db.scalar(select(m.TokenMcp))
        assert salvo.hash != texto and texto not in (salvo.hash, salvo.prefixo)
        assert salvo.expira_em - salvo.criado_em == timedelta(days=90)


def test_limite_de_tokens_ativos_e_revogacao(client, admin):
    criados = [client.post("/api/mcp/tokens", json={"nome": f"App {i}"}, headers=admin) for i in range(5)]
    assert all(r.status_code == 201 for r in criados)
    sexto = client.post("/api/mcp/tokens", json={"nome": "Sexto"}, headers=admin)
    assert sexto.status_code == 409 and "Revogue" in sexto.json()["detail"]
    primeiro = criados[0].json()
    revogado = client.delete(f"/api/mcp/tokens/{primeiro['id']}", headers=admin)
    assert revogado.status_code == 200 and revogado.json()["situacao"] == "REVOGADO"
    assert legado(client, primeiro["token"], "tools/list").status_code == 401
    assert client.post("/api/mcp/tokens", json={"nome": "Sexto"}, headers=admin).status_code == 201


def test_nome_em_branco_e_token_de_outra_pessoa(client, admin, outro_do_grupo):
    assert client.post("/api/mcp/tokens", json={"nome": "   "}, headers=admin).status_code == 422
    meu = client.post("/api/mcp/tokens", json={"nome": "Meu"}, headers=admin).json()
    assert client.delete(f"/api/mcp/tokens/{meu['id']}", headers=outro_do_grupo).status_code == 404
    assert client.get("/api/mcp/tokens", headers=outro_do_grupo).json() == []
    assert legado(client, meu["token"], "tools/list").status_code == 200


def test_cliente_nao_cria_token(client, mariana):
    assert client.post("/api/mcp/tokens", json={"nome": "x"}, headers=mariana).status_code == 401
    assert client.get("/api/mcp/tokens").status_code == 401


def test_token_vencido_ou_de_conta_desativada_para_de_valer(client, admin, outro_do_grupo):
    vencido = criar_token(client, admin)
    desativado = criar_token(client, outro_do_grupo)
    with SessionLocal() as db:
        db.execute(text("UPDATE tokens_mcp SET expira_em = now() - interval '1 minute' WHERE prefixo = :p"), {"p": vencido[:12]})
        db.execute(text("UPDATE usuarios SET ativo = false WHERE email = 'otavio.vasconcelos@casalorenzi.com.br'"))
        db.commit()
    for token in (vencido, desativado):
        resposta = legado(client, token, "tools/list")
        assert resposta.status_code == 401 and resposta.headers["www-authenticate"].startswith("Bearer")
    assert client.get("/api/mcp/tokens", headers=admin).json()[0]["situacao"] == "VENCIDO"


def test_sem_token_ou_token_falso(client):
    sem = client.post(URL, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert sem.status_code == 401 and "Inteligência > Conectar ao Claude" in sem.json()["error"]["message"]
    assert legado(client, "clmcp_inventado", "tools/list").status_code == 401
    assert legado(client, "token-do-painel", "tools/list").status_code == 401


def test_login_do_painel_nao_abre_o_mcp(client, admin):
    resposta = client.post(URL, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=admin)
    assert resposta.status_code == 401


# ---------- Protocolo de 2025 (initialize) ----------


def test_initialize_e_notificacao(client, admin):
    token = criar_token(client, admin)
    resposta = legado(
        client,
        token,
        "initialize",
        {"protocolVersion": LEGADA, "capabilities": {}, "clientInfo": {"name": "teste", "version": "1"}},
        versao=None,
    )
    resultado = resposta.json()["result"]
    assert resposta.status_code == 200 and resposta.headers["content-type"].startswith("application/json")
    assert resultado["protocolVersion"] == LEGADA and resultado["capabilities"] == {"tools": {"listChanged": False}}
    assert resultado["serverInfo"]["name"] == "casa-lorenzi-copiloto" and "ver_contexto" in resultado["instructions"]
    assert "resultType" not in resultado  # campo só da versão nova
    assert "mcp-session-id" not in resposta.headers
    # Em pedaços, sem Content-Length: antivírus que inspecionam MCP corrompem as respostas com tamanho fixo
    assert "content-length" not in resposta.headers
    notificacao = client.post(
        URL,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": f"Bearer {token}", "MCP-Protocol-Version": LEGADA},
    )
    assert notificacao.status_code == 202 and notificacao.content == b""


def test_initialize_com_versao_desconhecida_responde_a_mais_nova_de_2025(client, admin):
    token = criar_token(client, admin)
    resposta = legado(client, token, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}}, versao=None)
    assert resposta.json()["result"]["protocolVersion"] == "2025-11-25"


def test_sem_cabecalho_de_versao_vale_2025_03_26_e_versao_desconhecida_e_recusada(client, admin):
    token = criar_token(client, admin)
    assert legado(client, token, "ping", versao=None).json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
    recusada = legado(client, token, "ping", versao="1999-01-01")
    assert recusada.status_code == 400 and recusada.json()["error"]["code"] == -32022
    assert MODERNA in recusada.json()["error"]["data"]["supported"]


def test_metodo_desconhecido_e_ferramenta_desconhecida(client, admin):
    token = criar_token(client, admin)
    metodo = legado(client, token, "resources/list")
    assert metodo.status_code == 200 and metodo.json()["error"]["code"] == -32601
    ferramenta = legado(client, token, "tools/call", {"name": "apagar_tudo", "arguments": {}})
    assert ferramenta.json()["error"]["code"] == -32602 and "apagar_tudo" in ferramenta.json()["error"]["message"]


def test_mensagens_mal_formadas(client, admin):
    token = criar_token(client, admin)
    cabecalhos = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    quebrado = client.post(URL, content=b"{nao e json", headers=cabecalhos)
    assert quebrado.status_code == 400 and quebrado.json()["error"]["code"] == -32700
    lote = client.post(URL, json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}], headers=cabecalhos)
    assert lote.status_code == 400 and lote.json()["error"]["code"] == -32600
    sem_versao = client.post(URL, json={"id": 1, "method": "ping"}, headers=cabecalhos)
    assert sem_versao.status_code == 400 and sem_versao.json()["error"]["code"] == -32600
    id_nulo = client.post(URL, json={"jsonrpc": "2.0", "id": None, "method": "ping"}, headers=cabecalhos)
    assert id_nulo.status_code == 400
    grande = client.post(URL, content=b" " * (65 * 1024), headers=cabecalhos)
    assert grande.status_code == 413


def test_json_que_o_python_aceita_mas_nao_e_json(client, admin):
    """NaN, Infinity e aninhamento sem fim: 400 de JSON inválido, sem chegar ao banco (antes davam 500)."""
    token = criar_token(client, admin)
    cabecalhos = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    corpos = [
        b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ver_contexto","arguments":{"x":NaN}}}',
        b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":-Infinity}}',
        b"[" * 20000 + b"]" * 20000,
    ]
    for corpo in corpos:
        resposta = client.post(URL, content=corpo, headers=cabecalhos)
        assert resposta.status_code == 400 and resposta.json()["error"]["code"] == -32700
    assert chamadas_mcp() == []


def test_argumentos_ausentes_ou_com_caractere_nulo_vao_para_a_auditoria(client, admin):
    token = criar_token(client, admin)
    sem_argumentos = legado(client, token, "tools/call", {"name": "ver_contexto"})
    assert sem_argumentos.json()["result"]["isError"] is False
    nulo = chamar(client, token, "consultar_faturamento", {"periodo": "mes\u0000atual"})
    assert nulo["isError"] is True and "PARAMETROS_INVALIDOS" in nulo["content"][0]["text"]
    assert [c.argumentos for c in chamadas_mcp()] == [{}, {"periodo": "mes\u0000atual"}]


def test_falha_inesperada_vira_erro_json_rpc(client, admin, monkeypatch):
    token = criar_token(client, admin)

    def quebra(*_, **__):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr("src.use_cases.assistente.servidor_mcp.processar", quebra)
    resposta = legado(client, token, "tools/list", id_=7)
    assert resposta.status_code == 500 and resposta.json()["error"]["code"] == -32603 and resposta.json()["id"] == 7
    assert "banco caiu" not in resposta.text


def test_get_e_delete_respondem_405(client, admin):
    token = criar_token(client, admin)
    for metodo in ("GET", "DELETE"):
        resposta = client.request(metodo, URL, headers={"Authorization": f"Bearer {token}"})
        assert resposta.status_code == 405 and resposta.headers["allow"] == "POST"


def test_origem_de_outro_site_e_recusada(client, admin):
    token = criar_token(client, admin)
    assert legado(client, token, "ping", Origin="https://site-malicioso.example").status_code == 403
    assert legado(client, token, "ping", Origin="http://localhost:5173").status_code == 200


# ---------- Protocolo 2026-07-28 (sem initialize) ----------


def test_discover_moderno(client, admin):
    token = criar_token(client, admin)
    resposta = moderno(client, token, "server/discover")
    resultado = resposta.json()["result"]
    assert resposta.status_code == 200 and resultado["resultType"] == "complete"
    assert resultado["supportedVersions"][0] == MODERNA and LEGADA in resultado["supportedVersions"]
    assert resultado["capabilities"] == {"tools": {"listChanged": False}} and resultado["instructions"]
    assert resultado["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "casa-lorenzi-copiloto"


def test_chamada_moderna_e_nome_em_base64(client, admin):
    token = criar_token(client, admin)
    lista = moderno(client, token, "tools/list").json()["result"]
    assert lista["resultType"] == "complete" and len(lista["tools"]) == 15
    nome = "ver_contexto"
    codificado = "=?base64?" + base64.b64encode(nome.encode()).decode() + "?="
    resposta = moderno(client, token, "tools/call", {"name": nome, "arguments": {}}, cabecalhos={"Mcp-Name": codificado})
    assert resposta.status_code == 200 and resposta.json()["result"]["isError"] is False
    assert chamadas_mcp()[-1].cliente == "teste-moderno"


def test_cabecalhos_que_nao_batem_com_o_corpo(client, admin):
    token = criar_token(client, admin)
    casos = [
        moderno(client, token, "tools/list", cabecalhos={"Mcp-Method": "tools/call"}),
        moderno(client, token, "tools/list", cabecalhos={"Mcp-Method": None}),
        moderno(client, token, "tools/list", cabecalhos={"MCP-Protocol-Version": LEGADA}),
        moderno(client, token, "tools/call", {"name": "ver_contexto"}, cabecalhos={"Mcp-Name": "consultar_faturamento"}),
        moderno(client, token, "tools/call", {"name": "ver_contexto"}, cabecalhos={"Mcp-Name": None}),
    ]
    for resposta in casos:
        assert resposta.status_code == 400 and resposta.json()["error"]["code"] == -32020, resposta.text
    assert chamadas_mcp() == []  # nada rodou


def test_versao_moderna_desconhecida_e_meta_incompleto(client, admin):
    token = criar_token(client, admin)
    futura = moderno(client, token, "tools/list", versao="2027-01-01")
    assert futura.status_code == 400 and futura.json()["error"]["code"] == -32022
    assert futura.json()["error"]["data"] == {
        "supported": [MODERNA, "2025-11-25", LEGADA, "2025-03-26"],
        "requested": "2027-01-01",
    }
    sem_capacidades = moderno(client, token, "tools/list", meta={"io.modelcontextprotocol/protocolVersion": MODERNA})
    assert sem_capacidades.status_code == 400 and sem_capacidades.json()["error"]["code"] == -32602
    sem_meta = legado(client, token, "tools/list", versao=MODERNA)
    assert sem_meta.status_code == 400 and sem_meta.json()["error"]["code"] == -32602


def test_versao_de_2025_em_meta_e_atendida_como_2025(client, admin):
    """A lista de versões suportadas inclui as de 2025: quem tentar de novo com uma delas não fica sem resposta."""
    token = criar_token(client, admin)
    resposta = moderno(client, token, "tools/list", versao="2025-11-25")
    assert resposta.status_code == 200 and len(resposta.json()["result"]["tools"]) == 15
    assert "resultType" not in resposta.json()["result"]


def test_metodo_desconhecido_moderno_responde_404(client, admin):
    token = criar_token(client, admin)
    resposta = moderno(client, token, "prompts/list")
    assert resposta.status_code == 404 and resposta.json()["error"]["code"] == -32601


# ---------- Ferramentas e permissões ----------


def test_so_ferramentas_da_equipe_e_so_leitura(client, admin):
    token = criar_token(client, admin)
    ferramentas = legado(client, token, "tools/list").json()["result"]["tools"]
    disponiveis = {f["name"] for f in ferramentas}
    assert disponiveis == {"ver_contexto"} | {f.nome for f in ferramentas_gerenciais.FERRAMENTAS}
    do_cliente = {f.nome for f in ferramentas_cliente.FERRAMENTAS}
    assert not disponiveis & do_cliente  # nada de pedidos, pontos ou devoluções de clientes
    for f in ferramentas:
        assert f["inputSchema"]["type"] == "object" and f["inputSchema"]["additionalProperties"] is False
        assert f["annotations"]["readOnlyHint"] is True and f["description"]


def test_faturamento_igual_ao_do_copiloto(client, admin):
    token = criar_token(client, admin)
    resultado = chamar(client, token, "consultar_faturamento", {"periodo": "ultimos_30_dias"})
    assert resultado["isError"] is False
    assert json.loads(resultado["content"][0]["text"]) == resultado["structuredContent"]
    dados = resultado["structuredContent"]
    assert dados["faturamento"].startswith("R$ ") and "regra da diretoria" in dados["definicao"]
    oficial = client.get("/api/financeiro/resumo", params={"comparar": "nenhum"}, headers=admin).json()
    centavos = f"{oficial['receitaLiquida']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    assert dados["faturamento"] == f"R$ {centavos}"


def _recusa(resultado) -> str:
    assert resultado["isError"] is True, resultado
    return resultado["content"][0]["text"]


def test_toda_a_equipe_usa_o_mcp_e_cada_um_ve_o_seu(client, admin, lojista, operador, paula):
    """Decisão 115 (substitui a 110): toda a equipe com acesso ao Assistente IA usa o MCP, e cada consulta vale o
    que o papel e a marca do dono permitem, como no copiloto do painel."""
    tokens = {
        nome: criar_token(client, perfil) for nome, perfil in [("lojista", lojista), ("operador", operador), ("paula", paula)]
    }

    # Lojista: estoque e Lupe+ sim (decisão 118); faturamento e transferências não
    assert chamar(client, tokens["lojista"], "consultar_estoque_baixo")["isError"] is False
    assert chamar(client, tokens["lojista"], "consultar_fidelidade")["isError"] is False
    for ferramenta in ("consultar_faturamento", "sugerir_transferencias"):
        assert "SEM_PERMISSAO: o perfil Lojista" in _recusa(chamar(client, tokens["lojista"], ferramenta))

    # Operador: estoque e transferências sim; faturamento não
    assert chamar(client, tokens["operador"], "sugerir_transferencias")["isError"] is False
    assert "SEM_PERMISSAO: o perfil Operador" in _recusa(chamar(client, tokens["operador"], "consultar_faturamento"))

    # Administradora só da Vulto: faturamento só da Vulto; a Casa Lorenzi é recusada
    contexto = chamar(client, tokens["paula"], "ver_contexto")["structuredContent"]
    assert contexto["marcasQuePodeVer"] == ["Vulto"]
    assert "SEM_PERMISSAO" in _recusa(chamar(client, tokens["paula"], "consultar_faturamento", {"marca": "LORENZI"}))
    vulto = chamar(client, tokens["paula"], "consultar_faturamento")
    assert vulto["isError"] is False and "Vulto" in " ".join(vulto["structuredContent"]["filtros"])

    # Quem é desativado perde o MCP na hora
    with SessionLocal() as db:
        db.execute(text("UPDATE usuarios SET ativo = false WHERE email = 'rafael.monteiro@casalorenzi.com.br'"))
        db.commit()
    assert legado(client, tokens["lojista"], "tools/list").status_code == 401
    assert legado(client, tokens["operador"], "tools/list").status_code == 200


def test_o_administrador_do_grupo_ve_as_duas_marcas(client, admin):
    token = criar_token(client, admin)
    contexto = chamar(client, token, "ver_contexto")["structuredContent"]
    assert contexto["marcasQuePodeVer"] == ["Casa Lorenzi", "Vulto"]
    so_vulto = chamar(client, token, "consultar_faturamento", {"marca": "VULTO"})
    assert so_vulto["isError"] is False and "Vulto" in " ".join(so_vulto["structuredContent"]["filtros"])


def test_parametro_a_mais_e_recusado_e_auditado(client, admin):
    token = criar_token(client, admin)
    resultado = chamar(client, token, "consultar_fidelidade", {"cliente_id": 1})
    assert resultado["isError"] is True and "PARAMETROS_INVALIDOS" in resultado["content"][0]["text"]
    chamada = chamadas_mcp()[-1]
    assert chamada.argumentos == {"cliente_id": 1} and chamada.sucesso is False and chamada.erro.startswith("PARAMETROS")


def test_auditoria_e_ultimo_uso(client, admin):
    token = criar_token(client, admin)
    chamar(client, token, "ver_contexto")
    chamada = chamadas_mcp()[-1]
    assert chamada.ferramenta == "ver_contexto" and chamada.sucesso and chamada.cliente == "testclient"
    token_salvo = client.get("/api/mcp/tokens", headers=admin).json()[0]
    assert token_salvo["chamadas"] == 1 and token_salvo["ultimoUsoEm"] is not None
    assert abs(token_salvo["ultimoUsoEm"] / 1000 - agora().timestamp()) < 60


def test_limite_de_consultas_por_token(client, admin, monkeypatch):
    monkeypatch.setitem(regra.LIMITE_POR_CONVERSA, regra.GERENCIAL, (2, 600))
    token = criar_token(client, admin)
    assert chamar(client, token, "ver_contexto")["isError"] is False
    assert chamar(client, token, "ver_contexto")["isError"] is False
    terceira = chamar(client, token, "ver_contexto")
    assert terceira["isError"] is True and terceira["content"][0]["text"].startswith("LIMITE_DE_CONSULTAS")
    assert [c.sucesso for c in chamadas_mcp()] == [True, True, False]
