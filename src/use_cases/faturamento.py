"""Faturamento por mês × loja × canal (com e sem frete) e o comparativo "sistema da Vulto × nosso número".

Receita = pedidos de venda não cancelados e com pagamento que não está só pendente; troca não é receita
(a venda original já contou); devoluções saem na data em que aconteceram (receita líquida).

O comparativo refaz o /relatorio/faturamento do sistema da Vulto (main.py) sobre o staging, com os
mesmos erros: soma todas as vendas (inclusive canceladas), lê "19081" (centavos do app) como R$ 19.081,
tira o "Z" da data sem converter o fuso. A diferença para o nosso número sai decomposta por ajuste, mês a
mês; o que nenhum ajuste explica fica em "outros" (o teste garante que é zero).
"""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from src import models as m
from src.config.settings import FUSO
from src.entities.marca import MARCAS, VULTO
from src.entities.pedido import TIPOS_SEM_RECEITA
from src.repositories import cadastro_repository, faturamento_repository, migracao_repository, pedido_repository
from src.use_cases.pedidos import conferir_acesso
from src.utils.datas import inicio_do_dia, ler_data
from src.utils.erros import DadosInvalidos, NaoEncontrado

INICIO_PADRAO, FIM_PADRAO = "2025-01-01", "2026-09-30"
SEM_ORIGEM = "Sem origem"

AJUSTES = {
    "centavos": 'O app grava o valor em centavos ("19081" = R$ 190,81); o sistema da Vulto somava como reais.',
    "cancelados": "Vendas canceladas, estornadas e chargebacks: o relatório da Vulto não tirava (estava como TODO).",
    "aguardando": "Vendas com o pagamento ainda pendente (aguardando): ainda não são receita.",
    "trocas": "Troca lançada como venda nova pelo preço cheio: fora do faturamento (a venda original já contou).",
    "devolucoes": "Devoluções: o sistema já subtraía o valor negativo; aqui sai o valor dos itens devolvidos.",
    "testes": 'Vendas de teste da TI/QA (obs "teste", item TESTE-001, clientes de teste).',
    "duplicatas": "O mesmo pedido do app gravado duas vezes (aguardando seguido do pago, ou enviado em dobro).",
    "batel": "Batel com o PDV fora do ar (02 a 22/03/26): vendas da planilha manual e relançadas que voltam para a data real.",
    "fuso": "Datas em UTC (site, app e Eldorado depois de fev/26): o sistema contava a venda das 21h às 24h no dia seguinte.",
    "outros": "Diferença que nenhum ajuste acima explica.",
}


def _intervalo(de: str | None, ate: str | None) -> tuple[str, str, datetime, datetime]:
    inicio = ler_data(de or INICIO_PADRAO, "de")
    fim = ler_data(ate or FIM_PADRAO, "ate")
    if fim < inicio:
        raise DadosInvalidos("A data final deve ser igual ou posterior à inicial.")
    return inicio.isoformat(), fim.isoformat(), inicio_do_dia(inicio), inicio_do_dia(fim + timedelta(days=1))


def _meses(inicio: str, fim: str) -> list[str]:
    meses, ano, mes = [], int(inicio[:4]), int(inicio[5:7])
    while f"{ano:04d}-{mes:02d}" <= fim[:7]:
        meses.append(f"{ano:04d}-{mes:02d}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return meses


def _valor(numero) -> float:
    return float(Decimal(numero or 0).quantize(Decimal("0.01")))


def faturamento(db: Session, de: str | None, ate: str | None, marca: str | None) -> dict:
    if marca and marca not in MARCAS:
        raise DadosInvalidos("Marca inválida.")
    inicio, fim, desde, ate_dt = _intervalo(de, ate)
    lojas = {loja.id: loja for loja in cadastro_repository.lojas(db)}
    linhas: dict[tuple[str, int, str], dict] = {}

    def linha(mes, loja_id, canal):
        chave = (mes, loja_id, canal or SEM_ORIGEM)
        if chave not in linhas:
            linhas[chave] = {"pedidos": 0, "com_frete": Decimal(0), "frete": Decimal(0), "devolucoes": Decimal(0)}
        return linhas[chave]

    for r in faturamento_repository.receita(db, desde, ate_dt, marca):
        alvo = linha(r["mes"], r["loja_id"], r["canal"])
        alvo["pedidos"] += r["pedidos"]
        alvo["com_frete"] += r["com_frete"]
        alvo["frete"] += r["frete"]
    for r in faturamento_repository.devolucoes(db, desde, ate_dt, marca):
        linha(r["mes"], r["loja_id"], r["canal"])["devolucoes"] += r["valor"]

    def saida(valores: dict) -> dict:
        com, frete, dev = valores["com_frete"], valores["frete"], valores["devolucoes"]
        return {
            "pedidos": valores["pedidos"],
            "comFrete": _valor(com),
            "frete": _valor(frete),
            "semFrete": _valor(com - frete),
            "devolucoes": _valor(dev),
            "liquidoComFrete": _valor(com - dev),
            "liquidoSemFrete": _valor(com - frete - dev),
        }

    total = {"pedidos": 0, "com_frete": Decimal(0), "frete": Decimal(0), "devolucoes": Decimal(0)}
    for valores in linhas.values():
        for campo in total:
            total[campo] += valores[campo]
    return {
        "de": inicio,
        "ate": fim,
        "marca": marca,
        "linhas": [
            {
                "mes": mes,
                "lojaId": loja_id,
                "loja": lojas[loja_id].nome,
                "marca": lojas[loja_id].marca,
                "canal": canal,
                **saida(v),
            }
            for (mes, loja_id, canal), v in sorted(
                linhas.items(), key=lambda item: (item[0][0], lojas[item[0][1]].nome, item[0][2])
            )
        ],
        "total": saida(total),
    }


# ---------- Comparativo com o sistema da Vulto ----------

# Formatos que o main.py da Vulto aceitava (parse_data), depois de tirar o "Z"
_FORMATOS_LEGADO = ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d")


def dia_legado(texto) -> str | None:
    """dia_utc() do main.py: a data como está no texto (sem o Z), sem converter o fuso."""
    s = str(texto or "").replace("Z", "")
    for formato in _FORMATOS_LEGADO:
        try:
            return datetime.strptime(s, formato).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def valor_legado(texto) -> Decimal:
    """valor() do main.py: troca vírgula por ponto e lê como número (o que não dá, zero)."""
    try:
        return Decimal(str(float(str(texto).replace(",", ".")))).quantize(Decimal("0.01"))
    except ValueError:
        return Decimal("0")


def _mes_sp(momento: datetime) -> str:
    return momento.astimezone(FUSO).strftime("%Y-%m")


def _conta(pedido: m.Pedido) -> str | None:
    """Por que um pedido não é receita (None: é)."""
    if pedido.status == "CANCELADO":
        return "cancelados"
    if pedido.pagamentos and all(p.status == "PENDENTE" for p in pedido.pagamentos):
        return "aguardando"
    if pedido.tipo in TIPOS_SEM_RECEITA:
        return "trocas"
    return None


def comparativo_vulto(db: Session, de: str | None, ate: str | None) -> dict:
    inicio, fim, _, _ = _intervalo(de, ate)
    meses = _meses(inicio, fim)
    legado = defaultdict(Decimal)
    ajustes: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

    def ajustar(mes: str | None, categoria: str, valor: Decimal) -> None:
        if mes in meses and valor:
            ajustes[mes][categoria] += valor

    destinos = faturamento_repository.destinos_das_vendas(db)
    codigos = faturamento_repository.ocorrencias_das_vendas(
        db, ("VENDA_DE_TESTE", "VENDA_DUPLICADA", "VALOR_EM_CENTAVOS", "BATEL_RELANCADA_REDATADA")
    )
    pedidos = faturamento_repository.pedidos_vulto(db)
    devolucoes = faturamento_repository.devolucoes_vulto(db)

    for venda in faturamento_repository.vendas_do_legado(db):
        dia = dia_legado(venda["criado_em"])
        valor = valor_legado(venda["total"])
        no_relatorio = dia is not None and inicio <= dia <= fim
        mes = dia[:7] if dia else None
        if no_relatorio:
            legado[mes] += valor
        codigo = codigos.get(str(venda["id"]), set())
        if "VENDA_DE_TESTE" in codigo or "VENDA_DUPLICADA" in codigo:
            # Descartada antes de decidir a escala: total inteiro no site/app é centavos, como na migração
            if venda["loja"] in (5, 6) and str(venda["total"]).strip().lstrip("-").isdigit():
                real = (valor / 100).quantize(Decimal("0.01"))
                if no_relatorio:
                    ajustar(mes, "centavos", real - valor)
                valor = real
            if no_relatorio:
                ajustar(mes, "testes" if "VENDA_DE_TESTE" in codigo else "duplicatas", -valor)
            continue
        if "VALOR_EM_CENTAVOS" in codigo:
            real = (valor / 100).quantize(Decimal("0.01"))
            if no_relatorio:
                ajustar(mes, "centavos", real - valor)
            valor = real

        contribuicoes, motivo, eh_devolucao = [], None, False
        for tabela, id_destino in destinos.get(str(venda["id"]), []):
            if tabela == "pedidos":
                pedido = pedidos[id_destino]
                motivo = _conta(pedido)
                if motivo is None:
                    contribuicoes.append((_mes_sp(pedido.criado_em), pedido.total))
            else:
                eh_devolucao = True
                devolucao = devolucoes[id_destino]
                contribuicoes.append((_mes_sp(devolucao.criada_em), -devolucao.valor_devolvido))
        if motivo is not None:
            if no_relatorio:
                ajustar(mes, motivo, -valor)
            continue
        soma = sum((v for _, v in contribuicoes), Decimal("0"))
        movimento = "batel" if "BATEL_RELANCADA_REDATADA" in codigo else "fuso"
        if no_relatorio:
            ajustar(mes, "devolucoes" if eh_devolucao else "outros", soma - valor)
            ajustar(mes, movimento, -soma)
        for mes_nosso, v in contribuicoes:
            ajustar(mes_nosso, movimento, v)

    for pedido_id in faturamento_repository.pedidos_da_planilha_batel(db):
        pedido = pedidos[pedido_id]
        if _conta(pedido) is None:
            ajustar(_mes_sp(pedido.criado_em), "batel", pedido.total)

    nosso = faturamento(db, inicio, fim, VULTO)
    por_mes = defaultdict(lambda: {"com": Decimal(0), "frete": Decimal(0)})
    for linha in nosso["linhas"]:
        por_mes[linha["mes"]]["com"] += Decimal(str(linha["liquidoComFrete"]))
        por_mes[linha["mes"]]["frete"] += Decimal(str(linha["frete"]))

    def bloco(valor_legado_mes: Decimal, ajustes_mes: dict, com: Decimal, frete: Decimal) -> dict:
        """Sistema da Vulto + ajustes = nosso (com frete); o que sobra vai para "outros"."""
        ajustes_mes = dict(ajustes_mes)
        explicado = valor_legado_mes + sum(ajustes_mes.values(), Decimal("0"))
        ajustes_mes["outros"] = ajustes_mes.get("outros", Decimal(0)) + (com - explicado)
        return {
            "sistemaVulto": _valor(valor_legado_mes),
            "ajustes": {categoria: _valor(ajustes_mes.get(categoria, 0)) for categoria in AJUSTES},
            "nossoComFrete": _valor(com),
            "frete": _valor(frete),
            "nossoSemFrete": _valor(com - frete),
        }

    linhas = [{"mes": mes, **bloco(legado[mes], ajustes[mes], por_mes[mes]["com"], por_mes[mes]["frete"])} for mes in meses]
    soma_ajustes = defaultdict(Decimal)
    for mes in meses:
        for categoria, valor in ajustes[mes].items():
            soma_ajustes[categoria] += valor
    total = bloco(
        sum(legado.values(), Decimal(0)),
        soma_ajustes,
        sum((v["com"] for v in por_mes.values()), Decimal(0)),
        sum((v["frete"] for v in por_mes.values()), Decimal(0)),
    )
    return {"de": inicio, "ate": fim, "explicacao": AJUSTES, "meses": linhas, "total": total}


# ---------- Consulta de venda da Vulto ----------


def venda_vulto(db: Session, referencia: str, usuario: m.Usuario) -> tuple[m.Pedido, int | None]:
    """Pedido de uma venda da Vulto pelo id da venda no sistema antigo, pelo número do pedido no site/app
    (S100234, APP-7001205) ou pelo número na plataforma (VLT-00123). (pedido, id da venda no legado)."""
    termo = (referencia or "").strip()
    if not termo:
        raise DadosInvalidos("Informe a venda.")
    if termo.isdigit():
        pedido_id = migracao_repository.destino(db, "vulto.db:vendas", str(int(termo)), "pedidos")
        if pedido_id is None:
            motivo = migracao_repository.motivo_da_venda(db, str(int(termo)))
            raise NaoEncontrado(
                f"A venda {int(termo)} da Vulto não virou pedido: {motivo}" if motivo else "Venda não encontrada."
            )
        return conferir_acesso(usuario, pedido_repository.obter(db, pedido_id)), int(termo)
    pedido = pedido_repository.por_numero_ou_externo(db, termo)
    if pedido is None or not pedido.numero.startswith("VLT-"):
        raise NaoEncontrado("Venda não encontrada.")
    venda_id = migracao_repository.origem(db, "pedidos", pedido.id, "vulto.db:vendas")
    return conferir_acesso(usuario, pedido), int(venda_id) if venda_id else None
