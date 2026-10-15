"""Domínio fidelidade: o Vulto+ vira contas_pontos + movimentos_pontos (pontos só com CPF).

Base (aprovada): os movimentos que o sistema da Vulto gravou, corrigidos das anomalias.
- Saldo inicial: a coluna Pontos da aba Clientes, congelada em 01/01/2025 ("2.203" = 2203; "2,7k" =
  2700, ESTIMADO). Cliente duplicado soma os saldos. Os pontos dos clientes antigos ATIVO já foram
  migrados para essa coluna em jan/24 e não somam de novo.
- Créditos (C), depois de 01/01/2025:
  - sem CPF válido saem (telefone, e-mail);
  - o bug do app v3.4 (08 a 12/06/2026: pontos sobre o valor em centavos) é corrigido para o que o
    sistema creditaria sem o bug; os ajustes manuais "correcao bug app v3.4" saem, porque a correção
    exata os substitui;
  - venda aguardando pagamento não pontua; venda descartada (teste, duplicata) não pontua;
  - venda cancelada sem estorno ganha o estorno.
- Resgates (D), estornos (E) e os outros ajustes manuais (cortesia, aniversário) ficam.
- Aba Resgates: os de 2025 em diante que não estão no sistema (mesmo CPF e pontos, até 7 dias de
  diferença) são debitados; os de antes de 2025 já estão no saldo congelado (aprovado).
- Categoria pela regra (aprovado), com a validade FIFO de src/entities/fidelidade.py; o saldo nunca fica
  negativo (o que faltaria fica registrado).
- O que o sistema nunca aplicou (bônus Ouro de +50%; o dobro do online quando o canal veio escrito
  "APP", "online", "web"...) não entra no saldo: entra no máximo da faixa do passivo, com a mesma validade.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from src import models as m
from src.entities import fidelidade as regra
from src.migracao_vulto import normalizacao as n
from src.migracao_vulto.relatorio import Resultado
from src.migracao_vulto.vendas import ORIGEM_COMPRAS, ORIGEM_VENDAS, _moeda
from src.repositories import migracao_repository

DOMINIO = "fidelidade"
ORIGEM_MOV = "vulto.db:pontos_mov"
ORIGEM_PLANILHA = "clientes.xlsx:Clientes"
ORIGEM_ANTIGOS = "clientes.xlsx:clientes antigos (NAO APAGAR)"
ORIGEM_RESGATES = "clientes.xlsx:Resgates"
ORIGEM_VALIDADE = "vulto+:validade"
ORIGENS = (ORIGEM_MOV, ORIGEM_PLANILHA, ORIGEM_RESGATES, ORIGEM_VALIDADE)

CONGELAMENTO = datetime(2025, 1, 1, tzinfo=n.FUSO_ORIGEM)
# A virada para a plataforma: o passivo é calculado aqui e os vencimentos são aplicados até aqui
DATA_CORTE = datetime.combine(regra.DATA_VIRADA, time(0), n.FUSO_ORIGEM)
OBS_BUG = "correcao bug app v3.4"
JANELA_RESGATE = timedelta(days=7)
# O sistema dobrava os pontos só quando o canal vinha escrito exatamente assim (main.py: CANAIS_ONLINE)
CANAIS_DOBRO_LEGADO = ("site", "app")
ORIGENS_ONLINE = ("site", "app")  # compras.origem: o canal gravado varia ("APP", "online", "E-commerce", "web"...)
# Crédito acima de 3× o que a venda daria (já em dobro) é o bug dos centavos (100× ou 200×)
FATOR_INFLADO = 3

CATEGORIA_DECLARADA = {
    "bronze": "BRONZE", "brz": "BRONZE",
    "prata": "PRATA", "prata*": "PRATA", "silver": "PRATA",
    "ouro": "OURO", "ouro ★": "OURO", "gold": "OURO",
}  # fmt: skip


@dataclass
class Mov:
    tipo: str
    quantidade: int
    quando: datetime
    origem: str
    obs: str = ""
    pedido_id: int | None = None
    sem_dobro: int = 0  # o dobro do online que o sistema não deu


class Contexto:
    def __init__(self, db: Session):
        self.db = db
        self.resultado = Resultado(DOMINIO)
        self.contas: dict[str, list[Mov]] = defaultdict(list)  # CPF → movimentos
        self.cliente_por_cpf = dict(db.execute(select(m.Cliente.cpf, m.Cliente.id).where(m.Cliente.cpf.is_not(None))).all())

    def ocorrencia(self, codigo, origem, descricao, acao, *, id_origem=None, original=None, final=None, impacto=None):
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
            impacto_unidade=None if impacto is None else "PONTOS",
        )
        if id_origem is not None and acao == "CORRIGIDO":
            self.resultado.corrigidos += 1
        if id_origem is not None and acao == "DESCARTADO":
            self.resultado.descartados += 1


def pontos_planilha(valor) -> tuple[int, bool]:
    """(pontos, exato). "2.203" = 2203 (ponto de milhar); "1389 pts"; "2,7k" = 2700 (arredondado: estimado)."""
    if valor is None or str(valor).strip() == "":
        return 0, True
    texto = str(valor).lower().replace("pts", "").replace(" ", "")
    if texto.endswith("k"):
        try:
            return int(Decimal(texto[:-1].replace(",", ".")) * 1000), False
        except ArithmeticError:
            raise n.ValorInvalido(f"Pontos ilegíveis: {valor!r}") from None
    if texto.endswith(".0") and texto[:-2].isdigit():  # célula numérica lida como float
        texto = texto[:-2]
    grupos = texto.split(".")
    if not (grupos[0].isdigit() and all(len(g) == 3 and g.isdigit() for g in grupos[1:])):
        raise n.ValorInvalido(f"Pontos ilegíveis: {valor!r}")
    return int("".join(grupos)), True


def _cpf(valor, *, numero_excel: bool = False) -> str | None:
    try:
        return n.cpf(valor, numero_excel=numero_excel)
    except n.ValorInvalido:
        return None


def _tipos(tipos: str | None) -> dict:
    return json.loads(tipos or "{}")


# ---------- Saldo congelado em 01/01/2025 ----------


def saldo_inicial(ctx: Contexto) -> None:
    por_cpf: dict[str, list[int]] = defaultdict(list)
    linhas = ctx.db.execute(text("SELECT _linha, cpf, pontos, _tipos FROM legado_vulto.clientes__clientes ORDER BY _linha")).all()
    ctx.resultado.lidos += len(linhas)
    for linha, cpf, pontos, tipos in linhas:
        id_origem = f"linha {linha}"
        try:
            valor, exato = pontos_planilha(pontos)
        except n.ValorInvalido:
            ctx.ocorrencia("SALDO_ILEGIVEL", ORIGEM_PLANILHA, "Saldo congelado ilegível: entra zero.", "PENDENTE",
                           id_origem=id_origem, original=pontos)  # fmt: skip
            continue
        if not valor:
            continue
        documento = _cpf(cpf, numero_excel=_tipos(tipos).get("cpf") == "int")
        if documento is None or documento not in ctx.cliente_por_cpf:
            ctx.ocorrencia("SALDO_SEM_CPF", ORIGEM_PLANILHA, "Saldo congelado de cliente sem CPF válido: pontos só com CPF.",
                           "DESCARTADO", id_origem=id_origem, original=f"{pontos} · CPF {cpf}", impacto=-valor)  # fmt: skip
            continue
        if not exato:
            ctx.ocorrencia("SALDO_ARREDONDADO", ORIGEM_PLANILHA, 'Saldo anotado arredondado ("2,7k"): entra o valor '
                           "arredondado.", "ESTIMADO", id_origem=id_origem, original=pontos, final=valor)  # fmt: skip
        elif not str(pontos).strip().isdigit():
            ctx.ocorrencia("SALDO_COM_FORMATO", ORIGEM_PLANILHA, 'Saldo com ponto de milhar ou "pts" ("2.203" = 2203).',
                           "CORRIGIDO", id_origem=id_origem, original=pontos, final=valor)  # fmt: skip
        por_cpf[documento].append(valor)
    for cpf, valores in por_cpf.items():
        if len(valores) > 1:
            ctx.ocorrencia("SALDOS_DUPLICADOS_SOMADOS", ORIGEM_PLANILHA, "Cliente duplicado na planilha: os saldos "
                           "congelados foram somados na conta única.", "CORRIGIDO", id_origem=f"cpf {cpf}",
                           original=" + ".join(map(str, valores)), final=sum(valores))  # fmt: skip
        ctx.contas[cpf].append(Mov("SALDO_INICIAL", sum(valores), CONGELAMENTO, ORIGEM_PLANILHA, "saldo congelado em 01/01/2025"))

    # Programa antigo: já está na coluna Pontos (migrado em jan/24 para quem estava ATIVO)
    antigos = ctx.db.execute(
        text("SELECT cpf_cnpj, _tipos FROM legado_vulto.clientes__clientes_antigos_nao_apagar WHERE upper(status) = 'ATIVO'")
    ).all()
    na_planilha = {
        _cpf(cpf, numero_excel=_tipos(tipos).get("cpf") == "int")
        for cpf, tipos in ctx.db.execute(text("SELECT cpf, _tipos FROM legado_vulto.clientes__clientes"))
    }
    fora = sum(1 for cpf, tipos in antigos if _cpf(cpf, numero_excel=_tipos(tipos).get("cpf_cnpj") == "int") not in na_planilha)
    ctx.ocorrencia("PONTOS_ANTIGOS_JA_MIGRADOS", ORIGEM_ANTIGOS, f"Os pontos do programa antigo dos {len(antigos)} clientes "
                   "ATIVO já foram migrados em jan/24 para a coluna Pontos: não somam de novo. "
                   f"{fora} deles não estão na aba Clientes (se tinham pontos, ficaram no programa antigo).",
                   "MANTIDO")  # fmt: skip


# ---------- Movimentos do sistema (pontos_mov) ----------


def _compras(db: Session) -> dict[str, dict]:
    """Compras do legado com o pedido migrado (se houver) e o motivo do descarte da venda (teste, duplicata)."""
    compras = {
        r["id"]: dict(r) for r in db.execute(text("SELECT id, valor, canal, origem FROM legado_vulto.db__compras")).mappings()
    }
    pedido_da_compra = dict(
        db.execute(select(m.DePara.id_origem, m.DePara.id_destino).where(m.DePara.origem == ORIGEM_COMPRAS)).all()
    )
    pedidos = {p.id: p for p in db.scalars(select(m.Pedido).where(m.Pedido.id.in_({int(i) for i in pedido_da_compra.values()})))}
    descartadas = dict(
        db.execute(
            text(
                "SELECT v.compra_id, o.codigo_problema FROM legado_vulto.db__vendas v JOIN migracao_ocorrencias o "
                "ON o.id_origem = v.id AND o.origem = :origem AND o.dominio = 'vendas' "
                "WHERE o.codigo_problema IN ('VENDA_DE_TESTE', 'VENDA_DUPLICADA') AND v.compra_id IS NOT NULL"
            ),
            {"origem": ORIGEM_VENDAS},
        ).all()
    )
    for compra_id, compra in compras.items():
        destino = pedido_da_compra.get(compra_id)
        compra["pedido"] = pedidos.get(int(destino)) if destino else None
        compra["descartada"] = descartadas.get(compra_id)
    return compras


def _credito_corrigido(ctx: Contexto, mid: str, qtd: int, compra: dict) -> int:
    """Bug do app v3.4: pontos sobre o valor em centavos (100×, ou 200× com o dobro). Corrige para o que o
    sistema creditaria sem o bug: o mesmo valor em reais, com o mesmo dobro que ele aplicava."""
    pedido = compra["pedido"]
    if pedido is None or qtd <= FATOR_INFLADO * 2 * max(pedido.subtotal, Decimal(1)):
        return qtd
    dobro = 2 if compra["canal"] in CANAIS_DOBRO_LEGADO else 1
    valor = str(compra["valor"] or "").strip()
    base = Decimal(valor) / 100 if valor.isdigit() else pedido.subtotal
    certo = int((base * dobro).to_integral_value())
    ctx.ocorrencia("CREDITO_INFLADO_BUG_APP", ORIGEM_MOV, "Crédito calculado sobre o valor em centavos (bug do app v3.4): "
                   "corrigido para o valor em reais.", "CORRIGIDO", id_origem=mid,
                   original=f"{qtd} pontos (compra de {valor}; venda {pedido.numero} de R$ {pedido.subtotal})", final=certo,
                   impacto=certo - qtd)  # fmt: skip
    return certo


def movimentos_do_sistema(ctx: Contexto) -> None:
    db = ctx.db
    compras = _compras(db)
    linhas = list(db.execute(text("SELECT * FROM legado_vulto.db__pontos_mov ORDER BY id::int")).mappings())
    ctx.resultado.lidos += len(linhas)
    creditadas: set[str] = set()  # compras cujo crédito entrou
    pedidos_creditados: set[int] = set()
    estornadas = {r["compra_id"] for r in linhas if r["tipo"] == "E" and r["compra_id"]}
    trocas = pontos_trocas = 0

    for r in linhas:
        mid, tipo, qtd = r["id"], r["tipo"], int(r["qtd"])
        quando = n.data_hora(r["criado_em"]).momento
        cpf = _cpf(r["cpf"])
        if cpf is None or cpf not in ctx.cliente_por_cpf:
            teste = n.identidade_de_teste(r["cpf"])
            ctx.ocorrencia(
                "PONTOS_DE_TESTE" if teste else "PONTOS_SEM_CPF_VALIDO" if cpf is None else "PONTOS_SEM_CLIENTE",
                ORIGEM_MOV,
                "Movimento de pontos de CPF de teste." if teste else "Movimento para referência que não é CPF válido "
                "(telefone, e-mail): pontos só com CPF." if cpf is None else "Movimento de CPF que não é cliente migrado.",
                "DESCARTADO", id_origem=mid, original=f"{tipo} {qtd} · {r['cpf']}",
                impacto=-qtd if tipo in ("C", "AJ") else None,
            )  # fmt: skip
            continue
        movs = ctx.contas[cpf]
        obs = (r["obs"] or "").strip()
        if tipo == "AJ":
            if obs == OBS_BUG:
                ctx.ocorrencia("AJUSTE_DO_BUG_SUBSTITUIDO", ORIGEM_MOV, "Ajuste manual da correção do bug do app v3.4: sai, "
                               "porque cada crédito inflado já foi corrigido com o valor exato.", "DESCARTADO", id_origem=mid,
                               original=qtd, impacto=-qtd)  # fmt: skip
            else:
                movs.append(Mov("AJUSTE", qtd, quando, ORIGEM_MOV, obs or "ajuste manual"))
            continue
        if tipo == "D":
            movs.append(Mov("RESGATE", -abs(qtd), quando, ORIGEM_MOV, f"resgate ({obs or 'sistema'})"))
            continue
        if tipo == "E":
            continue  # depois dos créditos: o estorno só vale se o crédito entrou

        compra = compras.get(r["compra_id"])
        if compra is None:
            movs.append(Mov("CREDITO", qtd, quando, ORIGEM_MOV, "crédito sem compra"))
            continue
        pedido = compra["pedido"]
        if compra["descartada"]:
            motivo = "de teste" if compra["descartada"] == "VENDA_DE_TESTE" else "duplicada"
            ctx.ocorrencia("CREDITO_DE_VENDA_DESCARTADA", ORIGEM_MOV, f"Crédito de uma venda {motivo} (descartada na etapa de "
                           "vendas): sai.", "DESCARTADO", id_origem=mid, original=qtd, impacto=-qtd)  # fmt: skip
            continue
        if pedido is not None and pedido.pagamentos and all(p.status == "PENDENTE" for p in pedido.pagamentos):
            ctx.ocorrencia("CREDITO_ANTES_DO_PAGAMENTO", ORIGEM_MOV, "Venda ainda aguardando pagamento: ponto só depois do "
                           "pagamento aprovado (o sistema creditava na hora).", "DESCARTADO", id_origem=mid,
                           original=f"{qtd} · {pedido.numero}", impacto=-qtd)  # fmt: skip
            continue
        qtd = _credito_corrigido(ctx, mid, qtd, compra)
        creditadas.add(r["compra_id"])
        sem_dobro = qtd if compra["origem"] in ORIGENS_ONLINE and compra["canal"] not in CANAIS_DOBRO_LEGADO else 0
        movs.append(
            Mov("CREDITO", qtd, quando, ORIGEM_MOV, f"compra (canal {compra['canal']})", pedido.id if pedido else None, sem_dobro)
        )
        if pedido is None:
            continue
        pedidos_creditados.add(pedido.id)
        if pedido.tipo == "TROCA":
            trocas += 1
            pontos_trocas += qtd
        if pedido.status == "CANCELADO" and r["compra_id"] not in estornadas:
            movs.append(
                Mov("ESTORNO", -qtd, quando + timedelta(seconds=1), ORIGEM_MOV, "estorno que faltou (venda cancelada)", pedido.id)
            )
            ctx.ocorrencia("CANCELADA_SEM_ESTORNO", ORIGEM_MOV, "Venda cancelada que manteve os pontos (o estorno era lançado "
                           "à mão): estornada.", "CORRIGIDO", id_origem=mid, original=f"crédito {qtd} · {pedido.numero}",
                           final="estornado", impacto=-qtd)  # fmt: skip

    for r in linhas:
        if r["tipo"] != "E" or (cpf := _cpf(r["cpf"])) not in ctx.cliente_por_cpf:
            continue
        qtd = int(r["qtd"])
        if r["compra_id"] and r["compra_id"] not in creditadas:
            ctx.ocorrencia("ESTORNO_DE_CREDITO_QUE_SAIU", ORIGEM_MOV, "Estorno de um crédito que não entrou (venda descartada "
                           "ou aguardando pagamento): sai junto.", "DESCARTADO", id_origem=r["id"], original=qtd,
                           impacto=abs(qtd))  # fmt: skip
            continue
        pedido = (compras.get(r["compra_id"]) or {}).get("pedido")
        ctx.contas[cpf].append(Mov("ESTORNO", -abs(qtd), n.data_hora(r["criado_em"]).momento, ORIGEM_MOV,
                                   "estorno de compra cancelada", pedido.id if pedido else None))  # fmt: skip

    if trocas:
        ctx.ocorrencia("CREDITO_EM_TROCA", ORIGEM_MOV, f"{trocas} trocas lançadas como venda nova ganharam pontos (a regra não "
                       "fala de troca): mantidos como o sistema creditou.", "MANTIDO", impacto=pontos_trocas)  # fmt: skip
    devolucoes, devolvido = db.execute(
        select(func.count(), func.coalesce(func.sum(m.Devolucao.valor_devolvido), 0)).where(
            m.Devolucao.pedido_id.in_(pedidos_creditados)
        )
    ).one()
    if devolucoes:
        ctx.ocorrencia("DEVOLUCAO_SEM_ESTORNO", ORIGEM_MOV, f"{devolucoes} devoluções de compras que pontuaram ("
                       f"{_moeda(devolvido)} devolvidos) não estornaram pontos. A regra só fala de compra cancelada: mantidos.",
                       "MANTIDO")  # fmt: skip


# ---------- Resgates anotados na planilha ----------


def resgates_da_planilha(ctx: Contexto) -> None:
    linhas = ctx.db.execute(
        text(
            "SELECT _linha, data, cliente, pontos_usados, loja, desconto_r, _tipos FROM legado_vulto.clientes__resgates "
            "ORDER BY _linha"
        )
    ).all()
    ctx.resultado.lidos += len(linhas)
    casados: set[int] = set()
    anteriores = 0
    valor_antigo = valor_antigo_reais = 0
    for linha, data, cliente, pontos, loja, desconto, tipos in linhas:
        id_origem = f"linha {linha}"
        try:
            lida = n.data_hora(data)
            quantidade, _ = pontos_planilha(pontos)
        except n.ValorInvalido:
            lida = None
        if lida is None or not quantidade:
            ctx.ocorrencia("RESGATE_ILEGIVEL", ORIGEM_RESGATES, "Resgate anotado sem data ou pontos legíveis.", "PENDENTE",
                           id_origem=id_origem, original=f"{data} · {cliente} · {pontos}")  # fmt: skip
            continue
        if lida.momento < CONGELAMENTO:
            anteriores += 1
            continue
        if (
            lida.momento.date() >= regra.VALOR_PONTO_MUDOU_EM
            and _valor_do_ponto(desconto, quantidade) == regra.VALOR_PONTO_ANTIGO
        ):
            valor_antigo += 1
            valor_antigo_reais += quantidade * (regra.VALOR_PONTO_ANTIGO - regra.VALOR_PONTO_VIGENTE)
        cpf = _cpf(cliente, numero_excel=_tipos(tipos).get("cliente") == "int")
        if cpf is None or cpf not in ctx.cliente_por_cpf:
            ctx.ocorrencia("RESGATE_SEM_CPF", ORIGEM_RESGATES, "Resgate anotado só com o nome (ou CPF que não é cliente): não "
                           "dá para saber de quem debitar.", "PENDENTE", id_origem=id_origem,
                           original=f"{data} · {cliente} · {pontos} pontos · {loja}", impacto=-quantidade)  # fmt: skip
            continue
        janela = timedelta(days=31) if lida.precisao == "mes" else JANELA_RESGATE
        igual = next(
            (
                mv
                for mv in ctx.contas[cpf]
                if mv.tipo == "RESGATE" and mv.origem == ORIGEM_MOV and id(mv) not in casados
                and -mv.quantidade == quantidade and abs(mv.quando - lida.momento) <= janela + timedelta(days=1)
            ),
            None,
        )  # fmt: skip
        if igual is not None:
            casados.add(id(igual))
            igual.obs += " · também anotado na planilha"
            continue
        ctx.contas[cpf].append(
            Mov("RESGATE", -quantidade, lida.momento, ORIGEM_RESGATES, f"resgate anotado na planilha ({loja})")
        )
        ctx.ocorrencia("RESGATE_SO_NA_PLANILHA", ORIGEM_RESGATES, "Resgate de 2025 em diante anotado só na planilha (fora do "
                       "sistema): debitado.", "CORRIGIDO", id_origem=id_origem, original=f"{data} · {cliente} · {pontos}",
                       impacto=-quantidade)  # fmt: skip
    ctx.resultado.notas.append(
        f"resgates da planilha: {len(casados)} já estavam no sistema; {anteriores} são de antes de 2025 (no saldo congelado)"
    )
    if valor_antigo:
        ctx.ocorrencia("RESGATE_COM_VALOR_ANTIGO", ORIGEM_RESGATES, f"{valor_antigo} resgates depois de mar/2025 deram R$ 0,10 "
                       "por ponto (o config.valor_ponto do sistema e o README), e não os R$ 0,05 da regra: "
                       f"{_moeda(valor_antigo_reais)} de desconto a mais. O passivo mostra os dois valores.",
                       "MANTIDO")  # fmt: skip


def _valor_do_ponto(desconto, pontos: int) -> Decimal | None:
    try:
        reais = n.dinheiro(desconto)
    except n.ValorInvalido:
        return None
    return (reais / pontos).quantize(Decimal("0.01")) if reais and pontos else None


# ---------- Carga ----------


def _no_ano(mv: Mov, ano: int) -> bool:
    return mv.quando.astimezone(n.FUSO_ORIGEM).year == ano


def migrar(db: Session) -> Resultado:
    ctx = Contexto(db)
    migracao_repository.limpar_ocorrencias(db, DOMINIO)
    saldo_inicial(ctx)
    movimentos_do_sistema(ctx)
    resgates_da_planilha(ctx)

    existentes = {c.cliente_id: c for c in db.scalars(select(m.ContaPontos))}
    db.execute(
        delete(m.MovimentoPontos).where(
            m.MovimentoPontos.conta_id.in_([c.id for c in existentes.values()]), m.MovimentoPontos.origem.in_(ORIGENS)
        )
    )
    ano = DATA_CORTE.year
    total = negativos = divergentes = depois_do_corte = 0
    sem_dobro = bonus_ouro = clientes_sem_dobro = 0  # o que o sistema não aplicou e ainda valeria na virada
    for cpf, todos in ctx.contas.items():
        depois_do_corte += sum(1 for mv in todos if mv.quando >= DATA_CORTE)
        movs = sorted((mv for mv in todos if mv.quando < DATA_CORTE), key=lambda mv: mv.quando)
        # Categoria pelos pontos creditados no ano (líquidos de estornos)
        categoria = regra.categoria_pela_regra(
            sum(mv.quantidade for mv in movs if mv.tipo in ("CREDITO", "ESTORNO") and _no_ano(mv, ano))
        )
        meses = regra.validade_meses(categoria)
        base = [(mv.quando, mv.quantidade) for mv in movs]
        validade = regra.aplicar_validade(base, meses, DATA_CORTE)
        if validade.faltas:
            # O saldo para em zero: um ajuste no mesmo instante cobre a diferença, e o extrato fecha com o saldo
            negativos += 1
            faltou = sum(falta for _, falta in validade.faltas)
            ctx.ocorrencia("SALDO_FICARIA_NEGATIVO", ORIGEM_MOV, "Resgates ou estornos maiores que o saldo disponível (o sistema "
                           "deixava ficar negativo): o saldo para em zero e a diferença entra como ajuste.", "PENDENTE",
                           id_origem=f"cpf {cpf}", impacto=faltou)  # fmt: skip
            obs = "saída maior que o saldo disponível: o saldo para em zero (o sistema da Vulto deixava negativo)"
            movs = sorted(movs + [Mov("AJUSTE", falta, quando, ORIGEM_VALIDADE, obs) for quando, falta in validade.faltas],
                          key=lambda mv: (mv.quando, mv.quantidade < 0))  # fmt: skip
        # Máximo do passivo: o dobro que faltou e o bônus Ouro (sobre tudo) como lotes a mais, com a mesma validade
        dobro = [(mv.quando, mv.sem_dobro) for mv in movs if mv.sem_dobro]
        com_dobro = regra.aplicar_validade(base + dobro, meses, DATA_CORTE).saldo if dobro else validade.saldo
        sem_dobro += com_dobro - validade.saldo
        clientes_sem_dobro += bool(dobro)
        if categoria == "OURO":
            bonus = [
                (mv.quando, int((mv.quantidade + mv.sem_dobro) * regra.BONUS_OURO))
                for mv in movs if mv.tipo == "CREDITO" and _no_ano(mv, ano)
            ]  # fmt: skip
            bonus_ouro += regra.aplicar_validade(base + dobro + bonus, meses, DATA_CORTE).saldo - com_dobro

        cliente_id = ctx.cliente_por_cpf[cpf]
        conta = existentes.get(cliente_id) or m.ContaPontos(cliente_id=cliente_id)
        db.add(conta)
        conta.categoria, conta.saldo = categoria, validade.saldo
        if conta.categoria_declarada and CATEGORIA_DECLARADA.get(conta.categoria_declarada.strip().lower()) != categoria:
            divergentes += 1
        db.flush()
        for mv in movs:
            db.add(
                m.MovimentoPontos(
                    conta_id=conta.id, tipo=mv.tipo, quantidade=mv.quantidade, data=mv.quando,
                    vence_em=regra.somar_meses(mv.quando, meses) if mv.quantidade > 0 else None,
                    pedido_id=mv.pedido_id, origem=mv.origem, obs=mv.obs,
                )
            )  # fmt: skip
        for quando, quantidade in validade.vencimentos:
            obs = f"pontos vencidos ({meses} meses, os mais antigos primeiro)"
            db.add(m.MovimentoPontos(conta_id=conta.id, tipo="VENCIMENTO", quantidade=-quantidade, data=quando,
                                     origem=ORIGEM_VALIDADE, obs=obs))  # fmt: skip
        total += len(movs) + len(validade.vencimentos)
    for conta in existentes.values():  # conta sem nenhum ponto: Bronze, saldo zero
        if conta.categoria is None:
            conta.categoria, conta.saldo = regra.categoria_pela_regra(0), 0
    db.flush()

    if depois_do_corte:
        ctx.ocorrencia("MOVIMENTO_DEPOIS_DA_VIRADA", ORIGEM_MOV, f"{depois_do_corte} movimentos de 01/10/2026 em diante: ficam "
                       "fora (a plataforma assume na virada).", "PENDENTE")  # fmt: skip
    if divergentes:
        ctx.ocorrencia("CATEGORIA_DECLARADA_DIVERGE", ORIGEM_PLANILHA, f"{divergentes} contas com a categoria colocada à mão "
                       f"diferente da regra (pontos creditados em {ano}): vale a regra; a declarada fica guardada.",
                       "CORRIGIDO")  # fmt: skip
    ctx.ocorrencia("ONLINE_SEM_DOBRO", ORIGEM_MOV, 'Compras online com o canal escrito "APP", "online", "web", "E-commerce"... '
                   'não ganharam o dobro (o sistema só dobrava "app" e "site"): o saldo fica como o cliente via. O impacto é o '
                   f"que ainda valeria em {DATA_CORTE:%d/%m/%Y} ({clientes_sem_dobro} clientes) e entra no máximo do passivo.",
                   "MANTIDO", impacto=sem_dobro)  # fmt: skip
    ctx.ocorrencia("BONUS_OURO_NUNCA_APLICADO", "main.py:/compra", "O sistema nunca aplicou o bônus Ouro de +50%: o saldo fica "
                   f"como o cliente via. O impacto é o bônus sobre os créditos de {ano} das contas Ouro que ainda valeria em "
                   f"{DATA_CORTE:%d/%m/%Y}, e entra no máximo do passivo.", "MANTIDO", impacto=bonus_ouro)  # fmt: skip
    _comparar_com_o_legado(ctx)

    ctx.resultado.carregados = total
    ctx.resultado.ocorrencias = migracao_repository.ocorrencias_por_acao(db, DOMINIO)
    saldo = db.scalar(select(func.coalesce(func.sum(m.ContaPontos.saldo), 0)))
    ctx.resultado.notas[:0] = [
        f"contas com movimento: {len(ctx.contas)} · movimentos: {total} · contas que ficariam negativas: {negativos}",
        f"saldo em {DATA_CORTE:%d/%m/%Y} (Ouro {regra.VALIDADE_OURO_GRAVADA} meses): {saldo} pontos",
    ]
    return ctx.resultado


def _comparar_com_o_legado(ctx: Contexto) -> None:
    """O saldo que o sistema da Vulto mostrava (/cliente/{cpf}): a coluna Pontos (o "2,7k" virava zero; só a
    primeira linha do CPF) + C + AJ − D + E, sem validade. Só comparação: não entra."""
    db = ctx.db
    planilha: dict[str, int] = {}
    for cpf, pontos, tipos in db.execute(text("SELECT cpf, pontos, _tipos FROM legado_vulto.clientes__clientes ORDER BY _linha")):
        documento = _cpf(cpf, numero_excel=_tipos(tipos).get("cpf") == "int")
        if documento and documento not in planilha:
            try:
                valor, exato = pontos_planilha(pontos)
            except n.ValorInvalido:
                valor, exato = 0, True
            planilha[documento] = valor if exato else 0
    saldos = defaultdict(int, planilha)
    for cpf, tipo, qtd in db.execute(text("SELECT cpf, tipo, qtd::int FROM legado_vulto.db__pontos_mov")):
        if (documento := _cpf(cpf)) is not None:
            saldos[documento] += -qtd if tipo == "D" else qtd
    mostrado = sum(v for v in saldos.values() if v > 0)
    negativos = sum(1 for v in saldos.values() if v < 0)
    sem_validade = db.scalar(
        select(func.coalesce(func.sum(m.MovimentoPontos.quantidade), 0)).where(m.MovimentoPontos.tipo != "VENCIMENTO")
    )
    vencidos = -db.scalar(
        select(func.coalesce(func.sum(m.MovimentoPontos.quantidade), 0)).where(m.MovimentoPontos.tipo == "VENCIMENTO")
    )
    ctx.ocorrencia("SALDO_DO_LEGADO_SO_COMPARACAO", "main.py:/cliente", f"O sistema da Vulto mostrava {mostrado} pontos "
                   f"(sem validade; {negativos} clientes com saldo negativo). Depois das correções, {sem_validade} pontos "
                   f"sem validade; {vencidos} venceram até {DATA_CORTE:%d/%m/%Y}. Só comparação: não entra.", "MANTIDO",
                   impacto=mostrado)  # fmt: skip
    ctx.resultado.notas.append(
        f"o sistema da Vulto mostrava {mostrado} pontos; sem validade, {sem_validade}; vencidos, {vencidos}"
    )
