"""Login OAuth 2.1 do servidor MCP (decisão 114, docs/mcp.md): o conector do claude.ai.

O claude.ai não aceita colar um token: ele pede o login. O fluxo segue a especificação de autorização do MCP:
1. O servidor MCP responde 401 com o endereço da ficha do recurso (Protected Resource Metadata, RFC 9728).
2. O app lê a ficha do servidor de autorização (RFC 8414) e se cadastra: pelo cadastro automático (DCR, RFC 7591)
   ou apontando para uma ficha publicada no próprio domínio (Client ID Metadata Document), aceita só dos domínios
   de OAUTH_CIMD_DOMINIOS.
3. A pessoa entra com o login do painel e autoriza. Só o Administrador do grupo pode (decisão 110), como no
   token pessoal. Sai um código de autorização: 10 minutos, uma vez só, preso ao PKCE (S256) e ao endereço de volta.
4. O app troca o código por um acesso (OAUTH_ACESSO_MINUTOS) e uma renovação (OAUTH_RENOVACAO_DIAS), trocada a
   cada uso; renovação usada de novo derruba a conexão (sinal de roubo).

Cada autorização vira uma conexão, que é uma linha de tokens_mcp: aparece em Inteligência > Conectar ao Claude, é
revogada por lá, conta no limite de tokens e usa a mesma auditoria e o mesmo limite de consultas do token pessoal.
Nada dos tokens fica em texto no banco: só o sha256.
"""

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m
from src.config import settings
from src.repositories import token_mcp_repository, usuario_repository
from src.use_cases import tokens_mcp
from src.utils.datas import agora
from src.utils.seguranca import confere_hash

ESCOPO = "copiloto"
CAMINHO_MCP = "/api/conector-mcp"
PREFIXO_CLIENTE, PREFIXO_SEGREDO = "clmcpc_", "clmcps_"
PREFIXO_ACESSO, PREFIXO_RENOVACAO = "clmcpa_", "clmcpr_"
VALIDADE_CODIGO = timedelta(minutes=10)
VALIDADE_PEDIDO = timedelta(minutes=15)  # a página de login aberta
CACHE_CIMD = timedelta(hours=24)
_INTERVALO_ULTIMO_USO = timedelta(minutes=1)
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_METODOS_AUTH = ("none", "client_secret_post", "client_secret_basic")

CONTA_NAO_AUTORIZADA = (
    "O acesso pelo Claude é exclusivo do Administrador do grupo. Entre com essa conta ou use o copiloto no painel."
)
CREDENCIAIS_INVALIDAS = "E-mail ou senha incorretos."


class ErroOAuth(Exception):
    """Erro no formato do OAuth: {"error": ..., "error_description": ...}."""

    def __init__(self, erro: str, descricao: str, status: int = 400):
        super().__init__(descricao)
        self.erro, self.descricao, self.status = erro, descricao, status

    def corpo(self) -> dict:
        return {"error": self.erro, "error_description": self.descricao}


class ErroLogin(Exception):
    """Login recusado na página de autorização: a página volta com a mensagem."""


@dataclass
class Pedido:
    """Pedido de autorização já conferido."""

    cliente: m.OAuthCliente
    redirect_uri: str
    state: str | None
    code_challenge: str
    recurso: str
    escopo: str


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


# ---------- Endereços e fichas ----------


def recurso(base: str) -> str:
    """O endereço canônico do servidor MCP (o "resource" do RFC 8707)."""
    return base + CAMINHO_MCP


def _canonico(url: str) -> str:
    partes = urlsplit(url.strip())
    return urlunsplit((partes.scheme.lower(), partes.netloc.lower(), partes.path.rstrip("/"), partes.query, ""))


def ficha_do_recurso(base: str) -> dict:
    return {
        "resource": recurso(base),
        "authorization_servers": [base],
        "scopes_supported": [ESCOPO],
        "bearer_methods_supported": ["header"],
        "resource_name": "Casa Lorenzi e Vulto · Copiloto",
    }


def ficha_do_servidor(base: str) -> dict:
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/api/oauth/autorizar",
        "token_endpoint": f"{base}/api/oauth/token",
        "registration_endpoint": f"{base}/api/oauth/registro",
        "revocation_endpoint": f"{base}/api/oauth/revogar",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": list(_METODOS_AUTH),
        "revocation_endpoint_auth_methods_supported": list(_METODOS_AUTH),
        "scopes_supported": [ESCOPO, "offline_access"],
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": True,
    }


# ---------- Apps (clientes OAuth) ----------


def _redirect_valido(uri: object) -> bool:
    """https (sem fragmento) ou http no próprio computador (apps de desktop)."""
    if not isinstance(uri, str) or len(uri) > 500:
        return False
    partes = urlsplit(uri)
    if partes.fragment or not partes.hostname:
        return False
    if partes.scheme == "https":
        return True
    return partes.scheme == "http" and partes.hostname in _LOOPBACK


def _mesmo_redirect(pedido: str, cadastrado: str) -> bool:
    """Igual ao cadastrado; no próprio computador, a porta pode mudar (RFC 8252, 7.3)."""
    if pedido == cadastrado:
        return True
    a, b = urlsplit(pedido), urlsplit(cadastrado)
    if a.hostname in _LOOPBACK and a.scheme == "http":
        return (a.scheme, a.hostname, a.path, a.query) == (b.scheme, b.hostname, b.path, b.query)
    return False


def _redirects(valor: object) -> list[str]:
    if not isinstance(valor, list) or not 1 <= len(valor) <= 10 or not all(_redirect_valido(u) for u in valor):
        raise ErroOAuth("invalid_redirect_uri", "Informe de 1 a 10 endereços de volta: https ou http no próprio computador.")
    return list(valor)


def _nome(valor: object) -> str:
    nome = " ".join(str(valor or "").split())[:120]
    return nome or "App sem nome"


def registrar(db: Session, dados: dict) -> dict:
    """Cadastro automático (DCR, RFC 7591). Devolve o client_id (e o segredo, se o app pediu um)."""
    if not isinstance(dados, dict):
        raise ErroOAuth("invalid_client_metadata", "Corpo inválido.")
    redirects = _redirects(dados.get("redirect_uris"))
    metodo = dados.get("token_endpoint_auth_method") or "client_secret_basic"
    if metodo not in _METODOS_AUTH:
        raise ErroOAuth("invalid_client_metadata", f"Autenticação do app não aceita: {metodo}.")
    tipos = dados.get("grant_types") or ["authorization_code"]
    if not isinstance(tipos, list) or "authorization_code" not in tipos:
        raise ErroOAuth("invalid_client_metadata", "O app precisa usar o tipo authorization_code.")
    respostas = dados.get("response_types") or ["code"]
    if respostas != ["code"]:
        raise ErroOAuth("invalid_client_metadata", "Só o tipo de resposta code é aceito.")
    momento = agora()
    client_id = PREFIXO_CLIENTE + secrets.token_urlsafe(24)
    segredo = PREFIXO_SEGREDO + secrets.token_urlsafe(32) if metodo != "none" else None
    cliente = m.OAuthCliente(
        client_id=client_id,
        nome=_nome(dados.get("client_name")),
        redirect_uris=redirects,
        metodo_auth=metodo,
        segredo_hash=_hash(segredo) if segredo else None,
        origem="DCR",
        criado_em=momento,
        atualizado_em=momento,
    )
    db.add(cliente)
    db.flush()
    saida = {
        "client_id": client_id,
        "client_id_issued_at": int(momento.timestamp()),
        "client_name": cliente.nome,
        "redirect_uris": redirects,
        "grant_types": [t for t in ("authorization_code", "refresh_token") if t in tipos] or ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": metodo,
    }
    if segredo:
        saida |= {"client_secret": segredo, "client_secret_expires_at": 0}
    return saida


def _dominio_permitido(host: str) -> bool:
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return False  # endereço IP: nunca (contra acesso à rede interna)
    except ValueError:
        pass
    return any(host == d or host.endswith("." + d) for d in settings.OAUTH_CIMD_DOMINIOS)


def baixar_ficha(url: str) -> dict:
    """GET da ficha do app (CIMD). Sem seguir redirecionamento, com tempo e tamanho limitados."""
    with httpx.Client(timeout=5, follow_redirects=False) as http:
        with http.stream("GET", url, headers={"Accept": "application/json"}) as resposta:
            if resposta.status_code != 200:
                raise ErroOAuth("invalid_client", f"A ficha do app respondeu {resposta.status_code}.")
            corpo = b""
            for pedaco in resposta.iter_bytes():
                corpo += pedaco
                if len(corpo) > 10_000:
                    raise ErroOAuth("invalid_client", "A ficha do app é grande demais.")
    try:
        return json.loads(corpo)
    except ValueError as erro:
        raise ErroOAuth("invalid_client", "A ficha do app não é um JSON válido.") from erro


def _cliente_cimd(db: Session, url: str) -> m.OAuthCliente:
    partes = urlsplit(url)
    if partes.scheme != "https" or not partes.hostname or partes.path in ("", "/") or partes.fragment:
        raise ErroOAuth("invalid_client", "O client_id em forma de endereço precisa ser https e ter um caminho.")
    if not _dominio_permitido(partes.hostname):
        raise ErroOAuth("invalid_client", "Este app não está na lista dos que podem se conectar.")
    cliente = db.scalar(select(m.OAuthCliente).where(m.OAuthCliente.client_id == url))
    momento = agora()
    if cliente is not None and momento - cliente.atualizado_em < CACHE_CIMD:
        return cliente
    try:
        ficha = baixar_ficha(url)
    except ErroOAuth:
        raise
    except httpx.HTTPError as erro:
        raise ErroOAuth("invalid_client", "Não consegui ler a ficha do app.") from erro
    if not isinstance(ficha, dict) or ficha.get("client_id") != url:
        raise ErroOAuth("invalid_client", "O client_id da ficha não confere com o endereço dela.")
    metodo = ficha.get("token_endpoint_auth_method") or "none"
    if metodo != "none":
        raise ErroOAuth("invalid_client", f"Autenticação do app não aceita: {metodo}.")
    redirects = _redirects(ficha.get("redirect_uris"))
    if cliente is None:
        cliente = m.OAuthCliente(client_id=url, origem="CIMD", metodo_auth="none", criado_em=momento)
        db.add(cliente)
    cliente.nome = _nome(ficha.get("client_name"))
    cliente.redirect_uris = redirects
    cliente.atualizado_em = momento
    db.flush()
    return cliente


def obter_cliente(db: Session, client_id: str | None) -> m.OAuthCliente:
    if not client_id or len(client_id) > 255:
        raise ErroOAuth("invalid_client", "App não informado.", 401)
    if client_id.startswith("https://"):
        return _cliente_cimd(db, client_id)
    cliente = db.scalar(select(m.OAuthCliente).where(m.OAuthCliente.client_id == client_id))
    if cliente is None:
        raise ErroOAuth("invalid_client", "App não cadastrado.", 401)
    return cliente


def autenticar_cliente(db: Session, client_id: str | None, segredo: str | None) -> m.OAuthCliente:
    cliente = obter_cliente(db, client_id)
    if cliente.metodo_auth != "none":
        if not segredo or not hmac.compare_digest(_hash(segredo), cliente.segredo_hash or ""):
            raise ErroOAuth("invalid_client", "Segredo do app incorreto.", 401)
    return cliente


# ---------- Pedido de autorização ----------


@dataclass
class ErroComVolta(Exception):
    """Erro devolvido ao app pelo endereço de volta (o app e o endereço já foram conferidos)."""

    redirect_uri: str
    state: str | None
    erro: str
    descricao: str


def conferir_app(db: Session, params: dict) -> tuple[m.OAuthCliente, str]:
    """O app e o endereço de volta. Erro aqui não volta para o app: a página mostra (RFC 6749, 4.1.2.1)."""
    cliente = obter_cliente(db, params.get("client_id"))
    redirect_uri = params.get("redirect_uri") or ""
    if not any(_mesmo_redirect(redirect_uri, r) for r in cliente.redirect_uris):
        raise ErroOAuth("invalid_request", "O endereço de volta não é um dos cadastrados para este app.")
    return cliente, redirect_uri


def conferir_pedido(db: Session, params: dict, base: str) -> Pedido:
    cliente, redirect_uri = conferir_app(db, params)
    state = params.get("state")
    if state is not None and len(state) > 500:
        state = None

    def recusar(erro: str, descricao: str):
        raise ErroComVolta(redirect_uri, state, erro, descricao)

    if params.get("response_type") != "code":
        recusar("unsupported_response_type", "Só o tipo de resposta code é aceito.")
    desafio = params.get("code_challenge") or ""
    if params.get("code_challenge_method") != "S256" or not 43 <= len(desafio) <= 128:
        recusar("invalid_request", "PKCE obrigatório, com o método S256.")
    alvo = params.get("resource")
    if alvo and _canonico(alvo) != _canonico(recurso(base)):
        recusar("invalid_target", "Este servidor só emite acesso para o próprio servidor MCP.")
    # Escopo: há um só, de leitura (copiloto). Pedido de outro nome não derruba a conexão: o servidor concede só
    # o copiloto e informa na resposta do token (RFC 6749, 3.3)
    return Pedido(cliente, redirect_uri, state, desafio, recurso(base), ESCOPO)


def assinar_pedido(pedido: Pedido) -> str:
    """O pedido conferido vai assinado no formulário: o POST não precisa (nem pode) confiar nos campos de novo."""
    dados = {
        "tipo": "oauth_pedido",
        "client_id": pedido.cliente.client_id,
        "redirect_uri": pedido.redirect_uri,
        "state": pedido.state,
        "code_challenge": pedido.code_challenge,
        "recurso": pedido.recurso,
        "exp": agora() + VALIDADE_PEDIDO,
    }
    return jwt.encode(dados, settings.JWT_SECRET, algorithm="HS256")


def ler_pedido(db: Session, assinado: str | None) -> Pedido:
    try:
        dados = jwt.decode(assinado or "", settings.JWT_SECRET, algorithms=["HS256"])
        if dados.get("tipo") != "oauth_pedido":
            raise jwt.InvalidTokenError
    except jwt.PyJWTError as erro:
        raise ErroOAuth("invalid_request", "A página de autorização venceu. Volte ao app e conecte de novo.") from erro
    cliente = obter_cliente(db, dados["client_id"])
    return Pedido(cliente, dados["redirect_uri"], dados["state"], dados["code_challenge"], dados["recurso"], ESCOPO)


def endereco_de_volta(redirect_uri: str, base: str, **params) -> str:
    """O endereço de volta com os parâmetros, sempre com iss (RFC 9207)."""
    params = {k: v for k, v in params.items() if v is not None} | {"iss": base}
    return redirect_uri + ("&" if "?" in redirect_uri else "?") + urlencode(params)


def _conta(db: Session, email: str, senha: str) -> m.Usuario:
    usuario = usuario_repository.por_email(db, email) if "@" in (email or "") else None
    if usuario is None or usuario.convite_pendente or not confere_hash(senha or "", usuario.senha_hash):
        raise ErroLogin(CREDENCIAIS_INVALIDAS)
    if not tokens_mcp.pode_usar(usuario):
        raise ErroLogin(CONTA_NAO_AUTORIZADA)
    return usuario


def autorizar(db: Session, pedido: Pedido, email: str, senha: str, base: str) -> str:
    """Login certo de quem pode: grava o código e devolve o endereço de volta com ele."""
    usuario = _conta(db, email, senha)
    codigo = secrets.token_urlsafe(32)
    momento = agora()
    db.add(
        m.OAuthCodigo(
            hash=_hash(codigo),
            cliente_id=pedido.cliente.id,
            usuario_id=usuario.id,
            redirect_uri=pedido.redirect_uri,
            code_challenge=pedido.code_challenge,
            recurso=pedido.recurso,
            escopo=pedido.escopo,
            criado_em=momento,
            expira_em=momento + VALIDADE_CODIGO,
        )
    )
    db.flush()
    return endereco_de_volta(pedido.redirect_uri, base, code=codigo, state=pedido.state)


# ---------- Tokens ----------


def _revogar_conexao(db: Session, token_mcp_id: int | None) -> None:
    if token_mcp_id is None:
        return
    conexao = db.get(m.TokenMcp, token_mcp_id)
    if conexao is not None and conexao.revogado_em is None:
        conexao.revogado_em = agora()


def _emitir(db: Session, conexao: m.TokenMcp, cliente: m.OAuthCliente, alvo: str) -> dict:
    momento = agora()
    acesso = PREFIXO_ACESSO + secrets.token_urlsafe(32)
    renovacao = PREFIXO_RENOVACAO + secrets.token_urlsafe(32)
    fim_acesso = min(momento + timedelta(minutes=settings.OAUTH_ACESSO_MINUTOS), conexao.expira_em)
    fim_renovacao = min(momento + timedelta(days=settings.OAUTH_RENOVACAO_DIAS), conexao.expira_em)
    for tipo, texto, fim in (("ACESSO", acesso, fim_acesso), ("RENOVACAO", renovacao, fim_renovacao)):
        db.add(
            m.OAuthToken(
                token_mcp_id=conexao.id,
                cliente_id=cliente.id,
                tipo=tipo,
                hash=_hash(texto),
                recurso=alvo,
                escopo=ESCOPO,
                criado_em=momento,
                expira_em=fim,
            )
        )
    db.flush()
    return {
        "access_token": acesso,
        "token_type": "Bearer",
        "expires_in": max(int((fim_acesso - momento).total_seconds()), 0),
        "refresh_token": renovacao,
        "scope": ESCOPO,
    }


def _nova_conexao(db: Session, usuario: m.Usuario, cliente: m.OAuthCliente) -> m.TokenMcp:
    """A conexão (linha de tokens_mcp). Autorizar o mesmo app de novo substitui a conexão anterior dele."""
    momento = agora()
    token_mcp_repository.travar_usuario(db, usuario.id)
    anteriores = db.scalars(
        select(m.OAuthToken.token_mcp_id)
        .join(m.TokenMcp, m.TokenMcp.id == m.OAuthToken.token_mcp_id)
        .where(
            m.OAuthToken.cliente_id == cliente.id,
            m.TokenMcp.usuario_id == usuario.id,
            m.TokenMcp.revogado_em.is_(None),
        )
        .distinct()
    ).all()
    for token_mcp_id in anteriores:
        _revogar_conexao(db, token_mcp_id)
    db.flush()
    if token_mcp_repository.ativos_do_usuario(db, usuario.id, momento) >= settings.MCP_TOKENS_POR_USUARIO:
        raise ErroOAuth(
            "invalid_grant",
            f"Você já tem {settings.MCP_TOKENS_POR_USUARIO} conexões ativas. Revogue uma em Inteligência > Conectar ao Claude.",
        )
    conexao = m.TokenMcp(
        usuario_id=usuario.id,
        nome=f"{cliente.nome[:50]} (login)",
        hash=_hash(secrets.token_urlsafe(32)),  # nunca usado como texto: o acesso é pelos tokens OAuth
        prefixo="oauth",
        criado_em=momento,
        expira_em=momento + timedelta(days=settings.MCP_TOKEN_VALIDADE_DIAS),
    )
    db.add(conexao)
    db.flush()
    return conexao


def _confere_pkce(verificador: str | None, desafio: str) -> bool:
    if not verificador or not 43 <= len(verificador) <= 128:
        return False
    calculado = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(calculado, desafio)


def trocar_codigo(db: Session, cliente: m.OAuthCliente, form: dict) -> dict:
    codigo = db.scalar(select(m.OAuthCodigo).where(m.OAuthCodigo.hash == _hash(form.get("code") or "")).with_for_update())
    if codigo is None or codigo.cliente_id != cliente.id:
        raise ErroOAuth("invalid_grant", "Código de autorização inválido.")
    if codigo.usado_em is not None:
        # Código usado duas vezes: alguém pode ter copiado. Derruba o que ele gerou.
        _revogar_conexao(db, codigo.token_mcp_id)
        db.commit()
        raise ErroOAuth("invalid_grant", "Código de autorização já usado.")
    if codigo.expira_em <= agora():
        raise ErroOAuth("invalid_grant", "Código de autorização vencido.")
    if form.get("redirect_uri") != codigo.redirect_uri:
        raise ErroOAuth("invalid_grant", "O endereço de volta não é o mesmo do pedido.")
    if not _confere_pkce(form.get("code_verifier"), codigo.code_challenge):
        raise ErroOAuth("invalid_grant", "O code_verifier não confere (PKCE).")
    alvo = form.get("resource")
    if alvo and _canonico(alvo) != _canonico(codigo.recurso):
        raise ErroOAuth("invalid_target", "Este código é de outro recurso.")
    codigo.usado_em = agora()
    usuario = db.get(m.Usuario, codigo.usuario_id)
    if usuario is None or not tokens_mcp.pode_usar(usuario):
        raise ErroOAuth("invalid_grant", CONTA_NAO_AUTORIZADA)
    conexao = _nova_conexao(db, usuario, cliente)
    codigo.token_mcp_id = conexao.id
    return _emitir(db, conexao, cliente, codigo.recurso)


def renovar(db: Session, cliente: m.OAuthCliente, form: dict) -> dict:
    token = db.scalar(
        select(m.OAuthToken)
        .where(m.OAuthToken.hash == _hash(form.get("refresh_token") or ""), m.OAuthToken.tipo == "RENOVACAO")
        .with_for_update(of=m.OAuthToken)
    )
    if token is None or token.cliente_id != cliente.id:
        raise ErroOAuth("invalid_grant", "Renovação inválida.")
    if token.revogado_em is not None:
        # Renovação já trocada sendo usada de novo: sinal de roubo. Derruba a conexão inteira.
        _revogar_conexao(db, token.token_mcp_id)
        db.commit()
        raise ErroOAuth("invalid_grant", "Renovação já usada. Conecte de novo.")
    conexao = token.conexao
    if token.expira_em <= agora() or tokens_mcp.situacao(conexao) != tokens_mcp.ATIVO:
        raise ErroOAuth("invalid_grant", "A conexão venceu ou foi revogada. Conecte de novo.")
    if not tokens_mcp.pode_usar(conexao.usuario):
        raise ErroOAuth("invalid_grant", CONTA_NAO_AUTORIZADA)
    alvo = form.get("resource")
    if alvo and _canonico(alvo) != _canonico(token.recurso):
        raise ErroOAuth("invalid_target", "Esta renovação é de outro recurso.")
    token.revogado_em = agora()
    return _emitir(db, conexao, cliente, token.recurso)


def emitir(db: Session, form: dict, segredo_basico: tuple[str, str] | None) -> dict:
    """Endpoint de token: authorization_code ou refresh_token."""
    client_id, segredo = segredo_basico or (form.get("client_id"), form.get("client_secret"))
    cliente = autenticar_cliente(db, client_id, segredo)
    tipo = form.get("grant_type")
    if tipo == "authorization_code":
        return trocar_codigo(db, cliente, form)
    if tipo == "refresh_token":
        return renovar(db, cliente, form)
    raise ErroOAuth("unsupported_grant_type", "Use authorization_code ou refresh_token.")


def revogar(db: Session, form: dict, segredo_basico: tuple[str, str] | None) -> None:
    """RFC 7009: revogar o acesso ou a renovação desconecta o app (a conexão inteira). Token desconhecido: nada."""
    client_id, segredo = segredo_basico or (form.get("client_id"), form.get("client_secret"))
    cliente = autenticar_cliente(db, client_id, segredo)
    token = db.scalar(select(m.OAuthToken).where(m.OAuthToken.hash == _hash(form.get("token") or "")))
    if token is not None and token.cliente_id == cliente.id:
        _revogar_conexao(db, token.token_mcp_id)


def autenticar(db: Session, texto: str | None, alvo: str) -> m.TokenMcp | None:
    """Acesso OAuth válido, emitido para este servidor, de uma conexão ativa de quem pode: a conexão; senão None."""
    if not texto or not texto.startswith(PREFIXO_ACESSO) or len(texto) > 100:
        return None
    token = db.scalar(select(m.OAuthToken).where(m.OAuthToken.hash == _hash(texto), m.OAuthToken.tipo == "ACESSO"))
    momento = agora()
    if token is None or token.revogado_em is not None or token.expira_em <= momento:
        return None
    if _canonico(token.recurso) != _canonico(alvo):
        return None
    conexao = token.conexao
    if tokens_mcp.situacao(conexao) != tokens_mcp.ATIVO or not tokens_mcp.pode_usar(conexao.usuario):
        return None
    if conexao.ultimo_uso_em is None or momento - conexao.ultimo_uso_em >= _INTERVALO_ULTIMO_USO:
        conexao.ultimo_uso_em = momento
    return conexao
