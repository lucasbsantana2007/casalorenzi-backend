"""Textos dos e-mails do grupo (Casa Lorenzi e Vulto), num modelo único e neutro com as duas logos.
Cada função devolve o e-mail pronto (texto puro e HTML).

Os links levam ao site (URL_FRONTEND), não à API."""

from decimal import Decimal
from html import escape

from src.config.settings import URL_FRONTEND
from src.integrations.email import Email


def _link(caminho: str) -> str:
    """caminho relativo do site (ex.: /login/nova-senha?token=...) → endereço completo."""
    return f"{URL_FRONTEND}{caminho}"


MARCAS = "Casa Lorenzi e Vulto"
RODAPE = "Casa Lorenzi · Vulto — uma conta, duas marcas, os mesmos pontos Vulto+."


def _html(paragrafos: list[str], botao: tuple[str, str] | None = None) -> str:
    """Modelo único das duas marcas: neutro (branco e grafite), com as duas logos no topo. As logos são
    imagens do site (public/email); se o programa de e-mail bloquear imagens, aparecem os nomes."""
    corpo = "".join(f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6">{p}</p>' for p in paragrafos)
    if botao:
        texto, url = botao
        corpo += (
            f'<p style="margin:28px 0"><a href="{escape(url)}" style="background:#1c1d21;color:#ffffff;'
            "padding:13px 24px;text-decoration:none;font-size:13px;letter-spacing:2px;text-transform:uppercase;"
            f'display:inline-block">{escape(texto)}</a></p>'
            f'<p style="margin:0 0 16px;font-size:12px;color:#8a8984">Se o botão não abrir, copie o endereço: {escape(url)}</p>'
        )
    logos = (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 32px"><tr>'
        f'<td style="padding-right:14px"><img src="{_link("/email/casa-lorenzi.png")}" alt="CASA LORENZI" height="30" '
        'style="display:block;height:30px;border:0;font-family:Georgia,serif;font-size:18px;letter-spacing:2px;color:#1c1d21"></td>'
        '<td style="border-left:1px solid #d6d3cc;padding-left:14px">'
        f'<img src="{_link("/email/vulto.png")}" alt="VULTO" height="18" '
        'style="display:block;height:18px;border:0;font-family:Arial,sans-serif;font-size:18px;font-weight:bold;color:#1c1d21"></td>'
        "</tr></table>"
    )
    return (
        '<div style="background:#f3f2ef;padding:32px 12px">'
        '<div style="max-width:560px;margin:0 auto;background:#ffffff;padding:36px 32px;'
        'font-family:Helvetica,Arial,sans-serif;color:#1c1d21">'
        f"{logos}{corpo}"
        '<p style="margin:32px 0 0;padding-top:16px;border-top:1px solid #ebeae7;font-size:12px;color:#8a8984">'
        f"{escape(RODAPE)}</p>"
        "</div></div>"
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
        assunto=f"{MARCAS} · Crie uma nova senha",
        texto=f"{saudacao}\n\n{pedido}\n\n{url}\n\n{aviso}",
        html=_html([escape(saudacao), escape(pedido), escape(aviso)], ("Criar nova senha", url)),
    )


def convite_funcionario(email: str, nome: str, cargo: str, caminho_link: str) -> Email:
    url = _link(caminho_link)
    saudacao = f"Olá, {_primeiro_nome(nome)}."
    convite = (
        f"Você foi cadastrado(a) no painel de gestão da Casa Lorenzi e da Vulto como {cargo}. "
        "Crie a sua senha de acesso pelo link abaixo."
    )
    validade = "O link vale por 7 dias e pode ser usado uma vez."
    return Email(
        para=email,
        assunto=f"{MARCAS} · Crie sua senha de acesso",
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
        assunto=f"{MARCAS} · Pedido {numero} confirmado",
        texto=f"{saudacao}\n\n{recebido}\n\n{acompanhar}\n\n{url}",
        html=_html([escape(saudacao), escape(recebido), escape(acompanhar)], ("Ver meus pedidos", url)),
    )
