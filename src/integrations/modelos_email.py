"""Textos dos e-mails da Casa Lorenzi. Cada função devolve o e-mail pronto (texto puro e HTML).

Os links levam ao site (URL_FRONTEND), não à API."""

from decimal import Decimal
from html import escape

from src.config.settings import URL_FRONTEND
from src.integrations.email import Email


def _link(caminho: str) -> str:
    """caminho relativo do site (ex.: /login/nova-senha?token=...) → endereço completo."""
    return f"{URL_FRONTEND}{caminho}"


def _html(paragrafos: list[str], botao: tuple[str, str] | None = None) -> str:
    corpo = "".join(f'<p style="margin:0 0 16px">{p}</p>' for p in paragrafos)
    if botao:
        texto, url = botao
        corpo += (
            f'<p style="margin:24px 0"><a href="{escape(url)}" style="background:#1f2a44;color:#fff;'
            f'padding:12px 20px;text-decoration:none;border-radius:4px">{escape(texto)}</a></p>'
            f'<p style="margin:0 0 16px;font-size:13px;color:#666">Se o botão não abrir, copie o endereço: {escape(url)}</p>'
        )
    return (
        '<div style="font-family:Georgia,serif;color:#1f2a44;max-width:560px;margin:0 auto;padding:24px">'
        f'<p style="font-size:20px;letter-spacing:2px;margin:0 0 24px">CASA LORENZI</p>{corpo}</div>'
    )


def _primeiro_nome(nome: str) -> str:
    return (nome or "").split(" ")[0] or "olá"


def nova_senha(email: str, nome: str, caminho_link: str) -> Email:
    url = _link(caminho_link)
    saudacao = f"Olá, {_primeiro_nome(nome)}."
    pedido = "Recebemos um pedido para trocar a sua senha. Para criar uma nova, use o link abaixo. Ele vale por 30 minutos."
    aviso = "Se não foi você, ignore este e-mail: a sua senha continua a mesma."
    return Email(
        para=email,
        assunto="Casa Lorenzi · Crie uma nova senha",
        texto=f"{saudacao}\n\n{pedido}\n\n{url}\n\n{aviso}",
        html=_html([escape(saudacao), escape(pedido), escape(aviso)], ("Criar nova senha", url)),
    )


def convite_funcionario(email: str, nome: str, cargo: str, caminho_link: str) -> Email:
    url = _link(caminho_link)
    saudacao = f"Olá, {_primeiro_nome(nome)}."
    convite = f"Você foi cadastrado(a) no painel da Casa Lorenzi como {cargo}. Crie a sua senha de acesso pelo link abaixo."
    validade = "O link vale por 7 dias e pode ser usado uma vez."
    return Email(
        para=email,
        assunto="Casa Lorenzi · Crie sua senha de acesso",
        texto=f"{saudacao}\n\n{convite}\n\n{url}\n\n{validade}",
        html=_html([escape(saudacao), escape(convite), escape(validade)], ("Criar minha senha", url)),
    )


def pedido_confirmado(email: str, nome: str, numero: str, total: Decimal) -> Email:
    url = _link("/cliente/pedidos")
    valor = f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    saudacao = f"Olá, {_primeiro_nome(nome)}."
    recebido = f"Recebemos o seu pedido {numero} ({valor}). O pagamento foi aprovado e já estamos separando as peças."
    acompanhar = (
        "Para acompanhar a entrega e pedir trocas, devoluções ou ajuda, entre na sua conta com este e-mail e a sua senha."
    )
    return Email(
        para=email,
        assunto=f"Casa Lorenzi · Pedido {numero} confirmado",
        texto=f"{saudacao}\n\n{recebido}\n\n{acompanhar}\n\n{url}",
        html=_html([escape(saudacao), escape(recebido), escape(acompanhar)], ("Ver meus pedidos", url)),
    )
