"""Login OAuth do servidor MCP: o conector do claude.ai (decisão 114). Regras em src/use_cases/oauth_mcp.py.

Na raiz (sem /api), as fichas que os apps procuram:
    GET /.well-known/oauth-protected-resource[/api/conector-mcp]   ficha do recurso (RFC 9728)
    GET /.well-known/oauth-authorization-server                    ficha do servidor de autorização (RFC 8414)
Em /api/oauth:
    POST registro    cadastro automático do app (RFC 7591)
    GET  autorizar   página de login e autorização; POST autorizar: o formulário
    POST token       troca do código e renovação (application/x-www-form-urlencoded)
    POST revogar     desconecta o app (RFC 7009)
"""

import base64
import json
import logging
from html import escape
from urllib.parse import parse_qsl, unquote, urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from src.config import settings
from src.database.connection import get_db
from src.middlewares import limite
from src.use_cases import oauth_mcp
from src.use_cases.oauth_mcp import ErroComVolta, ErroLogin, ErroOAuth
from src.utils.erros import MuitasTentativas

log = logging.getLogger(__name__)
raiz = APIRouter(include_in_schema=False)
router = APIRouter(prefix="/oauth", tags=["OAuth do servidor MCP"], include_in_schema=False)

SEM_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
TAMANHO_MAXIMO = 16 * 1024


def base(request: Request) -> str:
    """O endereço público da API (issuer). URL_API no Render; sem ela, o endereço por onde o pedido chegou."""
    if settings.URL_API:
        return settings.URL_API
    return f"{request.url.scheme}://{request.url.netloc}"


def _ip(request: Request) -> str:
    return request.client.host if request.client else "desconhecido"


def _json(corpo: dict, status: int = 200, publico: bool = False) -> JSONResponse:
    cabecalhos = dict(SEM_CACHE)
    if publico:
        cabecalhos["Access-Control-Allow-Origin"] = "*"  # fichas públicas: apps no navegador também leem
    return JSONResponse(corpo, status_code=status, headers=cabecalhos)


def _erro(erro: ErroOAuth) -> JSONResponse:
    resposta = _json(erro.corpo(), erro.status)
    if erro.status == 401:
        resposta.headers["WWW-Authenticate"] = 'Basic realm="casa-lorenzi-oauth"'
    return resposta


async def _form(request: Request) -> dict:
    """application/x-www-form-urlencoded, sem dependência nova."""
    corpo = await request.body()
    if len(corpo) > TAMANHO_MAXIMO:
        raise ErroOAuth("invalid_request", "Pedido grande demais.")
    return dict(parse_qsl(corpo.decode("utf-8", "replace"), keep_blank_values=True))


def _basico(request: Request) -> tuple[str, str] | None:
    """client_id e segredo no cabeçalho Authorization: Basic (client_secret_basic)."""
    esquema, _, valor = request.headers.get("authorization", "").partition(" ")
    if esquema.lower() != "basic" or not valor:
        return None
    try:
        usuario, _, senha = base64.b64decode(valor.strip()).decode().partition(":")
    except ValueError as erro:
        raise ErroOAuth("invalid_client", "Cabeçalho Basic inválido.", 401) from erro
    return unquote(usuario), unquote(senha)


# ---------- Fichas (na raiz) ----------


@raiz.get("/.well-known/oauth-protected-resource")
@raiz.get("/.well-known/oauth-protected-resource/api/conector-mcp")
def ficha_do_recurso(request: Request):
    return _json(oauth_mcp.ficha_do_recurso(base(request)), publico=True)


@raiz.get("/.well-known/oauth-authorization-server")
def ficha_do_servidor(request: Request):
    return _json(oauth_mcp.ficha_do_servidor(base(request)), publico=True)


# ---------- Cadastro do app ----------


@router.post("/registro")
async def registrar(request: Request, db: Session = Depends(get_db)):
    try:
        limite.conferir(f"oauth:registro:{_ip(request)}", maximo=20, janela_segundos=3600)
        corpo = await request.body()
        if len(corpo) > TAMANHO_MAXIMO:
            raise ErroOAuth("invalid_client_metadata", "Pedido grande demais.")
        try:
            dados = json.loads(corpo or b"{}")
        except ValueError as erro:
            raise ErroOAuth("invalid_client_metadata", "Corpo não é um JSON válido.") from erro
        saida = oauth_mcp.registrar(db, dados)
        db.commit()
        return _json(saida, 201)
    except MuitasTentativas:
        return _json({"error": "too_many_requests", "error_description": limite.MENSAGEM}, 429)
    except ErroOAuth as erro:
        db.rollback()
        return _erro(erro)


# ---------- Página de login e autorização ----------

ESTILO = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f3f2ef;
  font-family:Helvetica,Arial,sans-serif;color:#1c1d21;padding:24px 16px}
main{width:100%;max-width:420px;background:#fff;border:1px solid #e3e1dc;border-radius:18px;padding:32px 28px}
.marcas{font-family:Georgia,serif;letter-spacing:.18em;font-size:13px;text-transform:uppercase;color:#5c5b57;margin:0 0 20px}
h1{font-size:21px;line-height:1.3;margin:0 0 10px;font-weight:600}
p{font-size:14px;line-height:1.55;margin:0 0 12px;color:#3d3c39}
ul{margin:0 0 18px;padding-left:18px;font-size:14px;line-height:1.55;color:#3d3c39}
.app{font-weight:600;color:#1c1d21}
label{display:block;font-size:13px;font-weight:600;margin:14px 0 6px}
input{width:100%;padding:11px 12px;border:1px solid #c9c6bf;border-radius:10px;font-size:15px}
input:focus{outline:2px solid #1c1d21;outline-offset:1px}
.acoes{display:flex;gap:10px;margin-top:22px}
button{flex:1;padding:12px;border-radius:10px;font-size:14px;cursor:pointer;border:1px solid #1c1d21}
.sim{background:#1c1d21;color:#fff}.nao{background:#fff;color:#1c1d21}
.erro{background:#fbeaea;color:#8a1c1c;border-radius:10px;padding:10px 12px;font-size:14px;margin:0 0 14px}
.nota{font-size:12px;color:#8a8984;margin-top:18px}
"""


def _pagina(titulo: str, corpo: str, status: int = 200, destino: str | None = None) -> HTMLResponse:
    # form-action: o Chrome aplica também ao redirecionamento depois do POST, então inclui o endereço de volta do app
    acoes = "'self'"
    if destino:
        partes = urlsplit(destino)
        acoes += f" {partes.scheme}://{partes.netloc}"
    cabecalhos = SEM_CACHE | {
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": (
            f"default-src 'none'; style-src 'unsafe-inline'; form-action {acoes}; frame-ancestors 'none'; base-uri 'none'"
        ),
    }
    html = (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(titulo)}</title><style>{ESTILO}</style></head>"
        f'<body><main><p class="marcas">Casa Lorenzi · Vulto</p>{corpo}</main></body></html>'
    )
    return HTMLResponse(html, status_code=status, headers=cabecalhos)


def _pagina_erro(mensagem: str) -> HTMLResponse:
    corpo = (
        "<h1>Não foi possível conectar</h1>"
        f'<p class="erro">{escape(mensagem)}</p>'
        "<p>Volte ao app e tente conectar de novo. Se continuar, fale com o administrador.</p>"
    )
    return _pagina("Não foi possível conectar", corpo, 400)


def _pagina_login(pedido: oauth_mcp.Pedido, assinado: str, email: str = "", erro: str | None = None) -> HTMLResponse:
    app = escape(pedido.cliente.nome)
    volta = escape(urlsplit(pedido.redirect_uri).netloc)
    aviso = f'<p class="erro" role="alert">{escape(erro)}</p>' if erro else ""
    corpo = f"""
<h1>Conectar <span class="app">{app}</span> à Casa Lorenzi</h1>
<p>Com a sua autorização, o app vai poder:</p>
<ul>
<li>consultar vendas, estoque, transferências, alertas e os números do Lupe+;</li>
<li>só ler: ele não altera nada e não vê dados pessoais de clientes;</li>
<li>usar as mesmas permissões da sua conta do painel.</li>
</ul>
{aviso}
<form method="post" action="/api/oauth/autorizar">
<input type="hidden" name="pedido" value="{escape(assinado)}">
<label for="email">E-mail do painel</label>
<input id="email" name="email" type="email" autocomplete="username" required value="{escape(email)}">
<label for="senha">Senha</label>
<input id="senha" name="senha" type="password" autocomplete="current-password" required>
<div class="acoes">
<button class="nao" type="submit" name="decisao" value="negar" formnovalidate>Cancelar</button>
<button class="sim" type="submit" name="decisao" value="autorizar">Entrar e autorizar</button>
</div>
</form>
<p class="nota">Depois, você volta para {volta}. Para desconectar, revogue a conexão em Inteligência &gt; Conectar
ao Claude.</p>"""
    return _pagina(f"Conectar {pedido.cliente.nome}", corpo, 401 if erro else 200, pedido.redirect_uri)


def _voltar(destino: str) -> RedirectResponse:
    return RedirectResponse(destino, status_code=303, headers=SEM_CACHE)


@router.get("/autorizar")
def pagina_de_autorizacao(request: Request, db: Session = Depends(get_db)):
    params = dict(request.query_params)
    endereco = base(request)
    try:
        pedido = oauth_mcp.conferir_pedido(db, params, endereco)
        db.commit()  # ficha do app (CIMD) guardada
    except ErroComVolta as erro:
        db.commit()
        destino = oauth_mcp.endereco_de_volta(
            erro.redirect_uri, endereco, error=erro.erro, error_description=erro.descricao, state=erro.state
        )
        return _voltar(destino)
    except ErroOAuth as erro:
        db.rollback()
        return _pagina_erro(erro.descricao)
    return _pagina_login(pedido, oauth_mcp.assinar_pedido(pedido))


@router.post("/autorizar")
async def autorizar(request: Request, db: Session = Depends(get_db)):
    endereco = base(request)
    try:
        form = await _form(request)
        pedido = oauth_mcp.ler_pedido(db, form.get("pedido"))
    except ErroOAuth as erro:
        db.rollback()
        return _pagina_erro(erro.descricao)
    if form.get("decisao") != "autorizar":
        destino = oauth_mcp.endereco_de_volta(
            pedido.redirect_uri, endereco, error="access_denied", error_description="A pessoa cancelou.", state=pedido.state
        )
        return _voltar(destino)
    email = (form.get("email") or "").strip()
    try:
        limite.conferir(f"oauth:login:ip:{_ip(request)}", f"oauth:login:{email.lower()}", maximo=10, janela_segundos=600)
        destino = oauth_mcp.autorizar(db, pedido, email, form.get("senha") or "", endereco)
        db.commit()
    except MuitasTentativas:
        return _pagina_login(pedido, form["pedido"], email, limite.MENSAGEM)
    except ErroLogin as erro:
        db.rollback()
        return _pagina_login(pedido, form["pedido"], email, str(erro))
    log.info("OAuth MCP: %s autorizou o app %s", email, pedido.cliente.client_id[:60])
    return _voltar(destino)


# ---------- Token e revogação ----------


@router.post("/token")
async def token(request: Request, db: Session = Depends(get_db)):
    try:
        limite.conferir(f"oauth:token:{_ip(request)}", maximo=60, janela_segundos=600)
        form = await _form(request)
        saida = oauth_mcp.emitir(db, form, _basico(request))
        db.commit()
        return _json(saida)
    except MuitasTentativas:
        return _json({"error": "too_many_requests", "error_description": limite.MENSAGEM}, 429)
    except ErroOAuth as erro:
        db.rollback()
        return _erro(erro)


@router.post("/revogar")
async def revogar(request: Request, db: Session = Depends(get_db)):
    try:
        limite.conferir(f"oauth:revogar:{_ip(request)}", maximo=60, janela_segundos=600)
        form = await _form(request)
        oauth_mcp.revogar(db, form, _basico(request))
        db.commit()
        return _json({})
    except MuitasTentativas:
        return _json({"error": "too_many_requests", "error_description": limite.MENSAGEM}, 429)
    except ErroOAuth as erro:
        db.rollback()
        return _erro(erro)
