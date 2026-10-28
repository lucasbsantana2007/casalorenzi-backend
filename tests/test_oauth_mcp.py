"""Login OAuth do servidor MCP, o conector do claude.ai (decisão 114): fichas, cadastro do app, página de login,
código de uso único com PKCE, renovação trocada a cada uso, revogação e as mesmas permissões do token pessoal."""

import base64
import hashlib
import re
import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from src.config import settings
from src.database.seed import SENHA_DEMO
from src.use_cases import oauth_mcp
from src.utils.datas import agora
from tests.conftest import _entrar
from tests.test_mcp import legado
from tests.util_assistente import sql

BASE = "http://testserver"
RECURSO = f"{BASE}/api/conector-mcp"
VOLTA = "https://claude.ai/api/mcp/auth_callback"
HELENA = "helena@casalorenzi.com.br"  # Administradora do grupo: a única que pode usar o MCP (decisão 110)
PAULA = "paula.ferraz@vulto.com.br"  # Administradora só da Vulto


def _pkce() -> tuple[str, str]:
    verificador = secrets.token_urlsafe(48)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    return verificador, desafio


def _registrar(client, **extra) -> dict:
    dados = {"client_name": "Claude", "redirect_uris": [VOLTA], "token_endpoint_auth_method": "none"} | extra
    resposta = client.post("/api/oauth/registro", json=dados)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _pagina(client, app: dict, desafio: str, **extra):
    params = {
        "response_type": "code",
        "client_id": app["client_id"],
        "redirect_uri": VOLTA,
        "code_challenge": desafio,
        "code_challenge_method": "S256",
        "state": "estado-123",
        "resource": RECURSO,
        "scope": "copiloto",
    } | extra
    return client.get("/api/oauth/autorizar", params=params, follow_redirects=False)


def _pedido_assinado(html: str) -> str:
    return re.search(r'name="pedido" value="([^"]+)"', html).group(1)


def _login(client, app: dict, desafio: str, email=HELENA, senha=SENHA_DEMO, decisao="autorizar"):
    pagina = _pagina(client, app, desafio)
    assert pagina.status_code == 200, pagina.text
    dados = {"pedido": _pedido_assinado(pagina.text), "email": email, "senha": senha, "decisao": decisao}
    return client.post("/api/oauth/autorizar", data=dados, follow_redirects=False)


def _codigo(resposta) -> dict:
    assert resposta.status_code == 303, resposta.text
    destino = resposta.headers["location"]
    assert destino.startswith(VOLTA + "?")
    return {k: v[0] for k, v in parse_qs(urlsplit(destino).query).items()}


def _trocar(client, app, codigo, verificador, **extra):
    dados = {
        "grant_type": "authorization_code",
        "code": codigo,
        "redirect_uri": VOLTA,
        "client_id": app["client_id"],
        "code_verifier": verificador,
        "resource": RECURSO,
    } | extra
    return client.post("/api/oauth/token", data=dados)


def _conectar(client) -> tuple[dict, dict]:
    """(app, tokens) de uma conexão completa da Helena."""
    app = _registrar(client)
    verificador, desafio = _pkce()
    volta = _codigo(_login(client, app, desafio))
    resposta = _trocar(client, app, volta["code"], verificador)
    assert resposta.status_code == 200, resposta.text
    return app, resposta.json()


def _ferramentas(client, token):
    return legado(client, token, "tools/list")


# ---------- Descoberta ----------


def test_401_aponta_para_a_ficha_e_as_fichas_apontam_para_o_login(client):
    resposta = client.post("/api/conector-mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resposta.status_code == 401
    desafio = resposta.headers["www-authenticate"]
    assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/api/conector-mcp"' in desafio

    ficha = client.get("/.well-known/oauth-protected-resource/api/conector-mcp").json()
    assert ficha["resource"] == RECURSO and ficha["authorization_servers"] == [BASE]
    assert client.get("/.well-known/oauth-protected-resource").json() == ficha

    servidor = client.get("/.well-known/oauth-authorization-server").json()
    assert servidor["issuer"] == BASE
    assert servidor["code_challenge_methods_supported"] == ["S256"]
    assert servidor["authorization_response_iss_parameter_supported"] is True
    assert servidor["client_id_metadata_document_supported"] is True
    for chave in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"):
        assert servidor[chave].startswith(BASE + "/api/oauth/")


# ---------- Fluxo completo ----------


def test_conecta_consulta_e_aparece_na_tela_de_tokens(client, admin):
    app, tokens = _conectar(client)
    assert tokens["token_type"] == "Bearer" and tokens["access_token"].startswith("clmcpa_")
    assert tokens["refresh_token"].startswith("clmcpr_") and tokens["expires_in"] > 0

    resposta = _ferramentas(client, tokens["access_token"])
    assert resposta.status_code == 200, resposta.text
    nomes = {f["name"] for f in resposta.json()["result"]["tools"]}
    assert "consultar_vendas" in nomes or len(nomes) >= 5

    # A conexão aparece com os tokens pessoais da Helena e é revogada por lá
    [conexao] = [t for t in client.get("/api/mcp/tokens", headers=admin).json() if t["prefixo"] == "oauth"]
    assert conexao["nome"] == "Claude (login)" and conexao["situacao"] == "ATIVO"
    client.delete(f"/api/mcp/tokens/{conexao['id']}", headers=admin)
    assert _ferramentas(client, tokens["access_token"]).status_code == 401
    renovar = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": app["client_id"]}
    assert client.post("/api/oauth/token", data=renovar).json()["error"] == "invalid_grant"


def test_volta_com_state_e_iss(client):
    app = _registrar(client)
    _, desafio = _pkce()
    volta = _codigo(_login(client, app, desafio))
    assert volta["state"] == "estado-123" and volta["iss"] == BASE and len(volta["code"]) >= 40


def test_cancelar_volta_com_access_denied(client):
    app = _registrar(client)
    _, desafio = _pkce()
    volta = _codigo(_login(client, app, desafio, decisao="negar"))
    assert volta["error"] == "access_denied" and "code" not in volta


# ---------- Quem pode autorizar ----------


@pytest.mark.parametrize(
    ("email", "senha", "mensagem"),
    [
        (HELENA, "senha-errada", "E-mail ou senha incorretos."),
        ("ninguem@exemplo.com", SENHA_DEMO, "E-mail ou senha incorretos."),
        (PAULA, SENHA_DEMO, "exclusivo do Administrador do grupo"),
        ("mariana.costa@gmail.com", SENHA_DEMO, "E-mail ou senha incorretos."),  # cliente da loja não é da equipe
    ],
)
def test_login_recusado_volta_para_a_pagina_sem_codigo(client, email, senha, mensagem):
    app = _registrar(client)
    _, desafio = _pkce()
    resposta = _login(client, app, desafio, email=email, senha=senha)
    assert resposta.status_code == 401 and mensagem in resposta.text
    assert "location" not in resposta.headers
    assert sql("SELECT count(*) FROM oauth_codigos") == [(0,)]


def test_pagina_nao_pode_ser_embutida_nem_guardada(client):
    app = _registrar(client)
    _, desafio = _pkce()
    pagina = _pagina(client, app, desafio)
    assert pagina.headers["x-frame-options"] == "DENY" and pagina.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in pagina.headers["content-security-policy"]
    assert "form-action 'self' https://claude.ai" in pagina.headers["content-security-policy"]


# ---------- Pedido de autorização ----------


def test_app_ou_endereco_de_volta_desconhecido_nao_redireciona(client):
    app = _registrar(client)
    _, desafio = _pkce()
    # Endereço de volta que não é o cadastrado: mostra o erro aqui, nunca manda o navegador para lá
    resposta = _pagina(client, app, desafio, redirect_uri="https://site-malicioso.com/callback")
    assert resposta.status_code == 400 and "location" not in resposta.headers
    resposta = _pagina(client, {"client_id": "clmcpc_nao-existe"}, desafio)
    assert resposta.status_code == 400 and "location" not in resposta.headers


@pytest.mark.parametrize(
    ("extra", "erro"),
    [
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge": ""}, "invalid_request"),
        ({"response_type": "token"}, "unsupported_response_type"),
        ({"resource": "https://outro-servidor.com/mcp"}, "invalid_target"),
    ],
)
def test_pedido_invalido_volta_ao_app_com_o_erro(client, extra, erro):
    app = _registrar(client)
    _, desafio = _pkce()
    volta = _codigo(_pagina(client, app, desafio, **extra))
    assert volta["error"] == erro and volta["state"] == "estado-123" and volta["iss"] == BASE


def test_escopo_desconhecido_recebe_so_o_copiloto(client):
    """O app pode pedir outro nome de escopo: a conexão sai, só com a leitura do copiloto."""
    app = _registrar(client)
    verificador, desafio = _pkce()
    pagina = _pagina(client, app, desafio, scope="claudeai admin")
    dados = {"pedido": _pedido_assinado(pagina.text), "email": HELENA, "senha": SENHA_DEMO, "decisao": "autorizar"}
    codigo = _codigo(client.post("/api/oauth/autorizar", data=dados, follow_redirects=False))["code"]
    resposta = _trocar(client, app, codigo, verificador).json()
    assert resposta["scope"] == "copiloto"


def test_pedido_assinado_vencido_ou_adulterado(client):
    app = _registrar(client)
    _, desafio = _pkce()
    pedido = _pedido_assinado(_pagina(client, app, desafio).text)
    adulterado = pedido[:-4] + ("AAAA" if not pedido.endswith("AAAA") else "BBBB")
    resposta = client.post(
        "/api/oauth/autorizar",
        data={"pedido": adulterado, "email": HELENA, "senha": SENHA_DEMO, "decisao": "autorizar"},
        follow_redirects=False,
    )
    assert resposta.status_code == 400 and "location" not in resposta.headers


# ---------- Código de autorização ----------


def test_codigo_vale_uma_vez_e_o_reuso_derruba_a_conexao(client):
    app = _registrar(client)
    verificador, desafio = _pkce()
    codigo = _codigo(_login(client, app, desafio))["code"]
    primeira = _trocar(client, app, codigo, verificador)
    assert primeira.status_code == 200
    segunda = _trocar(client, app, codigo, verificador)
    assert segunda.status_code == 400 and segunda.json()["error"] == "invalid_grant"
    # Sinal de código roubado: o acesso emitido na primeira troca também deixa de valer
    assert _ferramentas(client, primeira.json()["access_token"]).status_code == 401


def test_pkce_endereco_e_app_precisam_conferir(client):
    app = _registrar(client)
    verificador, desafio = _pkce()
    codigo = _codigo(_login(client, app, desafio))["code"]
    outro, _ = _pkce()
    assert _trocar(client, app, codigo, outro).json()["error"] == "invalid_grant"
    assert _trocar(client, app, codigo, verificador, redirect_uri=VOLTA + "?x=1").json()["error"] == "invalid_grant"
    intruso = _registrar(client, client_name="Outro app")
    assert _trocar(client, intruso, codigo, verificador).json()["error"] == "invalid_grant"
    assert _trocar(client, app, codigo, verificador, resource="https://outro.com/mcp").json()["error"] == "invalid_target"
    # Nenhuma tentativa errada gastou o código
    assert _trocar(client, app, codigo, verificador).status_code == 200


def test_codigo_vencido(client):
    app = _registrar(client)
    verificador, desafio = _pkce()
    codigo = _codigo(_login(client, app, desafio))["code"]
    sql("UPDATE oauth_codigos SET expira_em = :t", t=agora() - timedelta(seconds=1))
    assert _trocar(client, app, codigo, verificador).json()["error"] == "invalid_grant"


# ---------- Renovação ----------


def test_renovacao_troca_os_dois_e_o_reuso_derruba_a_conexao(client):
    app, tokens = _conectar(client)
    renovar = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": app["client_id"]}
    nova = client.post("/api/oauth/token", data=renovar)
    assert nova.status_code == 200, nova.text
    novos = nova.json()
    assert novos["refresh_token"] != tokens["refresh_token"]
    assert _ferramentas(client, novos["access_token"]).status_code == 200

    # A renovação antiga usada de novo: alguém copiou. Cai tudo.
    assert client.post("/api/oauth/token", data=renovar).json()["error"] == "invalid_grant"
    assert _ferramentas(client, novos["access_token"]).status_code == 401


def test_acesso_vencido_recebe_401(client):
    _, tokens = _conectar(client)
    sql("UPDATE oauth_tokens SET expira_em = :t WHERE tipo = 'ACESSO'", t=agora() - timedelta(seconds=1))
    assert _ferramentas(client, tokens["access_token"]).status_code == 401


def test_quem_perde_o_papel_perde_o_acesso(client):
    _, tokens = _conectar(client)
    sql("UPDATE usuarios SET marca = 'LORENZI' WHERE email = :e", e=HELENA)
    assert _ferramentas(client, tokens["access_token"]).status_code == 401


def test_conectar_o_mesmo_app_de_novo_substitui_a_conexao(client, admin):
    app, primeira = _conectar(client)
    verificador, desafio = _pkce()
    codigo = _codigo(_login(client, app, desafio))["code"]
    segunda = _trocar(client, app, codigo, verificador).json()
    assert _ferramentas(client, primeira["access_token"]).status_code == 401
    assert _ferramentas(client, segunda["access_token"]).status_code == 200
    ativas = [t for t in client.get("/api/mcp/tokens", headers=admin).json() if t["situacao"] == "ATIVO"]
    assert len(ativas) == 1


def test_revogar_pelo_app_desconecta(client):
    app, tokens = _conectar(client)
    resposta = client.post("/api/oauth/revogar", data={"token": tokens["refresh_token"], "client_id": app["client_id"]})
    assert resposta.status_code == 200
    assert _ferramentas(client, tokens["access_token"]).status_code == 401


# ---------- Cadastro do app ----------


@pytest.mark.parametrize(
    "redirects",
    [[], ["http://site.com/callback"], ["https://claude.ai/cb#frag"], ["javascript:alert(1)"], ["https://a.com"] * 11],
)
def test_cadastro_recusa_endereco_de_volta_perigoso(client, redirects):
    resposta = client.post("/api/oauth/registro", json={"client_name": "X", "redirect_uris": redirects})
    assert resposta.status_code == 400 and resposta.json()["error"] == "invalid_redirect_uri"


def test_app_com_segredo_precisa_mandar_o_segredo(client):
    app = _registrar(client, token_endpoint_auth_method="client_secret_post")
    assert app["client_secret"].startswith("clmcps_")
    verificador, desafio = _pkce()
    codigo = _codigo(_login(client, app, desafio))["code"]
    sem = _trocar(client, app, codigo, verificador)
    assert sem.status_code == 401 and sem.json()["error"] == "invalid_client"
    # Pelo cabeçalho Basic também vale (client_secret_basic)
    basico = base64.b64encode(f"{app['client_id']}:{app['client_secret']}".encode()).decode()
    dados = {"grant_type": "authorization_code", "code": codigo, "redirect_uri": VOLTA, "code_verifier": verificador}
    resposta = client.post("/api/oauth/token", data=dados, headers={"Authorization": f"Basic {basico}"})
    assert resposta.status_code == 200, resposta.text


def test_app_do_computador_volta_em_outra_porta(client):
    """Apps de desktop recebem a volta no próprio computador, numa porta que muda a cada vez (RFC 8252)."""
    app = _registrar(client, redirect_uris=["http://127.0.0.1:33418/callback"])
    _, desafio = _pkce()
    pagina = _pagina(client, app, desafio, redirect_uri="http://127.0.0.1:51234/callback")
    assert pagina.status_code == 200


# ---------- Ficha publicada pelo app (CIMD) ----------

FICHA = "https://claude.ai/oauth/mcp-oauth-client-metadata"


def test_app_pela_ficha_publicada(client, monkeypatch):
    baixadas = []

    def baixar(url):
        baixadas.append(url)
        return {"client_id": FICHA, "client_name": "Claude", "redirect_uris": [VOLTA], "token_endpoint_auth_method": "none"}

    monkeypatch.setattr(oauth_mcp, "baixar_ficha", baixar)
    app = {"client_id": FICHA}
    verificador, desafio = _pkce()
    codigo = _codigo(_login(client, app, desafio))["code"]
    assert _trocar(client, app, codigo, verificador).status_code == 200
    assert baixadas == [FICHA]  # depois da primeira vez, a ficha fica guardada por 24 h


@pytest.mark.parametrize(
    ("client_id", "ficha"),
    [
        ("https://site-malicioso.com/cliente.json", None),  # domínio fora da lista
        ("https://127.0.0.1/cliente.json", None),  # IP: nunca (rede interna)
        (FICHA, {"client_id": "https://claude.ai/outra", "redirect_uris": [VOLTA]}),  # client_id não confere
        (FICHA, {"client_id": FICHA, "redirect_uris": [VOLTA], "token_endpoint_auth_method": "private_key_jwt"}),
    ],
)
def test_ficha_publicada_recusada(client, monkeypatch, client_id, ficha):
    monkeypatch.setattr(oauth_mcp, "baixar_ficha", lambda url: ficha)
    _, desafio = _pkce()
    resposta = _pagina(client, {"client_id": client_id}, desafio)
    assert resposta.status_code == 400 and "location" not in resposta.headers


def test_issuer_configurado_vale_nas_fichas(client, monkeypatch):
    monkeypatch.setattr(settings, "URL_API", "https://casalorenzi-api.onrender.com")
    servidor = client.get("/.well-known/oauth-authorization-server").json()
    assert servidor["issuer"] == "https://casalorenzi-api.onrender.com"
    assert client.get("/.well-known/oauth-protected-resource").json()["resource"].startswith("https://casalorenzi-api")


def test_token_pessoal_continua_funcionando(client):
    headers = _entrar(client, HELENA)
    texto = client.post("/api/mcp/tokens", json={"nome": "Claude Code"}, headers=headers).json()["token"]
    assert _ferramentas(client, texto).status_code == 200
