"""Domínio vendas: vendas + itens_venda da Vulto viram pedidos, itens, pagamentos e devoluções.

Decisões (aprovadas, parametrizáveis aqui ou em src/entities/pedido.py):
- Canal pela loja do legado (1–4 loja física, 5 site, 6 app), nunca pelo texto. O pedido online fica
  com o CD Cajamar; o ship from store (obs "sfs pinheiros"...), com Pinheiros.
- Valores: o app grava centavos no total e nos itens; a escala certa é a que faz o preço dos itens
  bater com o do catálogo (as duas escalas fecham a conta da venda). Frete que o app embutiu no total
  e desconto não registrado saem da conta da venda.
- Status pelo mapeamento de normalizacao.STATUS_POR_TEXTO; vazio (949 vendas de lojas físicas em
  jan–fev/25, todas com itens e conta fechando) = pago.
- Troca lançada como venda nova = pedido TROCA: baixa o estoque, mas não é receita.
- Valor negativo = devolução, ligada à venda original pela referência da obs ("dev pedido 674"), ou
  pela última compra do mesmo cliente com a mesma peça, ou sem origem.
- Fora: vendas de teste (TI/QA) e a duplicata do app (o mesmo pedido externo enviado duas vezes).
- Batel em março (PDV fora de 02 a 22/03/26): a planilha manual entra, menos o que a gerente relançou
  no sistema (mesmo CPF e valor); o relançado volta para a data da venda.
"""

import json
import re
import statistics
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from difflib import get_close_matches

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from src import models as m
from src.entities.pagamento import METODO_PADRAO_POR_CANAL
from src.entities.pedido import CANAL_APP, CANAL_LOJA, CANAL_SITE
from src.migracao_vulto import lojas as lojas_vulto
from src.migracao_vulto import normalizacao as n
from src.migracao_vulto import produtos as produtos_vulto
from src.migracao_vulto.relatorio import Resultado
from src.repositories import migracao_repository

DOMINIO = "vendas"
ORIGEM_VENDAS = "vulto.db:vendas"
ORIGEM_COMPRAS = "vulto.db:compras"
ORIGEM_BATEL = "vendas_batel_MANUAL_marco.xlsx:MARÇO"
PREFIXO = "VLT-"

STATUS_VAZIO = ("ENTREGUE", "APROVADO")
TERMOS_TROCA = ("troca",)
TERMOS_SFS = ("sfs", "saiu da loja pinheiros")
TERMO_RETROATIVO = "lancamento retroativo"
SKUS_TESTE = {"TESTE-001"}
JANELA_DEVOLUCAO = timedelta(days=180)  # devolução sem referência: compra do mesmo cliente até 180 dias antes
TOLERANCIA = Decimal("0.02")
# Escala: preço do item ÷ preço do catálogo entre esses limites (descontos de até 70% e reajustes)
RAZAO_CATALOGO = (Decimal("0.3"), Decimal("1.6"))

BATEL_INICIO, BATEL_FIM = date(2026, 3, 2), date(2026, 3, 22)
METODO_BATEL = {
    "pix": ("PIX", 1),
    "credito": ("CARTAO", 1),
    "credito 2x": ("CARTAO", 2),
    "debito": ("DEBITO", 1),
    "dinheiro": ("DINHEIRO", 1),
}


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower().strip()


# ---------- Leitura ----------


@dataclass
class ItemLegado:
    id: int
    sku: str
    descricao: str | None
    qtd: int
    preco: str


@dataclass
class VendaLegado:
    id: int
    pedido_externo: str | None
    canal_texto: str | None
    loja: int
    cliente_ref: str | None
    total: str
    desconto: str | None
    frete: str | None
    status: str | None
    criado_em: str
    obs: str
    compra_id: int | None
    itens: list[ItemLegado] = field(default_factory=list)

    @property
    def obs_chave(self) -> str:
        return _sem_acento(self.obs)


def ler_vendas(db: Session) -> list[VendaLegado]:
    vendas = {}
    for r in db.execute(text("SELECT * FROM legado_vulto.db__vendas ORDER BY id::int")).mappings():
        vendas[int(r["id"])] = VendaLegado(
            int(r["id"]),
            r["pedido_externo"],
            r["canal"],
            int(r["loja_id"]),
            r["cliente_ref"],
            r["total"],
            r["desconto"],
            r["frete"],
            r["status"],
            r["criado_em"],
            (r["obs"] or "").strip(),
            int(r["compra_id"]) if r["compra_id"] else None,
        )
    for r in db.execute(text("SELECT * FROM legado_vulto.db__itens_venda ORDER BY id::int")).mappings():
        vendas[int(r["venda_id"])].itens.append(
            ItemLegado(int(r["id"]), r["sku"], r["descricao"], int(r["qtd"]), r["preco_unit"])
        )
    return list(vendas.values())


# ---------- Catálogo: grafia → variação ----------


class Catalogo:
    """Resolve grafias de SKU (com a vigência do código reaproveitado) e dá o preço de catálogo."""

    def __init__(self, db: Session):
        self.aliases: dict[str, list[tuple[int, date | None, date | None]]] = defaultdict(list)
        for normal, variacao_id, de, ate in db.execute(
            select(m.SkuAlias.alias_normalizado, m.SkuAlias.variacao_id, m.SkuAlias.valido_de, m.SkuAlias.valido_ate)
        ):
            self.aliases[normal].append((variacao_id, de, ate))
        self.preco: dict[int, Decimal] = {}
        self.produto: dict[int, int] = {}
        for variacao_id, produto_id, preco in db.execute(
            select(m.Variacao.id, m.Variacao.produto_id, m.Produto.preco_base).join(m.Produto)
        ):
            self.preco[variacao_id], self.produto[variacao_id] = preco, produto_id
        self.nao_catalogado = db.scalar(select(m.Variacao.id).where(m.Variacao.sku == produtos_vulto.SKU_NAO_CATALOGADO))

    def variacao(self, grafia: str, dia: date) -> int | None:
        candidatos = self.aliases.get(n.alias_normalizado(grafia), [])
        validos = [v for v, de, ate in candidatos if (de or dia) <= dia <= (ate or dia)]
        return validos[0] if validos else None


# ---------- Transformação ----------


@dataclass
class Plano:
    """O que a venda do legado vira na plataforma."""

    venda: VendaLegado
    destino: str = "PEDIDO"  # PEDIDO, DEVOLUCAO ou DESCARTADA
    momento: datetime | None = None
    escala: str = "reais"
    total: Decimal = Decimal("0")
    subtotal: Decimal = Decimal("0")
    desconto: Decimal = Decimal("0")
    frete: Decimal | None = None
    status: str = "ENTREGUE"
    status_pagamento: str | None = "APROVADO"
    tipo: str = "VENDA"
    canal: str = CANAL_LOJA
    loja_id: int | None = None
    cliente_id: int | None = None
    itens: list[tuple[int, int, Decimal]] = field(default_factory=list)  # (variacao_id, qtd, preço)
    metodo: str | None = None
    parcelas: int = 1
    pedido_id: int | None = None


class Contexto:
    def __init__(self, db: Session):
        self.db = db
        self.resultado = Resultado(DOMINIO)
        self.corrigidos: set[str] = set()

    def ocorrencia(
        self,
        codigo,
        descricao,
        acao,
        *,
        id_origem=None,
        original=None,
        final=None,
        impacto=None,
        unidade=None,
        origem=ORIGEM_VENDAS,
    ):
        migracao_repository.registrar_ocorrencia(
            self.db,
            codigo_problema=codigo,
            dominio=DOMINIO,
            origem=origem,
            id_origem=None if id_origem is None else str(id_origem),
            descricao=descricao,
            acao_tomada=acao,
            valor_original=None if original is None else str(original),
            valor_final=None if final is None else str(final),
            impacto=impacto,
            impacto_unidade=unidade,
        )
        if acao == "CORRIGIDO" and id_origem is not None:
            self.corrigidos.add(f"{origem}#{id_origem}")


def _moeda(valor: Decimal | None) -> str:
    return "—" if valor is None else f"R$ {valor:.2f}".replace(".", ",")


def _de_teste(v: VendaLegado) -> str | None:
    if v.obs_chave.startswith("teste"):
        return f'obs "{v.obs}"'
    if any(i.sku.strip().upper() in SKUS_TESTE for i in v.itens):
        return "item TESTE-001"
    if n.identidade_de_teste(v.cliente_ref):
        return f"cliente de teste ({v.cliente_ref.strip()})"
    return None


def descartar_testes_e_duplicatas(ctx: Contexto, planos: dict[int, Plano]) -> None:
    for plano in planos.values():
        if motivo := _de_teste(plano.venda):
            plano.destino = "DESCARTADA"
            ctx.ocorrencia(
                "VENDA_DE_TESTE",
                f"Venda de teste da TI/QA ({motivo}): fora da plataforma.",
                "DESCARTADO",
                id_origem=plano.venda.id,
                original=plano.venda.total,
            )
    por_externo: dict[str, list[Plano]] = defaultdict(list)
    for plano in planos.values():
        if plano.destino != "DESCARTADA" and plano.venda.pedido_externo:
            por_externo[plano.venda.pedido_externo.strip()].append(plano)
    for externo, repetidos in por_externo.items():
        if len(repetidos) < 2:
            continue
        pagos = [p for p in repetidos if (n.status(p.venda.status) or STATUS_VAZIO)[1] == "APROVADO"]
        manter = min(pagos or repetidos, key=lambda p: p.momento)
        for plano in repetidos:
            if plano is manter:
                continue
            igual = plano.venda.total == manter.venda.total and sorted(i.sku for i in plano.venda.itens) == sorted(
                i.sku for i in manter.venda.itens
            )
            if not igual:
                ctx.ocorrencia(
                    "PEDIDO_EXTERNO_REPETIDO",
                    f"Pedido externo {externo} repetido com conteúdo diferente: as duas vendas entram.",
                    "PENDENTE",
                    id_origem=plano.venda.id,
                    original=externo,
                )
                continue
            plano.destino = "DESCARTADA"
            como = "aguardando seguido do pago" if (plano.venda.status or "").lower() == "aguardando" else "enviado duas vezes"
            ctx.ocorrencia(
                "VENDA_DUPLICADA",
                f"Mesmo pedido externo {externo} ({como}, {abs(plano.momento - manter.momento).seconds} s "
                f"depois): fica só a venda {manter.venda.id}.",
                "DESCARTADO",
                id_origem=plano.venda.id,
                original=plano.venda.total,
            )


def _texto_canal(texto: str | None) -> str | None:
    chave = _sem_acento(texto or "")
    if chave == "app":
        return CANAL_APP
    if chave in ("site", "web", "ecommerce", "e-commerce"):
        return CANAL_SITE
    if chave in ("loja", "pdv", "fisica", "loja fisica"):
        return CANAL_LOJA
    return None  # "online" vale para site e app


def decidir_escala(catalogo: Catalogo, v: VendaLegado, dia: date) -> tuple[str, str]:
    """(escala, como decidiu). Total com separador decimal é reais; inteiro pode ser centavos (app)."""
    if "centavos" not in n.escalas(v.total):
        return "reais", "separador decimal"
    razoes = {"reais": [], "centavos": []}
    for item in v.itens:
        variacao = catalogo.variacao(item.sku, dia)
        preco = n.dinheiro(item.preco)
        if variacao is None or not catalogo.preco.get(variacao) or preco is None:
            continue
        razoes["reais"].append(abs(preco) / catalogo.preco[variacao])
        razoes["centavos"].append(abs(preco) / 100 / catalogo.preco[variacao])
    for escala in ("centavos", "reais"):
        if razoes[escala] and RAZAO_CATALOGO[0] <= statistics.median(razoes[escala]) <= RAZAO_CATALOGO[1]:
            return escala, "preço do catálogo"
    return ("centavos", "loja online, sem preço de catálogo") if v.loja in (5, 6) else ("reais", "sem preço de catálogo")


def _escalar(valor: str | None, escala: str) -> Decimal:
    numero = n.dinheiro(valor) or Decimal("0")
    if escala == "centavos" and re.fullmatch(r"-?\d+", str(valor or "").strip()):
        return (numero / 100).quantize(n.CENTAVO)
    return numero


def transformar(ctx: Contexto, plano: Plano, catalogo: Catalogo, lojas: dict[int, m.Loja], clientes: dict[str, int]) -> None:
    v = plano.venda
    dia = plano.momento.astimezone(n.FUSO_ORIGEM).date()

    plano.escala, como = decidir_escala(catalogo, v, dia)
    plano.total = _escalar(v.total, plano.escala)
    plano.desconto = _escalar(v.desconto, plano.escala)
    frete_coluna = n.dinheiro(v.frete) if v.frete else None
    for item in v.itens:
        variacao = catalogo.variacao(item.sku, dia)
        if variacao is None:
            variacao = catalogo.nao_catalogado
            ctx.ocorrencia(
                "ITEM_SEM_PRODUTO",
                "Item com SKU que não acha variação: vai para o produto não catalogado.",
                "CORRIGIDO",
                id_origem=v.id,
                original=item.sku,
            )
        plano.itens.append((variacao, item.qtd, _escalar(item.preco, plano.escala)))
    plano.subtotal = sum((abs(q) * p for _, q, p in plano.itens), Decimal("0"))
    if plano.escala == "centavos":
        legado = n.dinheiro(v.total)
        ctx.ocorrencia(
            "VALOR_EM_CENTAVOS",
            f"Total e itens gravados em centavos pelo app (decidido pelo {como}).",
            "CORRIGIDO",
            id_origem=v.id,
            original=v.total,
            final=_moeda(plano.total),
            impacto=plano.total - legado,
            unidade="REAIS",
        )

    # Conta da venda: total = itens − desconto + frete. O que sobra é frete embutido (online) ou desconto não registrado
    total_abs = abs(plano.total)
    diferenca = total_abs - (plano.subtotal - plano.desconto + (frete_coluna or 0))
    plano.frete = frete_coluna
    if abs(diferenca) > TOLERANCIA:
        if diferenca > 0 and v.loja in (5, 6) and frete_coluna is None:
            plano.frete = diferenca
            ctx.ocorrencia(
                "FRETE_EMBUTIDO_NO_TOTAL",
                "O app somou o frete no total sem gravar na coluna frete: separado.",
                "CORRIGIDO",
                id_origem=v.id,
                original=v.total,
                final=f"frete {_moeda(diferenca)}",
            )
        elif diferenca < 0:
            plano.desconto += -diferenca
            ctx.ocorrencia(
                "DESCONTO_NAO_REGISTRADO",
                "Total menor que a soma dos itens sem desconto registrado: a diferença vira desconto.",
                "CORRIGIDO",
                id_origem=v.id,
                original=f"total {v.total} · itens {plano.subtotal}",
                final=f"desconto {_moeda(plano.desconto)}",
            )
        else:
            ctx.ocorrencia(
                "TOTAL_NAO_FECHA",
                "Total maior que itens + frete numa loja física: mantido o total gravado.",
                "PENDENTE",
                id_origem=v.id,
                original=v.total,
                impacto=diferenca,
                unidade="REAIS",
            )

    status = n.status(v.status)
    if status is None:
        status = STATUS_VAZIO
        ctx.ocorrencia(
            "STATUS_VAZIO_COMO_PAGO",
            "Status vazio (lojas físicas, jan–fev/25, com itens e conta fechando): tratado como pago.",
            "CORRIGIDO",
            id_origem=v.id,
            original="''",
            final="ENTREGUE/APROVADO",
        )
    plano.status, plano.status_pagamento = status

    plano.canal = n.canal(v.loja)
    texto = _texto_canal(v.canal_texto)
    if texto and texto != plano.canal:
        ctx.ocorrencia(
            "CANAL_TEXTO_DIVERGE",
            "O texto do canal contradiz a loja da venda: vale a loja.",
            "MANTIDO",
            id_origem=v.id,
            original=f"{v.canal_texto} · loja {v.loja}",
            final=plano.canal,
        )
    if v.loja in (5, 6):
        sfs = any(t in v.obs_chave for t in TERMOS_SFS)
        plano.loja_id = lojas[lojas_vulto.ID_LEGADO_PINHEIROS if sfs else lojas_vulto.ID_LEGADO_CD].id
        if sfs:
            ctx.ocorrencia(
                "SHIP_FROM_STORE",
                "Pedido do site que saiu de Pinheiros: a loja de expedição é Pinheiros (o sistema da Vulto baixava do site).",
                "CORRIGIDO",
                id_origem=v.id,
                original=v.obs,
                final="Vulto Pinheiros",
            )
    else:
        plano.loja_id = lojas[v.loja].id

    plano.cliente_id = _cliente(clientes, v.cliente_ref)
    plano.metodo = METODO_PADRAO_POR_CANAL[plano.canal]
    if plano.total < 0:
        plano.destino = "DEVOLUCAO"
    elif any(t in v.obs_chave for t in TERMOS_TROCA):
        plano.tipo = "TROCA"
        ctx.ocorrencia(
            "TROCA_FORA_DA_RECEITA",
            "Troca lançada como venda nova pelo preço cheio: entra como pedido TROCA "
            "(baixa o estoque), fora do faturamento — a venda original já contou.",
            "CORRIGIDO",
            id_origem=v.id,
            original=f"{v.obs} · {_moeda(plano.total)}",
            impacto=-plano.total if plano.status != "CANCELADO" else 0,
            unidade="REAIS",
        )


def _cliente(clientes: dict[str, int], ref: str | None) -> int | None:
    try:
        referencia = n.referencia_cliente(ref)
    except n.ValorInvalido:
        return None
    if referencia is None:
        return None
    chave = f"{referencia.tipo}:{referencia.valor}"
    if chave in clientes:
        return clientes[chave]
    if referencia.ambigua and (fone := n.telefone(ref)):
        return clientes.get(f"telefone:{fone}")
    return None


# ---------- Batel, março ----------


@dataclass
class LinhaBatel:
    linha: int
    momento: datetime
    cpf: str | None
    nome: str | None
    pecas: str
    valor: Decimal
    pgto: str | None
    obs: str


def ler_batel(ctx: Contexto) -> tuple[list[LinhaBatel], Decimal | None]:
    linhas, total_marco = [], None
    consulta = text(
        "SELECT _linha, data, hora, cliente, cpf, pecas, valor, pgto, obs, _tipos "
        "FROM legado_vulto.batel_manual__marco ORDER BY _linha"
    )
    for linha, data, hora, cliente, cpf, pecas, valor, pgto, obs, tipos in ctx.db.execute(consulta):
        tipos = json.loads(tipos or "{}")
        if (pecas or "").upper().startswith("TOTAL"):
            if pecas.upper().strip() == "TOTAL MARÇO":
                total_marco = n.dinheiro(valor)
            continue
        if tipos.get("data") == "datetime":
            lida = datetime.fromisoformat(data).date()
            corrigida = date(lida.year, lida.day, lida.month) if lida.day <= 12 else lida
            if not BATEL_INICIO <= lida <= BATEL_FIM and BATEL_INICIO <= corrigida <= BATEL_FIM:
                ctx.ocorrencia(
                    "BATEL_DATA_INVERTIDA",
                    "O Excel leu a data digitada como mês/dia: dia e mês destrocados.",
                    "CORRIGIDO",
                    id_origem=linha,
                    original=data,
                    final=corrigida.isoformat(),
                    origem=ORIGEM_BATEL,
                )
                lida = corrigida
        else:
            lida = n.data_hora(data, ano_padrao=2026).momento.date()
        hora_lida = time.fromisoformat(hora) if hora and re.fullmatch(r"\d{1,2}:\d{2}", hora) else time(12)
        documento = None
        if cpf:
            try:
                documento = n.cpf(cpf, numero_excel=tipos.get("cpf") == "int")
            except n.ValorInvalido:
                ctx.ocorrencia(
                    "CPF_INVALIDO",
                    "CPF ilegível na planilha manual: venda sem cliente.",
                    "DESCARTADO",
                    id_origem=linha,
                    original=cpf,
                    origem=ORIGEM_BATEL,
                )
        linhas.append(
            LinhaBatel(
                linha,
                datetime.combine(lida, hora_lida, n.FUSO_ORIGEM),
                documento,
                cliente,
                pecas,
                n.dinheiro(valor),
                pgto,
                (obs or "").strip(),
            )
        )
    return linhas, total_marco


class Pecas:
    """Casa a descrição livre da planilha ("2x pochete nylon branco U") com uma variação do catálogo."""

    def __init__(self, db: Session):
        self.por_nome: dict[str, m.Produto] = {}
        for produto in db.scalars(select(m.Produto).where(m.Produto.marca == "VULTO").order_by(m.Produto.ativo, m.Produto.id)):
            self.por_nome[_sem_acento(produto.nome)] = produto  # o ativo (mais recente) fica por último e vence

    def achar(self, descricao: str) -> tuple[int, m.Variacao | None, str]:
        """(quantidade, variação, nome lido)."""
        texto = descricao.strip()
        quantidade = 1
        if m_qtd := re.match(r"(\d+)\s*x\s+", texto, re.I):
            quantidade, texto = int(m_qtd[1]), texto[m_qtd.end() :]
        partes = texto.split()
        try:
            tam = n.tamanho(partes[-1])
        except (n.ValorInvalido, IndexError):
            return quantidade, None, texto
        cor = None
        for tamanho_cor in (2, 1):
            if len(partes) > tamanho_cor:
                try:
                    cor = n.codigo_cor(" ".join(partes[-1 - tamanho_cor : -1]))
                    nome = " ".join(partes[: -1 - tamanho_cor])
                    break
                except n.ValorInvalido:
                    continue
        if cor is None:
            return quantidade, None, texto
        chave = _sem_acento(nome)
        produto = self.por_nome.get(chave) or self.por_nome.get(
            next(iter(get_close_matches(chave, self.por_nome, n=1, cutoff=0.85)), "")
        )
        if produto is None:
            return quantidade, None, nome
        variacao = next((v for v in produto.variacoes if v.cor == n.CORES[cor] and v.tamanho == tam), None)
        return quantidade, variacao, nome


def _cpf_da_venda(venda: VendaLegado) -> str | None:
    try:
        referencia = n.referencia_cliente(venda.cliente_ref)
    except n.ValorInvalido:
        return None
    return referencia.valor if referencia and referencia.tipo == "cpf" else None


def _metodo_batel(pgto: str | None) -> tuple[str, int]:
    return METODO_BATEL.get(_sem_acento(pgto or ""), (METODO_PADRAO_POR_CANAL[CANAL_LOJA], 1))


def planejar_batel(ctx: Contexto, planos: dict[int, Plano], catalogo: Catalogo, lojas, clientes) -> list[Plano]:
    """Linhas da planilha manual que viram pedido (as relançadas no sistema ficam com o pedido do sistema)."""
    linhas, total_marco = ler_batel(ctx)
    # Os totais da gerente não contam as vendas canceladas ou estornadas na maquininha
    validas = [linha for linha in linhas if not any(t in _sem_acento(linha.obs) for t in ("cancelou", "estornado"))]
    soma = sum((linha.valor for linha in validas), Decimal("0"))
    if total_marco is not None:
        ctx.ocorrencia(
            "BATEL_TOTAL_DA_PLANILHA",
            f"Soma das {len(validas)} vendas manuais não canceladas conferida com o TOTAL MARÇO da planilha "
            f"({len(linhas) - len(validas)} canceladas ou estornadas ficam fora, como nos totais da gerente).",
            "MANTIDO" if soma == total_marco else "PENDENTE",
            original=_moeda(total_marco),
            final=_moeda(soma),
            impacto=soma - total_marco,
            unidade="REAIS",
            origem=ORIGEM_BATEL,
        )
    ctx.ocorrencia(
        "BATEL_PIX_FALTANDO",
        'A aba Plan2 da planilha manual diz "semana 2 faltou 1 venda pix?": não há dado dessa venda; fica de fora.',
        "PENDENTE",
        origem="vendas_batel_MANUAL_marco.xlsx:Plan2",
    )

    batel = lojas[4].id
    candidatos = [
        p
        for p in planos.values()
        if p.destino == "PEDIDO"
        and p.venda.loja == 4
        and (TERMO_RETROATIVO in p.venda.obs_chave or BATEL_INICIO <= p.momento.astimezone(n.FUSO_ORIGEM).date() <= BATEL_FIM)
    ]
    pecas = Pecas(ctx.db)
    ctx.resultado.lidos += len(linhas)
    novos = []
    for linha in linhas:
        cliente = clientes.get(f"cpf:{linha.cpf}") if linha.cpf else None
        par = next((p for p in candidatos if linha.cpf and _cpf_da_venda(p.venda) == linha.cpf and p.total == linha.valor), None)
        if par is None and not linha.cpf:
            sem_cpf = [p for p in candidatos if p.total == linha.valor and not _cpf_da_venda(p.venda)]
            par = sem_cpf[0] if len(sem_cpf) == 1 else None
        if par is not None:
            candidatos.remove(par)
            ctx.ocorrencia(
                "BATEL_JA_RELANCADA",
                f"Venda manual que a gerente relançou no sistema (venda {par.venda.id}, mesmo "
                "CPF e valor): fica a do sistema, que tem os SKUs.",
                "DESCARTADO",
                id_origem=linha.linha,
                original=f"{linha.pecas} · {_moeda(linha.valor)}",
                origem=ORIGEM_BATEL,
            )
            if TERMO_RETROATIVO in par.venda.obs_chave and par.momento.date() != linha.momento.date():
                ctx.ocorrencia(
                    "BATEL_RELANCADA_REDATADA",
                    "Venda relançada com a data do relançamento: volta para a data em que aconteceu (planilha manual).",
                    "CORRIGIDO",
                    id_origem=par.venda.id,
                    original=par.venda.criado_em,
                    final=linha.momento.isoformat(),
                )
                par.momento = linha.momento
            continue

        plano = Plano(
            VendaLegado(
                -linha.linha,
                None,
                "planilha manual",
                4,
                linha.cpf,
                str(linha.valor),
                None,
                None,
                None,
                linha.momento.isoformat(),
                linha.obs,
                None,
            )
        )
        plano.momento, plano.loja_id, plano.canal, plano.cliente_id = linha.momento, batel, CANAL_LOJA, cliente
        plano.metodo, plano.parcelas = _metodo_batel(linha.pgto)
        obs = _sem_acento(linha.obs)
        if "estornado" in obs:
            plano.status, plano.status_pagamento = "CANCELADO", "ESTORNADO"
        elif "cancelou" in obs:
            plano.status, plano.status_pagamento = "CANCELADO", None
        itens, sem_cadastro = [], []
        for descricao in linha.pecas.split(" + "):
            quantidade, variacao, nome = pecas.achar(descricao)
            if variacao is None:
                sem_cadastro.append(descricao)
                itens.append((catalogo.nao_catalogado, quantidade, None))
            else:
                itens.append((variacao.id, quantidade, catalogo.preco[variacao.id]))
        # Preço de catálogo; a diferença para o valor cobrado é desconto (ou, se a mais, rateio)
        com_preco = sum((q * p for _, q, p in itens if p is not None), Decimal("0"))
        if sem_cadastro:
            ctx.ocorrencia(
                "BATEL_PECA_SEM_CADASTRO",
                "Peça da planilha manual que não casa com o catálogo: entra como item sem cadastro.",
                "ESTIMADO",
                id_origem=linha.linha,
                original=" + ".join(sem_cadastro),
                origem=ORIGEM_BATEL,
            )
            resto = max(linha.valor - com_preco, Decimal("0"))
            qtd_sem = sum(q for _, q, p in itens if p is None)
            itens = [(v, q, p if p is not None else (resto / qtd_sem).quantize(n.CENTAVO)) for v, q, p in itens]
        plano.itens = itens
        plano.subtotal = sum((q * p for _, q, p in itens), Decimal("0"))
        plano.total = linha.valor
        if plano.subtotal > linha.valor:
            plano.desconto = plano.subtotal - linha.valor
        elif plano.subtotal < linha.valor:
            fator = linha.valor / plano.subtotal if plano.subtotal else Decimal("1")
            plano.itens = [(v, q, (p * fator).quantize(n.CENTAVO)) for v, q, p in itens]
            plano.subtotal = sum((q * p for _, q, p in plano.itens), Decimal("0"))
            plano.desconto = max(plano.subtotal - linha.valor, Decimal("0"))
        ctx.ocorrencia(
            "BATEL_VENDA_MANUAL",
            "Venda feita com o PDV fora do ar, só na planilha manual: entra como pedido (peças "
            "casadas pela descrição; preço do catálogo e a diferença como desconto).",
            "ESTIMADO",
            id_origem=linha.linha,
            original=f"{linha.pecas} · {_moeda(linha.valor)}",
            final=_moeda(plano.total),
            impacto=plano.total if plano.status != "CANCELADO" else 0,
            unidade="REAIS",
            origem=ORIGEM_BATEL,
        )
        novos.append(plano)
    for p in candidatos:
        if TERMO_RETROATIVO in p.venda.obs_chave:
            ctx.ocorrencia(
                "BATEL_RELANCADA_SEM_PAR",
                "Venda relançada que não casou com nenhuma linha da planilha manual: fica como está.",
                "PENDENTE",
                id_origem=p.venda.id,
                original=p.venda.total,
            )
    return novos


# ---------- Devoluções ----------


def ligar_devolucoes(
    ctx: Contexto, planos: dict[int, Plano], itens_por_pedido: dict[int, list[m.ItemPedido]]
) -> list[tuple[m.Devolucao, str]]:
    """(devolução, id de origem "venda:item") de cada item devolvido."""
    compras_do_cliente: dict[int, list[Plano]] = defaultdict(list)
    for p in planos.values():
        if p.destino == "PEDIDO" and p.cliente_id:
            compras_do_cliente[p.cliente_id].append(p)
    devolucoes = []
    for plano in planos.values():
        if plano.destino != "DEVOLUCAO":
            continue
        v = plano.venda
        referencia = re.search(r"(\d{2,6})", v.obs)
        original = planos.get(int(referencia[1])) if referencia else None
        for indice, (variacao_id, qtd, preco) in enumerate(plano.itens, start=1):
            item, como = None, None
            if original and original.destino == "PEDIDO":
                item = next((i for i in itens_por_pedido[original.pedido_id] if i.variacao_id == variacao_id), None)
                como = "REFERENCIA" if item else None
            if item is None and plano.cliente_id:
                anteriores = [
                    p
                    for p in compras_do_cliente[plano.cliente_id]
                    if p.momento <= plano.momento
                    and plano.momento - p.momento <= JANELA_DEVOLUCAO
                    and any(vid == variacao_id for vid, _, _ in p.itens)
                ]
                if anteriores:
                    compra = max(anteriores, key=lambda p: p.momento)
                    item = next(i for i in itens_por_pedido[compra.pedido_id] if i.variacao_id == variacao_id)
                    como = "CLIENTE"
            valor = (abs(qtd) * preco).quantize(n.CENTAVO)
            devolucoes.append(
                (
                    m.Devolucao(
                        item_pedido_id=item.id if item else None,
                        pedido_id=item.pedido_id if item else None,
                        variacao_id=variacao_id,
                        usuario_id=None,
                        loja_id=plano.loja_id,
                        quantidade=abs(qtd),
                        valor_devolvido=valor,
                        motivo=v.obs or "devolução (Vulto)",
                        criada_em=plano.momento,
                    ),
                    f"{v.id}:{indice}",
                )
            )
            if como == "REFERENCIA":
                acao, descricao = "MANTIDO", "Devolução ligada à venda citada na obs."
            elif como == "CLIENTE":
                acao, descricao = (
                    "ESTIMADO",
                    "Devolução sem referência válida: ligada à última compra do mesmo cliente com a mesma peça.",
                )
            else:
                acao, descricao = (
                    "PENDENTE",
                    "Devolução que não dá para ligar a nenhuma venda: entra sem origem (conta no líquido).",
                )
            ctx.ocorrencia(
                f"DEVOLUCAO_{como or 'SEM_ORIGEM'}",
                descricao,
                acao,
                id_origem=v.id,
                original=v.obs or v.total,
                final=f"pedido {item.pedido_id}" if item else None,
                impacto=-valor,
                unidade="REAIS",
            )
    return devolucoes


# ---------- Carga ----------


def _limpar(db: Session) -> None:
    """Refaz os filhos dos pedidos migrados (itens, pagamentos, histórico, devoluções); os pedidos ficam
    (atendimentos e transferências podem apontar para eles) e são atualizados."""
    vulto = select(m.Pedido.id).where(m.Pedido.numero.like(f"{PREFIXO}%"))
    # Devoluções migradas: as dos pedidos da Vulto e as sem origem (só a migração grava devolução sem usuário)
    db.execute(delete(m.Devolucao).where(m.Devolucao.pedido_id.in_(vulto) | m.Devolucao.usuario_id.is_(None)))
    for modelo in (m.Pagamento, m.EventoPedido, m.ItemPedido):
        db.execute(delete(modelo).where(modelo.pedido_id.in_(vulto)))
    db.execute(
        delete(m.DePara).where(
            m.DePara.origem.in_((ORIGEM_VENDAS, ORIGEM_COMPRAS, ORIGEM_BATEL)),
            m.DePara.tabela_destino.in_(("pedidos", "devolucoes")),
        )
    )


def _origem_legivel(plano: Plano) -> str:
    venda_id = plano.venda.id
    return f"planilha manual da Batel, linha {-venda_id}" if venda_id < 0 else f"venda {venda_id}"


def _numero(plano: Plano) -> str:
    v = plano.venda
    return f"{PREFIXO}BATEL-{-v.id:03d}" if v.id < 0 else f"{PREFIXO}{v.id:05d}"


def migrar(db: Session) -> Resultado:
    ctx = Contexto(db)
    migracao_repository.limpar_ocorrencias(db, DOMINIO)
    _limpar(db)
    catalogo = Catalogo(db)
    lojas = {i: lojas_vulto.loja_da_vulto(db, i) for i in lojas_vulto.LOJAS}
    clientes = dict(
        db.execute(select(m.DePara.id_origem, m.DePara.id_destino).where(m.DePara.origem == "vulto.db:cliente_ref")).all()
    )

    vendas = ler_vendas(db)
    planos = {v.id: Plano(v, momento=n.data_hora(v.criado_em).momento) for v in vendas}
    ctx.resultado.lidos = len(vendas)
    descartar_testes_e_duplicatas(ctx, planos)
    for plano in planos.values():
        if plano.destino != "DESCARTADA":
            transformar(ctx, plano, catalogo, lojas, clientes)
    _registrar_eldorado(ctx, vendas)
    batel = planejar_batel(ctx, planos, catalogo, lojas, clientes)

    pedidos = [p for p in planos.values() if p.destino == "PEDIDO"] + batel
    existentes = {p.numero: p for p in db.scalars(select(m.Pedido).where(m.Pedido.numero.like(f"{PREFIXO}%")))}
    usados = set()
    for plano in pedidos:
        numero = _numero(plano)
        pedido = existentes.get(numero) or m.Pedido(numero=numero)
        usados.add(numero)
        db.add(pedido)
        pedido.cliente_id, pedido.loja_id, pedido.canal, pedido.tipo = plano.cliente_id, plano.loja_id, plano.canal, plano.tipo
        pedido.status, pedido.subtotal, pedido.desconto, pedido.total = plano.status, plano.subtotal, plano.desconto, plano.total
        pedido.frete_valor = plano.frete
        pedido.pedido_externo = plano.venda.pedido_externo
        pedido.criado_em = plano.momento
        pedido.itens = [m.ItemPedido(variacao_id=v, quantidade=q, preco_unitario=p) for v, q, p in plano.itens]
        pedido.eventos = [
            m.EventoPedido(
                status=plano.status,
                criado_em=plano.momento,
                observacao=f"Migrado da Vulto ({_origem_legivel(plano)})",
            )
        ]
        pedido.pagamentos = (
            [
                m.Pagamento(
                    metodo=plano.metodo,
                    valor=plano.total,
                    parcelas=plano.parcelas,
                    status=plano.status_pagamento,
                    criado_em=plano.momento,
                )
            ]
            if plano.status_pagamento
            else []
        )
        plano.pedido = pedido  # type: ignore[attr-defined]
    db.flush()
    _remover_pedidos_obsoletos(db, set(existentes) - usados)

    itens_por_pedido: dict[int, list[m.ItemPedido]] = {}
    for plano in pedidos:
        plano.pedido_id = plano.pedido.id  # type: ignore[attr-defined]
        itens_por_pedido[plano.pedido_id] = list(plano.pedido.itens)  # type: ignore[attr-defined]
        origem, id_origem = (ORIGEM_BATEL, str(-plano.venda.id)) if plano.venda.id < 0 else (ORIGEM_VENDAS, str(plano.venda.id))
        migracao_repository.vincular(db, origem, id_origem, "pedidos", plano.pedido_id)
        if plano.venda.compra_id:
            migracao_repository.vincular(db, ORIGEM_COMPRAS, str(plano.venda.compra_id), "pedidos", plano.pedido_id)

    devolucoes = ligar_devolucoes(ctx, planos, itens_por_pedido)
    db.add_all(d for d, _ in devolucoes)
    db.flush()
    for devolucao, id_origem in devolucoes:
        migracao_repository.vincular(db, ORIGEM_VENDAS, id_origem, "devolucoes", devolucao.id)

    sem_cliente = sum(1 for p in pedidos if p.cliente_id is None)
    ctx.ocorrencia(
        "VENDA_SEM_CLIENTE",
        'Vendas sem cliente identificável (vazio, "NAO INFORMADO", "consumidor", referência inválida): pedido sem cliente.',
        "MANTIDO",
        impacto=sem_cliente,
        unidade="REGISTROS",
    )
    db.flush()

    descartadas = sum(1 for p in planos.values() if p.destino == "DESCARTADA")
    ctx.resultado.carregados = len(pedidos) + len(devolucoes)
    ctx.resultado.descartados = descartadas
    ctx.resultado.corrigidos = len(ctx.corrigidos)
    ctx.resultado.ocorrencias = migracao_repository.ocorrencias_por_acao(db, DOMINIO)
    trocas = sum(1 for p in pedidos if p.tipo == "TROCA")
    ctx.resultado.notas = [
        f"pedidos: {len(pedidos)} ({len(batel)} da planilha manual da Batel, {trocas} trocas, {sem_cliente} sem cliente)",
        f"devoluções: {len(devolucoes)} itens · descartadas: {descartadas} vendas (teste e duplicatas)",
    ]
    return ctx.resultado


def _remover_pedidos_obsoletos(db: Session, numeros: set[str]) -> None:
    """Pedidos migrados numa rodada anterior que agora são descartados (ex.: teste): saem, soltando quem apontava para eles."""
    if not numeros:
        return
    ids = select(m.Pedido.id).where(m.Pedido.numero.in_(numeros))
    db.execute(update(m.Atendimento).where(m.Atendimento.pedido_id.in_(ids)).values(pedido_id=None))
    db.execute(update(m.Transferencia).where(m.Transferencia.pedido_id.in_(ids)).values(pedido_id=None))
    db.execute(update(m.MovimentoPontos).where(m.MovimentoPontos.pedido_id.in_(ids)).values(pedido_id=None))
    db.execute(delete(m.Pedido).where(m.Pedido.numero.in_(numeros)))


def _registrar_eldorado(ctx: Contexto, vendas: list[VendaLegado]) -> None:
    """A troca do servidor do PDV do Eldorado (fev/26): datas passaram de horário local para UTC (Z)."""
    eldorado = [v for v in vendas if v.loja == 2]
    utc = [v for v in eldorado if v.criado_em.endswith("Z")]
    if not utc:
        return
    primeira = min(utc, key=lambda v: v.id)
    noite = sum(
        1
        for v in utc
        if n.data_hora(v.criado_em).momento.astimezone(n.FUSO_ORIGEM).date() != n.data_hora(v.criado_em).momento.date()
    )
    ctx.ocorrencia(
        "ELDORADO_SERVIDOR_TROCADO",
        f"Desde a venda {primeira.id} ({primeira.criado_em}) o PDV do Eldorado grava em UTC (Z); antes, horário local. "
        f"Sem lacunas nem vendas duplicadas na troca. {len(utc)} vendas convertidas para Brasília; {noite} delas, feitas depois "
        "das 21h, o sistema da Vulto contava no dia seguinte.",
        "CORRIGIDO",
        id_origem=primeira.id,
        original=f"{len(eldorado) - len(utc)} vendas em horário local · {len(utc)} em UTC",
        impacto=noite,
        unidade="REGISTROS",
    )
