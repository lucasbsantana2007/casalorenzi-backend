"""Ferramentas da conta do cliente na Lúcia (decisão 93): detalhe do pedido, reembolsos e devoluções, extrato
de pontos, solicitações e frete por CEP. Só consultas: nada aqui grava (o extrato lança o vencimento dos pontos,
como a página Lupe+ já fazia). As ações (cancelar, devolver, trocar e-mail) são confirmadas pelo cliente e feitas
pelas rotas da conta, não pelo modelo.

Os dados pessoais saem sempre do cliente do token: nenhuma ferramenta recebe id ou CPF de cliente.
"""

from decimal import Decimal, InvalidOperation

from pydantic import Field
from sqlalchemy.orm import Session

from src import models as m
from src.entities.atendimento import EM_ABERTO
from src.entities.cliente import email_valido, normalizar_email
from src.entities.frete import ROTULOS as ROTULO_FRETE
from src.entities.frete import somente_digitos, uf_do_cep
from src.repositories import atendimento_repository, pedido_repository
from src.use_cases import fidelidade, pedidos_cliente
from src.use_cases import frete as frete_config
from src.use_cases.assistente.ferramentas import Contexto, Entrada, FalhaFerramenta, Ferramenta, Resultado
from src.use_cases.assistente.ferramentas_cliente import ROTULO_STATUS_PEDIDO, SemParametros, _cliente
from src.use_cases.assistente.formatacao import brl, data, numero
from src.utils.datas import ms

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


def pedido_do_cliente(db: Session, cliente: m.Cliente, numero_pedido: str) -> m.Pedido:
    """Aceita "CL-105093", "cl-105093" ou só "105093"; só entre os pedidos do próprio cliente."""
    texto = (numero_pedido or "").strip().upper()
    if not texto:
        raise FalhaFerramenta("PEDIDO_NAO_INFORMADO: qual é o número do pedido? Ele aparece em Minha conta > Pedidos.")
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
    prazo = pedidos_cliente.prazo_devolucao(pedido)
    pode_devolver = pedidos_cliente.pode_pedir_devolucao(pedido)
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


# ---------- Ações com confirmação (decisões 95, 96 e 97) ----------
# A ferramenta só confere e monta o cartão; a ação acontece quando o cliente confirma no cartão, pelas rotas da
# conta (a senha do e-mail vai direto para /conta, nunca para a conversa nem para o modelo).

CONFIRMAR = "Nada foi feito ainda: a ação só acontece quando o cliente confirma no cartão. Não diga que já foi feita."


class TrocarEmail(Entrada):
    novo_email: str = Field(max_length=255, description="O e-mail novo que o cliente quer na conta.")


def trocar_meu_email(db: Session, ctx: Contexto, entrada: TrocarEmail) -> Resultado:
    cliente = _cliente(db, ctx)
    novo = normalizar_email(entrada.novo_email)
    if not email_valido(novo):
        raise FalhaFerramenta("EMAIL_INVALIDO: o e-mail informado não é válido. Peça para o cliente conferir.")
    if novo == normalizar_email(cliente.email):
        raise FalhaFerramenta("MESMO_EMAIL: esse já é o e-mail da conta.")
    texto = (
        f"Para trocar o e-mail da sua conta para {novo}, confirme com a sua senha atual no cartão abaixo. "
        "A senha vai direto para a sua conta, não para mim."
    )
    return Resultado(
        dados={"emailNovo": novo, "importante": CONFIRMAR},
        blocos=[{"tipo": "confirmar_email", "estado": "PENDENTE", "emailNovo": novo}],
        texto=texto,
    )


class NumeroDoPedido(Entrada):
    numero_pedido: str = Field(max_length=30, description="Número do pedido, como CL-105093.")


def cancelar_pedido(db: Session, ctx: Contexto, entrada: NumeroDoPedido) -> Resultado:
    cliente = _cliente(db, ctx)
    pedido = pedido_do_cliente(db, cliente, entrada.numero_pedido)
    if pedido.status == "CANCELADO":
        raise FalhaFerramenta(f"JA_CANCELADO: o pedido {pedido.numero} já está cancelado.")
    if pedido.status != "PROCESSANDO":
        raise FalhaFerramenta(
            f"NAO_CANCELAVEL: o pedido {pedido.numero} já saiu para entrega e não pode ser cancelado. Quando ele chegar, dá para pedir a devolução."
        )
    texto = (
        f"Posso cancelar o pedido {pedido.numero}, de {brl(pedido.total)}. O pagamento é estornado e os pontos usados "
        "voltam para a sua conta. Confirme no cartão abaixo."
    )
    bloco = {
        "tipo": "confirmar_cancelamento",
        "estado": "PENDENTE",
        "numero": pedido.numero,
        "total": float(pedido.total),
        "itens": [f"{_peca(i.variacao)} x{i.quantidade}" for i in pedido.itens],
    }
    return Resultado(
        dados={"pedido": pedido.numero, "total": brl(pedido.total), "importante": CONFIRMAR},
        blocos=[bloco],
        memoria={"pedidoEmFoco": pedido.numero},
        texto=texto,
    )


class SolicitarDevolucao(Entrada):
    numero_pedido: str = Field(max_length=30, description="Número do pedido, como CL-105093.")
    motivo: str = Field("", max_length=300, description="O motivo com as palavras do cliente (ex.: ficou grande).")


def solicitar_devolucao(db: Session, ctx: Contexto, entrada: SolicitarDevolucao) -> Resultado:
    cliente = _cliente(db, ctx)
    pedido = pedido_do_cliente(db, cliente, entrada.numero_pedido)
    if pedido.status == "PROCESSANDO":
        raise FalhaFerramenta(
            f"AINDA_NAO_ENVIADO: o pedido {pedido.numero} ainda não saiu para entrega: dá para cancelar em vez de devolver."
        )
    if not pedidos_cliente.pode_pedir_devolucao(pedido):
        raise FalhaFerramenta(
            f"FORA_DO_PRAZO: o pedido {pedido.numero} não aceita mais devolução (o prazo é de 30 dias do recebimento). "
            "Posso chamar alguém da equipe para ver o seu caso."
        )
    pecas = [
        {
            "itemPedidoId": i.id,
            "nome": i.variacao.produto.nome,
            "cor": i.variacao.cor,
            "tamanho": i.variacao.tamanho,
            "quantidade": pedidos_cliente.devolvivel(i),
            "preco": float(i.preco_unitario),
        }
        for i in pedido.itens
        if pedidos_cliente.devolvivel(i) > 0
    ]
    if not pecas:
        raise FalhaFerramenta(f"NADA_A_DEVOLVER: as peças do pedido {pedido.numero} já foram devolvidas.")
    prazo = pedidos_cliente.prazo_devolucao(pedido)
    texto = (
        f"Separei a devolução do pedido {pedido.numero}. Marque as peças, confira o motivo e confirme no cartão. "
        "A equipe confere a peça e faz o reembolso."
    )
    bloco = {
        "tipo": "confirmar_devolucao",
        "estado": "PENDENTE",
        "numero": pedido.numero,
        "prazoAte": data(prazo),
        "motivo": entrada.motivo.strip(),
        "pecas": pecas,
    }
    return Resultado(
        dados={"pedido": pedido.numero, "prazoAte": data(prazo), "pecas": len(pecas), "importante": CONFIRMAR},
        blocos=[bloco],
        memoria={"pedidoEmFoco": pedido.numero},
        texto=texto,
    )


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
    Ferramenta(
        "trocar_meu_email",
        "Prepara a troca do e-mail da conta do cliente logado: mostra um cartão em que o cliente confirma com a senha "
        "atual (a senha não passa por você). Use quando o cliente pedir para trocar o e-mail e disser o novo. Sem "
        "login, devolve LOGIN_NECESSARIO.",
        TrocarEmail,
        trocar_meu_email,
        exige_cliente=True,
    ),
    Ferramenta(
        "cancelar_pedido",
        "Prepara o cancelamento de um pedido do cliente logado que ainda está em separação: mostra o cartão de "
        "confirmação (o pagamento é estornado e os pontos usados voltam). Pedido já enviado não cancela: ofereça a "
        "devolução. Sem login, devolve LOGIN_NECESSARIO.",
        NumeroDoPedido,
        cancelar_pedido,
        exige_cliente=True,
    ),
    Ferramenta(
        "solicitar_devolucao",
        "Prepara o pedido de devolução de um pedido do cliente logado (enviado ou entregue, até 30 dias do "
        "recebimento): mostra o cartão com as peças para marcar e o motivo. A equipe confere a peça e faz o reembolso. "
        "Sem login, devolve LOGIN_NECESSARIO.",
        SolicitarDevolucao,
        solicitar_devolucao,
        exige_cliente=True,
    ),
]
