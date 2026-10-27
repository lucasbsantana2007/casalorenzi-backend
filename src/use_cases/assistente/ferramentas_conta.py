"""Ferramentas da conta do cliente na Lúcia (decisão 93): detalhe do pedido, reembolsos e devoluções, extrato
de pontos, solicitações e frete por CEP. Só consultas: nada aqui grava (o extrato lança o vencimento dos pontos,
como a página Lupe+ já fazia). As ações (cancelar, devolver, trocar e-mail) são confirmadas pelo cliente e feitas
pelas rotas da conta, não pelo modelo.

Os dados pessoais saem sempre do cliente do token: nenhuma ferramenta recebe id ou CPF de cliente.
"""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from pydantic import Field
from sqlalchemy.orm import Session

from src import models as m
from src.entities import devolucao as regra_devolucao
from src.entities.atendimento import EM_ABERTO
from src.entities.frete import ROTULOS as ROTULO_FRETE
from src.entities.frete import somente_digitos, uf_do_cep
from src.entities.pedido import CANAL_LOJA
from src.repositories import atendimento_repository, pedido_repository
from src.use_cases import fidelidade
from src.use_cases import frete as frete_config
from src.use_cases.assistente.ferramentas import Contexto, Entrada, FalhaFerramenta, Ferramenta, Resultado
from src.use_cases.assistente.ferramentas_cliente import ROTULO_STATUS_PEDIDO, SemParametros, _cliente
from src.use_cases.assistente.formatacao import brl, data, numero
from src.utils.datas import agora, ms

ROTULO_PAGAMENTO = {
    "APROVADO": "aprovado",
    "ESTORNADO": "estornado (valor devolvido)",
    "PENDENTE": "aguardando pagamento",
    "CHARGEBACK": "contestado no cartão",
}
ROTULO_METODO = {"PIX": "PIX", "CARTAO": "cartão de crédito", "DEBITO": "cartão de débito", "DINHEIRO": "dinheiro"}
ROTULO_ATENDIMENTO = {
    "ABERTO": "aberta, aguardando a equipe",
    "EM_ANDAMENTO": "em andamento",
    "AGUARDANDO_CLIENTE": "a equipe respondeu e aguarda você",
    "CONCLUIDO": "concluída",
}
ROTULO_MOVIMENTO = {
    "SALDO_INICIAL": "Saldo trazido da Vulto",
    "CREDITO": "Pontos de compra",
    "RESGATE": "Usados no checkout",
    "ESTORNO": "Estorno de compra cancelada",
    "AJUSTE": "Ajuste",
    "VENCIMENTO": "Pontos vencidos",
}
EXTRATO_LINHAS = 10


def _peca(variacao) -> str:
    return f"{variacao.produto.nome} ({variacao.cor}, {variacao.tamanho})"


def recebido_em(pedido: m.Pedido) -> datetime | None:
    """Quando o cliente recebeu: o evento de entrega; sem ele, a data do pedido para pedido entregue."""
    entrega = next((e for e in reversed(pedido.eventos) if e.status == "ENTREGUE"), None)
    if entrega is not None:
        return entrega.criado_em
    return pedido.criado_em if pedido.status == "ENTREGUE" else None


def prazo_devolucao(pedido: m.Pedido) -> datetime | None:
    """Último dia para pedir a devolução (30 dias do recebimento); None se ainda não foi entregue."""
    recebido = recebido_em(pedido)
    return recebido + timedelta(days=regra_devolucao.PRAZO_DEVOLUCAO_DIAS) if recebido else None


def pedido_do_cliente(db: Session, cliente: m.Cliente, numero_pedido: str) -> m.Pedido:
    """Aceita "CL-105093", "cl-105093" ou só "105093"; só entre os pedidos do próprio cliente."""
    texto = (numero_pedido or "").strip().upper()
    if not texto:
        raise FalhaFerramenta("PEDIDO_NAO_INFORMADO: pergunte o número do pedido ou consulte os pedidos do cliente.")
    pedido = pedido_repository.do_cliente_por_numero(db, cliente.id, texto)
    if pedido is None:
        digitos = somente_digitos(texto)
        candidatos = [p for p in pedido_repository.do_cliente(db, cliente.id) if digitos and somente_digitos(p.numero) == digitos]
        pedido = pedido_repository.do_cliente_por_numero(db, cliente.id, candidatos[0].numero) if candidatos else None
    if pedido is None:
        raise FalhaFerramenta(f"PEDIDO_NAO_ENCONTRADO: o pedido {texto} não está entre os pedidos desta conta.")
    return pedido


# ---------- ver_pedido ----------


class VerPedido(Entrada):
    numero_pedido: str = Field(max_length=30, description="Número do pedido, como CL-105093.")


def ver_pedido(db: Session, ctx: Contexto, entrada: VerPedido) -> Resultado:
    cliente = _cliente(db, ctx)
    pedido = pedido_do_cliente(db, cliente, entrada.numero_pedido)
    status = ROTULO_STATUS_PEDIDO.get(pedido.status, pedido.status)
    pagamento = pedido.pagamentos[-1] if pedido.pagamentos else None
    devolucoes = [d for item in pedido.itens for d in item.devolucoes]
    prazo = prazo_devolucao(pedido)
    pode_devolver = (
        regra_devolucao.aceita_devolucao(pedido.status) and prazo is not None and agora() <= prazo and pedido.canal != CANAL_LOJA
    )
    frete = None
    if pedido.frete_tipo:
        valor = "grátis" if not pedido.frete_valor else brl(pedido.frete_valor)
        frete = f"{ROTULO_FRETE.get(pedido.frete_tipo, pedido.frete_tipo)}, {valor}" + (
            f", até {pedido.frete_prazo_dias} dias úteis" if pedido.frete_prazo_dias else ""
        )
    dados = {
        "numero": pedido.numero,
        "data": data(pedido.criado_em),
        "status": status,
        "canal": pedido.canal,
        "itens": [{"peca": _peca(i.variacao), "quantidade": i.quantidade, "preco": brl(i.preco_unitario)} for i in pedido.itens],
        "subtotal": brl(pedido.subtotal),
        "desconto": brl(pedido.desconto) if pedido.desconto else None,
        "frete": frete,
        "total": brl(pedido.total),
        "pagamento": (
            f"{ROTULO_METODO.get(pagamento.metodo, pagamento.metodo)}"
            + (f" em {pagamento.parcelas}x" if pagamento.parcelas and pagamento.parcelas > 1 else "")
            + f", {ROTULO_PAGAMENTO.get(pagamento.status, pagamento.status.lower())}"
        )
        if pagamento
        else None,
        "rastreio": pedido.codigo_rastreio,
        "entregaEm": f"{pedido.entrega_cidade}/{pedido.entrega_uf}" if pedido.entrega_cidade else None,
        "historico": [
            {"data": data(e.criado_em), "status": ROTULO_STATUS_PEDIDO.get(e.status, e.status)} for e in pedido.eventos[-5:]
        ],
        "devolucoes": [
            {"data": data(d.criada_em), "peca": _peca(d.variacao), "quantidade": d.quantidade, "valor": brl(d.valor_devolvido)}
            for d in devolucoes
        ],
        "podeCancelar": pedido.status == "PROCESSANDO",
        "podeDevolver": pode_devolver,
        "devolucaoAte": data(prazo) if pode_devolver else None,
    }
    bloco = {
        "tipo": "pedido_detalhe",
        "numero": pedido.numero,
        "data": ms(pedido.criado_em),
        "status": pedido.status,
        "statusRotulo": status,
        "itens": [
            {
                "nome": i.variacao.produto.nome,
                "cor": i.variacao.cor,
                "tamanho": i.variacao.tamanho,
                "quantidade": i.quantidade,
                "preco": float(i.preco_unitario),
            }
            for i in pedido.itens
        ],
        "frete": dados["frete"],
        "desconto": float(pedido.desconto or 0),
        "total": float(pedido.total),
        "pagamento": dados["pagamento"],
        "rastreio": pedido.codigo_rastreio,
        "devolucoes": dados["devolucoes"],
        "link": "/cliente/pedidos",
    }
    texto = f"Pedido {pedido.numero} ({dados['data']}): {status.lower()}, total de {dados['total']}."
    if pedido.codigo_rastreio:
        texto += f" Código de rastreio: {pedido.codigo_rastreio}."
    if devolucoes:
        texto += f" Tem {len(devolucoes)} devolução(ões) registrada(s)."
    return Resultado(dados=dados, blocos=[bloco], memoria={"pedidoEmFoco": pedido.numero}, texto=texto)


# ---------- consultar_reembolsos ----------


def consultar_reembolsos(db: Session, ctx: Contexto, entrada: SemParametros) -> Resultado:
    cliente = _cliente(db, ctx)
    pedidos = pedido_repository.do_cliente(db, cliente.id)
    devolucoes = [
        {
            "pedido": p.numero,
            "data": data(d.criada_em),
            "peca": _peca(d.variacao),
            "quantidade": d.quantidade,
            "valor": brl(d.valor_devolvido),
            "situacao": "devolução recebida e valor reembolsado",
        }
        for p in pedidos
        for item in p.itens
        for d in item.devolucoes
    ]
    estornos = [
        {
            "pedido": p.numero,
            "data": data(pg.atualizado_em),
            "valor": brl(pg.valor),
            "situacao": "pedido cancelado e pagamento estornado",
        }
        for p in pedidos
        for pg in p.pagamentos
        if p.status == "CANCELADO" and pg.status == "ESTORNADO"
    ]
    em_analise = [
        {
            "protocolo": a.protocolo,
            "pedido": a.pedido.numero if a.pedido else a.pedido_citado,
            "assunto": a.tipo_solicitacao.titulo,
            "situacao": ROTULO_ATENDIMENTO.get(a.status, a.status),
        }
        for a in atendimento_repository.do_cliente(db, cliente.id)
        if a.status in EM_ABERTO and (a.pedido_id or a.pedido_citado)
    ]
    dados = {"devolucoes": devolucoes[:10], "estornos": estornos[:10], "emAnalise": em_analise[:10]}
    if not (devolucoes or estornos or em_analise):
        texto = (
            "Não encontrei reembolso, estorno nem devolução em andamento na sua conta. Se quiser devolver uma peça, "
            "me diga o número do pedido."
        )
    else:
        partes = []
        if em_analise:
            a = em_analise[0]
            partes.append(f"a solicitação {a['protocolo']} ({a['assunto']}) está {a['situacao']}")
        if devolucoes:
            d = devolucoes[0]
            partes.append(f"a devolução do pedido {d['pedido']} foi registrada em {d['data']}, com {d['valor']} reembolsados")
        if estornos:
            e = estornos[0]
            partes.append(f"o pedido {e['pedido']} foi cancelado e {e['valor']} foram estornados em {e['data']}")
        texto = "Encontrei na sua conta: " + "; ".join(partes) + "."
    return Resultado(dados=dados, blocos=[{"tipo": "reembolsos", **dados, "link": "/cliente/solicitacoes"}], texto=texto)


# ---------- consultar_extrato_pontos ----------


def consultar_extrato_pontos(db: Session, ctx: Contexto, entrada: SemParametros) -> Resultado:
    cliente = _cliente(db, ctx)
    resumo = fidelidade.resumo(db, cliente)  # a mesma conta da página Lupe+ (lança o vencimento, se houver)
    movimentos = list(reversed(resumo.movimentos))[:EXTRATO_LINHAS]
    linhas = [
        {
            "data": data(mov.criado_em),
            "tipo": ROTULO_MOVIMENTO.get(mov.tipo, mov.tipo),
            "pontos": f"{'+' if mov.quantidade > 0 else ''}{numero(mov.quantidade)}",
            "detalhe": (mov.pedido.numero if mov.pedido else (mov.obs or ""))[:80],
            "saldo": numero(mov.saldo_resultante),
        }
        for mov in movimentos
    ]
    dados = {
        "saldo": numero(resumo.saldo),
        "valorEmReais": brl(resumo.valor_em_reais),
        "extrato": linhas,
        "proximosVencimentos": [{"data": data(d), "pontos": numero(p)} for d, p in resumo.a_vencer],
    }
    if not linhas:
        texto = "Ainda não há movimentos de pontos Lupe+ na sua conta."
    else:
        ultimo = linhas[0]
        texto = (
            f"Seu saldo é de {dados['saldo']} pontos Lupe+ ({dados['valorEmReais']}). O último movimento foi em "
            f"{ultimo['data']}: {ultimo['tipo'].lower()} ({ultimo['pontos']} pontos)."
        )
    bloco = {
        "tipo": "extrato",
        "saldo": resumo.saldo,
        "itens": [
            {"data": ms(mov.criado_em), "tipo": ROTULO_MOVIMENTO.get(mov.tipo, mov.tipo), "pontos": mov.quantidade}
            for mov in movimentos
        ],
        "link": "/cliente/pontos",
    }
    return Resultado(dados=dados, blocos=[bloco], texto=texto)


# ---------- consultar_minhas_solicitacoes ----------


def consultar_minhas_solicitacoes(db: Session, ctx: Contexto, entrada: SemParametros) -> Resultado:
    cliente = _cliente(db, ctx)
    chamados = atendimento_repository.do_cliente(db, cliente.id)[:5]
    itens = [
        {
            "protocolo": a.protocolo,
            "assunto": a.tipo_solicitacao.titulo,
            "situacao": ROTULO_ATENDIMENTO.get(a.status, a.status),
            "pedido": a.pedido.numero if a.pedido else a.pedido_citado,
            "abertaEm": data(a.criado_em),
            "atualizadaEm": data(a.atualizado_em),
        }
        for a in chamados
    ]
    if not itens:
        texto = "Você não tem solicitações abertas com a equipe."
    else:
        a = itens[0]
        texto = f"Sua solicitação mais recente é a {a['protocolo']} ({a['assunto']}): {a['situacao']}."
    blocos = [
        {
            "tipo": "solicitacoes",
            "itens": [{**i, "link": f"/cliente/solicitacoes/{c.id}"} for i, c in zip(itens, chamados, strict=True)],
        }
    ]
    return Resultado(dados={"solicitacoes": itens}, blocos=blocos if itens else [], texto=texto)


# ---------- calcular_frete ----------


class CalcularFrete(Entrada):
    cep: str = Field(max_length=12, description="CEP de entrega, com ou sem traço.")
    valor_produtos: float | None = Field(None, ge=0, description="Valor das peças em reais, se o cliente disse.")


def calcular_frete(db: Session, ctx: Contexto, entrada: CalcularFrete) -> Resultado:
    cep = somente_digitos(entrada.cep)
    if len(cep) != 8:
        raise FalhaFerramenta("CEP_INVALIDO: o CEP precisa ter 8 dígitos. Peça o CEP de novo.")
    try:
        valor = Decimal(str(entrada.valor_produtos or 0))
    except InvalidOperation:
        valor = Decimal("0")
    opcoes = frete_config.opcoes(db, cep, valor)
    if not opcoes:
        raise FalhaFerramenta("CEP_NAO_ATENDIDO: não entregamos nesse CEP pelo site.")
    condicoes = frete_config.condicoes(db)
    gratis = condicoes.get("gratisMinimo") if isinstance(condicoes, dict) else None
    lista = [
        {
            "tipo": ROTULO_FRETE.get(o.tipo, o.tipo),
            "valor": "grátis" if not o.valor else brl(o.valor),
            "prazo": f"até {o.prazo_dias} dias úteis",
        }
        for o in opcoes
    ]
    cep_formatado = f"{cep[:5]}-{cep[5:]}"
    dados = {"cep": cep_formatado, "uf": uf_do_cep(cep), "opcoes": lista, "freteGratisAPartirDe": brl(gratis) if gratis else None}
    if entrada.valor_produtos is None:
        dados["observacao"] = "Valores para compras abaixo do frete grátis; o checkout recalcula com a sacola."
    texto = f"Para o CEP {cep_formatado}: " + "; ".join(f"{o['tipo']} {o['valor']}, {o['prazo']}" for o in lista) + "."
    if gratis:
        texto += f" Frete grátis em compras a partir de {brl(gratis)}."
    bloco = {"tipo": "frete", "cep": cep_formatado, "opcoes": lista, "freteGratisAPartirDe": dados["freteGratisAPartirDe"]}
    return Resultado(dados=dados, blocos=[bloco], texto=texto)


FERRAMENTAS = [
    Ferramenta(
        "ver_pedido",
        "Detalhe de um pedido do cliente logado: peças, valores, frete, pagamento, rastreio, histórico, devoluções e se "
        "ainda dá para cancelar (podeCancelar) ou devolver (podeDevolver, devolucaoAte). Use para status, rastreio ou "
        "dúvidas sobre um pedido. Sem login, devolve LOGIN_NECESSARIO.",
        VerPedido,
        ver_pedido,
        exige_cliente=True,
    ),
    Ferramenta(
        "consultar_reembolsos",
        "Reembolsos, estornos e devoluções do cliente logado: devoluções registradas (com o valor reembolsado), pedidos "
        "cancelados com estorno e solicitações de devolução ou troca ainda em análise. Use para 'cadê meu reembolso', "
        "'meu estorno', 'minha devolução'. Sem login, devolve LOGIN_NECESSARIO.",
        SemParametros,
        consultar_reembolsos,
        exige_cliente=True,
    ),
    Ferramenta(
        "consultar_extrato_pontos",
        "Extrato de pontos Lupe+ do cliente logado: os últimos movimentos (compras, resgates, estornos, vencimentos) e o "
        "saldo depois de cada um. Use quando o cliente quer saber para onde foram os pontos. Sem login, devolve "
        "LOGIN_NECESSARIO.",
        SemParametros,
        consultar_extrato_pontos,
        exige_cliente=True,
        escrita=True,
    ),
    Ferramenta(
        "consultar_minhas_solicitacoes",
        "As 5 solicitações mais recentes do cliente logado com a equipe (protocolo, assunto, situação, pedido). Use para "
        "'minha solicitação foi respondida?'. Sem login, devolve LOGIN_NECESSARIO.",
        SemParametros,
        consultar_minhas_solicitacoes,
        exige_cliente=True,
    ),
    Ferramenta(
        "calcular_frete",
        "Valor e prazo do frete do site para um CEP (Padrão e Expresso), com o mínimo para frete grátis. Não precisa de "
        "login. Se o cliente não disse o CEP, pergunte.",
        CalcularFrete,
        calcular_frete,
    ),
]
