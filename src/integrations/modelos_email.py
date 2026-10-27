"""Textos dos e-mails do grupo (Casa Lorenzi e Vulto), num modelo único e neutro com as duas logos.
Cada função devolve o e-mail pronto (texto puro e HTML).

Os links levam ao site (URL_FRONTEND), não à API."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html import escape

from src.config.settings import URL_FRONTEND
from src.entities import fidelidade as regra_pontos
from src.integrations.email import Email


def _link(caminho: str) -> str:
    """caminho relativo do site (ex.: /login/nova-senha?token=...) → endereço completo."""
    return f"{URL_FRONTEND}{caminho}"


MARCAS = "Casa Lorenzi e Vulto"
RODAPE = "Casa Lorenzi · Vulto — uma conta, duas marcas, os mesmos pontos Lupe+."


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


def _reais(valor: Decimal) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pontos(quantidade: int) -> str:
    return f"{quantidade:,}".replace(",", ".")


def _regra_do_resgate() -> str:
    valor_100 = _reais(regra_pontos.valor_em_reais(regra_pontos.RESGATE_MULTIPLO))
    return (
        f"Para usar os pontos, faça o resgate no checkout do site: cada {regra_pontos.RESGATE_MULTIPLO} pontos valem "
        f"{valor_100} de desconto, em compras a partir de {_reais(regra_pontos.COMPRA_MINIMA_RESGATE)} em produtos."
    )


def aviso_pontos(
    email: str,
    nome: str,
    vencimentos: list[tuple[date, int]],
    saldo: int,
    categoria: str | None,
    proxima: tuple[str, int] | None,
) -> Email:
    """Aviso de serviço (decisão 82): quantos pontos vencem e quando, o saldo e a categoria. Sem oferta."""
    programa = regra_pontos.NOME_PROGRAMA
    total = sum(pontos for _, pontos in vencimentos)
    valor = _reais(regra_pontos.valor_em_reais(total))
    saudacao = f"Olá, {_primeiro_nome(nome)}."
    if len(vencimentos) == 1:
        dia, _ = vencimentos[0]
        assunto = f"{MARCAS} · {_pontos(total)} pontos {programa} vencem em {dia:%d/%m/%Y}"
        aviso = [f"Você tem {_pontos(total)} pontos {programa} ({valor} em desconto) que vencem em {dia:%d/%m/%Y}."]
    else:
        dias = regra_pontos.AVISO_VENCIMENTO_DIAS
        assunto = f"{MARCAS} · {_pontos(total)} pontos {programa} vencem nos próximos {dias} dias"
        aviso = [f"Você tem {_pontos(total)} pontos {programa} ({valor} em desconto) que vencem nos próximos {dias} dias:"]
        aviso += [f"{_pontos(pontos)} pontos em {dia:%d/%m/%Y}" for dia, pontos in vencimentos]
    situacao = f"Hoje o seu saldo é de {_pontos(saldo)} pontos ({_reais(regra_pontos.valor_em_reais(saldo))})"
    situacao += f", na categoria {categoria.capitalize()}." if categoria else "."
    if proxima:
        faltam = "Falta 1 ponto" if proxima[1] == 1 else f"Faltam {_pontos(proxima[1])} pontos"
        situacao += f" {faltam} para a categoria {proxima[0].capitalize()}."
    servico = f"Este é um aviso sobre a sua conta {programa}, que vale nas duas marcas."
    url = _link("/cliente/pontos")
    paragrafos = [saudacao, *aviso, situacao, _regra_do_resgate(), servico]
    return Email(
        para=email,
        assunto=assunto,
        texto="\n\n".join([*paragrafos, url]),
        html=_html([escape(p) for p in paragrafos], ("Ver meus pontos", url)),
    )


def aviso_pontos_sem_numeros(email: str, nome: str) -> Email:
    """O mesmo aviso para um e-mail que mais de uma conta usa (familiares): sem saldo nem quantidade, para os
    pontos de uma pessoa não aparecerem para outra (decisão 82)."""
    programa = regra_pontos.NOME_PROGRAMA
    saudacao = f"Olá, {_primeiro_nome(nome)}."
    aviso = f"Há pontos {programa} na sua conta que vencem nos próximos {regra_pontos.AVISO_VENCIMENTO_DIAS} dias."
    seguranca = (
        "Por segurança, este e-mail não mostra o saldo: este endereço está cadastrado em mais de uma conta. "
        "Entre na sua conta para ver quantos pontos são e quando vencem."
    )
    url = _link("/cliente/pontos")
    paragrafos = [saudacao, aviso, seguranca, _regra_do_resgate()]
    return Email(
        para=email,
        assunto=f"{MARCAS} · Há pontos {programa} vencendo na sua conta",
        texto="\n\n".join([*paragrafos, url]),
        html=_html([escape(p) for p in paragrafos], ("Ver meus pontos", url)),
    )


# ---------- Andamento do pedido (decisão 98) ----------


def pedido_enviado(email: str, nome: str, numero: str, codigo_rastreio: str) -> Email:
    url = _link("/cliente/pedidos")
    saudacao = f"Olá, {_primeiro_nome(nome)}."
    enviado = f"O seu pedido {numero} saiu para entrega."
    rastreio = f"Código de rastreio: {codigo_rastreio}."
    acompanhar = "Você acompanha a entrega na sua conta, em Meus pedidos."
    return Email(
        para=email,
        assunto=f"{MARCAS} · Pedido {numero} enviado",
        texto=f"{saudacao}\n\n{enviado}\n\n{rastreio}\n\n{acompanhar}\n\n{url}",
        html=_html(
            [
                escape(saudacao),
                escape(enviado),
                f"Código de rastreio: <strong>{escape(codigo_rastreio)}</strong>.",
                escape(acompanhar),
            ],
            ("Acompanhar pedido", url),
        ),
    )


def pedido_entregue(email: str, nome: str, numero: str) -> Email:
    url = _link("/cliente/pedidos")
    saudacao = f"Olá, {_primeiro_nome(nome)}."
    entregue = f"O seu pedido {numero} foi entregue. Esperamos que goste das peças."
    troca = "Se precisar trocar ou devolver alguma peça, você tem 30 dias a partir do recebimento: é só pedir em Meus pedidos."
    return Email(
        para=email,
        assunto=f"{MARCAS} · Pedido {numero} entregue",
        texto=f"{saudacao}\n\n{entregue}\n\n{troca}\n\n{url}",
        html=_html([escape(saudacao), escape(entregue), escape(troca)], ("Ver meus pedidos", url)),
    )


# ---------- "Avise-me quando chegar" e sacola (decisões 99 e 100) ----------


@dataclass(frozen=True)
class PecaEmail:
    nome: str
    cor: str
    tamanho: str
    preco: Decimal
    caminho: str
    quantidade: int = 1


def _linha_peca(peca: PecaEmail) -> str:
    quantidade = f"{peca.quantidade} × " if peca.quantidade > 1 else ""
    return f"{quantidade}{peca.nome} · {peca.cor} · {peca.tamanho} · {_reais(peca.preco)}"


def _pecas_html(pecas: list[PecaEmail]) -> list[str]:
    return [f'<a href="{escape(_link(p.caminho))}" style="color:#1c1d21">{escape(_linha_peca(p))}</a>' for p in pecas]


def peca_disponivel(email: str, nome: str, pecas: list[PecaEmail]) -> Email:
    """Aviso pedido pelo próprio cliente na página da peça (serviço, não marketing)."""
    saudacao = f"Olá, {_primeiro_nome(nome)}."
    if len(pecas) == 1:
        assunto = f"{MARCAS} · {pecas[0].nome} voltou ao estoque"
        chegou = "A peça que você pediu para ser avisado(a) voltou ao estoque do site:"
    else:
        assunto = f"{MARCAS} · {len(pecas)} peças voltaram ao estoque"
        chegou = "As peças que você pediu para ser avisado(a) voltaram ao estoque do site:"
    pressa = "O estoque é limitado e não fica reservado: garanta a sua pelo site."
    motivo = "Você recebeu este e-mail porque pediu o aviso na página da peça. Cada aviso é enviado uma vez."
    url = _link(pecas[0].caminho)
    linhas = [f"- {_linha_peca(p)}: {_link(p.caminho)}" for p in pecas]
    return Email(
        para=email,
        assunto=assunto,
        texto="\n\n".join([saudacao, chegou, *linhas, pressa, motivo]),
        html=_html([escape(saudacao), escape(chegou), *_pecas_html(pecas), escape(pressa), escape(motivo)], ("Ver a peça", url)),
    )


def lembrete_sacola(email: str, nome: str, pecas: list[PecaEmail], caminho_loja: str) -> Email:
    """Lembrete de sacola abandonada: só para quem aceita receber e-mails de marketing."""
    saudacao = f"Olá, {_primeiro_nome(nome)}."
    ficou = "Você deixou estas peças na sua sacola:"
    total = _reais(sum((p.preco * p.quantidade for p in pecas), Decimal(0)))
    resumo = f"Total das peças: {total}. Elas ainda estão disponíveis, mas o estoque não fica reservado."
    sair = "Para não receber mais lembretes como este, desligue os e-mails de novidades em Minha conta > Dados da conta."
    url = _link(f"{caminho_loja}?sacola=abrir")
    return Email(
        para=email,
        assunto=f"{MARCAS} · Suas peças estão esperando na sacola",
        texto="\n\n".join([saudacao, ficou, *[f"- {_linha_peca(p)}" for p in pecas], resumo, url, sair]),
        html=_html(
            [escape(saudacao), escape(ficou), *_pecas_html(pecas), escape(resumo), escape(sair)], ("Voltar para a sacola", url)
        ),
    )
