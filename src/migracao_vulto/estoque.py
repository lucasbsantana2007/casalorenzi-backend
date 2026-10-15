"""Domínio estoque: o histórico de estoque da Vulto é reconstruído (a tabela estoque do legado não tem
histórico e tem 1.156 saldos negativos: serve só de comparação).

Movimentações, por loja e variação (marca VULTO):
- ENTRADA: entradas com nota fiscal (as de fornecedor).
- TRANSFERENCIA_SAIDA/ENTRADA (CD → loja): o CD anota o envio (quantidade só no texto da obs) e a loja
  anota o recebimento; "uma das duas pontas basta". Envio e recebimento da mesma peça, para a mesma loja,
  na mesma quantidade e datas próximas (JANELA_ANTES/JANELA_DEPOIS) são uma transferência só; a ponta
  sem par também conta (uma vez).
- VENDA: itens dos pedidos migrados (não cancelados, com pagamento que não está só pendente); site e app
  baixam do CD, o ship from store de Pinheiros; a troca baixa a peça nova.
- DEVOLUCAO: devoluções migradas.
- AJUSTE de abertura (01/01/2025, aprovado): o menor que deixa o histórico sem saldo negativo até a
  contagem (o saldo de abertura real é desconhecido) — ESTIMADO.
- AJUSTE da contagem de set/26 (âncora): leva o saldo reconstruído ao contado. Pinheiros 20/09, CD 28/09
  (coluna SALDO do WMS: reservado não é vendido); Eldorado, Savassi e Batel sem data na planilha: 30/09
  (aprovado, ESTIMADO). A Savassi contou por modelo: rateio pelo mix de entradas e vendas — ESTIMADO.
Saldo em 01/10/2026 = contagem + movimentos posteriores.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from src import models as m
from src.entities.marca import VULTO
from src.migracao_vulto import lojas as lojas_vulto
from src.migracao_vulto import normalizacao as n
from src.migracao_vulto.produtos import SUFIXO_PECA_ANTIGA
from src.migracao_vulto.relatorio import Resultado
from src.migracao_vulto.vendas import Catalogo
from src.repositories import migracao_repository

DOMINIO = "estoque"
ORIGEM_ENTRADAS = "vulto.db:entradas_estoque"
ORIGEM_CONTAGEM = "contagem_inventario_set26.xlsx"

# Envio e recebimento da mesma transferência: cada ponta anota quando quer (há recebimentos anotados
# antes do envio), então a janela vai de 10 dias antes a 15 depois do envio
JANELA_ANTES, JANELA_DEPOIS = timedelta(days=10), timedelta(days=15)
ABERTURA = datetime(2025, 1, 1, tzinfo=n.FUSO_ORIGEM)
HORA_ENTRADA = time(8)  # entrada sem hora: antes das vendas do dia
FIM_DO_DIA = time(23, 59, 59)

# Loja do legado → (aba da contagem, data, data estimada?)
CONTAGENS = {
    1: ("contagem__pinheiros_20_09", date(2026, 9, 20), False),
    2: ("contagem__eldorado", date(2026, 9, 30), True),
    3: ("contagem__savassi_por_modelo", date(2026, 9, 30), True),
    4: ("contagem__batel", date(2026, 9, 30), True),
    7: ("contagem__cd_posicao_wms_28_09", date(2026, 9, 28), False),
}
DESTINOS = {"pinheiros": 1, "eldorado": 2, "savassi": 3, "batel": 4}


@dataclass
class Mov:
    loja: int  # loja do legado
    variacao: int
    quando: datetime
    tipo: str
    quantidade: int
    origem: str
    devolucao_id: int | None = None


class Contexto:
    def __init__(self, db: Session):
        self.db = db
        self.resultado = Resultado(DOMINIO)

    def ocorrencia(self, codigo, origem, descricao, acao, *, id_origem=None, original=None, final=None, impacto=None):
        migracao_repository.registrar_ocorrencia(
            self.db,
            codigo_problema=codigo,
            dominio=DOMINIO,
            origem=origem,
            id_origem=None if id_origem is None else str(id_origem)[:80],
            descricao=descricao,
            acao_tomada=acao,
            valor_original=None if original is None else str(original),
            valor_final=None if final is None else str(final),
            impacto=impacto,
            impacto_unidade="UNIDADES" if impacto is not None else None,
        )


def _dia(texto: str) -> datetime:
    return datetime.combine(n.data_hora(texto).momento.date(), HORA_ENTRADA, n.FUSO_ORIGEM)


# ---------- Entradas e transferências ----------


@dataclass
class Ponta:
    id: int
    sku: str
    loja: int  # loja que recebe (destino)
    quantidade: int
    quando: datetime
    obs: str
    origem: int = lojas_vulto.ID_LEGADO_CD  # loja que envia


def _envio(obs: str) -> tuple[int, int] | None:
    """(loja de destino, quantidade) do texto de quem envia (o CD ou uma loja): "1 un -> batel", "TRANSF SAVASSI 1"..."""
    chave = n.sem_acento(obs or "").lower()
    destino = next((loja for nome, loja in DESTINOS.items() if nome in chave), None)
    quantidade = re.search(r"(\d+)", chave)
    return (destino, int(quantidade[1])) if destino and quantidade else None


def ler_entradas(ctx: Contexto, catalogo: Catalogo) -> list[Mov]:
    movs: list[Mov] = []
    envios: list[Ponta] = []
    recebimentos: list[Ponta] = []
    for r in ctx.db.execute(text("SELECT * FROM legado_vulto.db__entradas_estoque ORDER BY id::int")).mappings():
        quando = _dia(r["data"])
        loja, rid = int(r["loja_id"]), int(r["id"])
        if (r["nf"] or "").strip():
            variacao = catalogo.variacao(r["sku"], quando.date())
            if variacao is None:
                ctx.ocorrencia(
                    "ENTRADA_SEM_PRODUTO",
                    ORIGEM_ENTRADAS,
                    "Nota de entrada de SKU sem variação.",
                    "DESCARTADO",
                    id_origem=rid,
                    original=r["sku"],
                )
                continue
            movs.append(Mov(loja, variacao, quando, "ENTRADA", int(r["qtd"]), f"{ORIGEM_ENTRADAS} {rid} (NF {r['nf'].strip()})"))
        elif r["qtd"] is None:
            # Quem envia (o CD, ou uma loja para outra) anota a quantidade só no texto da obs
            envio = _envio(r["obs"])
            if envio is None or envio[0] == loja:
                ctx.ocorrencia(
                    "ENVIO_ILEGIVEL",
                    ORIGEM_ENTRADAS,
                    "Envio sem loja de destino ou quantidade legível na obs.",
                    "DESCARTADO",
                    id_origem=rid,
                    original=r["obs"],
                )
                continue
            envios.append(Ponta(rid, r["sku"], envio[0], envio[1], quando, r["obs"], origem=loja))
            if loja != lojas_vulto.ID_LEGADO_CD:
                ctx.ocorrencia(
                    "TRANSFERENCIA_ENTRE_LOJAS",
                    ORIGEM_ENTRADAS,
                    "Transferência entre lojas, anotada por quem enviou com a quantidade só na obs.",
                    "CORRIGIDO",
                    id_origem=rid,
                    original=r["obs"],
                    final=f"{envio[1]} un. para a loja {envio[0]} do legado",
                )
        else:
            recebimentos.append(Ponta(rid, r["sku"], loja, int(r["qtd"]), quando, r["obs"] or ""))
    movs += casar_transferencias(ctx, catalogo, envios, recebimentos)
    return movs


def casar_transferencias(ctx: Contexto, catalogo: Catalogo, envios: list[Ponta], recebimentos: list[Ponta]) -> list[Mov]:
    """Envio e recebimento da mesma peça viram uma transferência, peça a peça: o CD anota envios de uma
    unidade e a loja anota o recebimento somado ("2 un"). Cada recebimento consome a quantidade dos envios da
    mesma peça para a mesma loja, do mais próximo no tempo; o que sobra de cada lado conta uma vez."""
    restante: dict[int, int] = {}
    pendentes: dict[tuple[int, int], list[Ponta]] = defaultdict(list)
    for envio in sorted(envios, key=lambda p: (p.quando, p.id)):
        variacao = catalogo.variacao(envio.sku, envio.quando.date())
        if variacao is not None:
            pendentes[(variacao, envio.loja)].append(envio)
            restante[envio.id] = envio.quantidade
    movs: list[Mov] = []
    casadas = so_loja = 0
    cd = lojas_vulto.ID_LEGADO_CD
    for recebido in sorted(recebimentos, key=lambda p: (p.quando, p.id)):
        variacao = catalogo.variacao(recebido.sku, recebido.quando.date())
        if variacao is None:
            ctx.ocorrencia(
                "RECEBIMENTO_SEM_PRODUTO",
                ORIGEM_ENTRADAS,
                "Recebimento de SKU sem variação.",
                "DESCARTADO",
                id_origem=recebido.id,
                original=recebido.sku,
            )
            continue
        falta = recebido.quantidade
        candidatos = sorted(
            (
                e
                for e in pendentes[(variacao, recebido.loja)]
                if restante[e.id] and e.quando - JANELA_ANTES <= recebido.quando <= e.quando + JANELA_DEPOIS
            ),
            key=lambda e: (abs(recebido.quando - e.quando), e.id),
        )
        for envio in candidatos:
            if not falta:
                break
            usa = min(falta, restante[envio.id])
            restante[envio.id] -= usa
            falta -= usa
            casadas += usa
            origem = f"{ORIGEM_ENTRADAS} {envio.id} → {recebido.id}"
            movs.append(Mov(envio.origem, variacao, envio.quando, "TRANSFERENCIA_SAIDA", -usa, origem))
            movs.append(Mov(recebido.loja, variacao, recebido.quando, "TRANSFERENCIA_ENTRADA", usa, origem))
        if falta:
            so_loja += falta
            origem = f"{ORIGEM_ENTRADAS} {recebido.id} (só a loja anotou; vindo do CD)"
            movs.append(Mov(cd, variacao, recebido.quando, "TRANSFERENCIA_SAIDA", -falta, origem))
            movs.append(Mov(recebido.loja, variacao, recebido.quando, "TRANSFERENCIA_ENTRADA", falta, origem))
    so_envio = 0
    for (variacao, destino), fila in pendentes.items():
        for envio in fila:
            if quantidade := restante[envio.id]:
                so_envio += quantidade
                origem = f"{ORIGEM_ENTRADAS} {envio.id} (só quem enviou anotou)"
                movs.append(Mov(envio.origem, variacao, envio.quando, "TRANSFERENCIA_SAIDA", -quantidade, origem))
                movs.append(Mov(destino, variacao, envio.quando, "TRANSFERENCIA_ENTRADA", quantidade, origem))
    enviadas = sum(p.quantidade for p in envios)
    recebidas = sum(p.quantidade for p in recebimentos)
    ctx.ocorrencia(
        "TRANSFERENCIA_DOS_DOIS_LADOS",
        ORIGEM_ENTRADAS,
        f'Quem envia e quem recebe anotam a mesma transferência ("uma das duas pontas basta"): {casadas} peças aparecem '
        f"dos dois lados (mesma peça e loja, de {JANELA_ANTES.days} dias antes a {JANELA_DEPOIS.days} depois do envio) e "
        f"contam uma vez; {so_loja} só quem recebeu anotou (tratadas como vindas do CD) e {so_envio} só quem enviou.",
        "CORRIGIDO",
        original=f"{enviadas} peças enviadas · {recebidas} recebidas",
        final=f"{casadas + so_loja + so_envio} peças transferidas",
        impacto=-casadas,
    )
    return movs


# ---------- Vendas e devoluções (da migração das vendas) ----------


def ler_vendas_e_devolucoes(db: Session, legado_por_loja: dict[int, int]) -> list[Mov]:
    movs = []
    pedidos = db.scalars(select(m.Pedido).join(m.Loja, m.Loja.id == m.Pedido.loja_id).where(m.Loja.marca == VULTO))
    for pedido in pedidos:
        so_pendente = pedido.pagamentos and all(p.status == "PENDENTE" for p in pedido.pagamentos)
        if pedido.status == "CANCELADO" or so_pendente:
            continue
        for item in pedido.itens:
            movs.append(
                Mov(
                    legado_por_loja[pedido.loja_id],
                    item.variacao_id,
                    pedido.criado_em,
                    "VENDA",
                    -item.quantidade,
                    f"pedido {pedido.numero}",
                )
            )
    devolucoes = db.scalars(select(m.Devolucao).join(m.Loja, m.Loja.id == m.Devolucao.loja_id).where(m.Loja.marca == VULTO))
    for d in devolucoes:
        variacao = d.item.variacao_id if d.item else d.variacao_id
        origem = f"devolução do pedido {d.pedido.numero}" if d.pedido else "devolução sem venda de origem"
        movs.append(Mov(legado_por_loja[d.loja_id], variacao, d.criada_em, "DEVOLUCAO", d.quantidade, origem, devolucao_id=d.id))
    return movs


# ---------- Contagem ----------


def _consertar_grafia(catalogo: Catalogo, grafia: str, dia: date) -> int | None:
    """Erro de digitação inequívoco na contagem: separador fora do lugar ou letras da cor trocadas
    ("VLT-BE-R007-AZM-42", "VLT-MOL-001-RMR-G")."""
    compacto = re.sub(r"[^A-Z0-9]", "", grafia.upper())
    m_sku = re.fullmatch(r"VLT([A-Z]{3})(\d{3})([A-Z]{3})(PP|GG|P|M|G|U|\d{2})", compacto)
    if not m_sku:
        return None
    cores = [c for c in n.CORES if sorted(c) == sorted(m_sku[3])]
    if len(cores) != 1:
        return None
    return catalogo.variacao(f"VLT-{m_sku[1]}-{m_sku[2]}-{cores[0]}-{m_sku[4]}", dia)


def quantidade_contada(texto) -> tuple[int, bool]:
    """(quantidade, confere). A Batel anotou "2 (1 no estoque + 1 vitrine)": vale o total, conferido com as partes."""
    valor = str(texto or "0").strip()
    if valor.isdigit():
        return int(valor), True
    lido = re.match(r"(\d+)\s*(?:\((.*)\))?", valor)
    if lido is None:
        raise n.ValorInvalido(f"Quantidade ilegível: {texto!r}")
    total = int(lido[1])
    partes = [int(p) for p in re.findall(r"\d+", lido[2] or "")]
    return total, not partes or sum(partes) == total


def ler_contagem(ctx: Contexto, catalogo: Catalogo, loja: int) -> dict[int, int]:
    """Peças contadas por variação na loja do legado (Savassi: por modelo, rateado depois)."""
    tabela, dia, _ = CONTAGENS[loja]
    colunas = {
        1: ("sku", "qtd", "obs"),
        2: ("codigo", "qtde", "conferente"),
        4: ("sku", "quantidade", "obs"),
        7: ("sku", "saldo", "reservado"),
    }[loja]
    contadas: dict[int, int] = defaultdict(int)
    for linha, grafia, quantidade, extra in ctx.db.execute(
        text(f"SELECT _linha, {', '.join(colunas)} FROM legado_vulto.{tabela}")
    ):
        origem = f"{ORIGEM_CONTAGEM}:{tabela.split('__')[1]}"
        variacao = catalogo.variacao(grafia, dia)
        if variacao is None and (variacao := _consertar_grafia(catalogo, grafia, dia)) is not None:
            ctx.ocorrencia(
                "CONTAGEM_SKU_DIGITADO_ERRADO",
                origem,
                "SKU digitado errado na contagem, com conserto inequívoco (separador fora do lugar ou letras da cor trocadas).",
                "CORRIGIDO",
                id_origem=linha,
                original=grafia,
                final=variacao,
            )
        if variacao is None:
            ctx.ocorrencia(
                "CONTAGEM_SKU_ILEGIVEL",
                origem,
                "SKU da contagem que não acha variação: as peças ficam de fora do ajuste.",
                "DESCARTADO",
                id_origem=linha,
                original=f"{grafia} · {quantidade}",
                impacto=-quantidade_contada(quantidade)[0],
            )
            continue
        try:
            contado, confere = quantidade_contada(quantidade)
        except n.ValorInvalido:
            ctx.ocorrencia(
                "CONTAGEM_QUANTIDADE_ILEGIVEL",
                origem,
                "Quantidade ilegível na contagem.",
                "DESCARTADO",
                id_origem=linha,
                original=quantidade,
            )
            continue
        if not str(quantidade).strip().isdigit():
            ctx.ocorrencia(
                "CONTAGEM_QUANTIDADE_COM_TEXTO",
                origem,
                "Quantidade anotada com o detalhe estoque + vitrine: vale o "
                f"total{'' if confere else ' (a soma das partes não bate)'}.",
                "CORRIGIDO" if confere else "PENDENTE",
                id_origem=linha,
                original=quantidade,
                final=contado,
            )
        contadas[variacao] += contado
        if loja == 4 and extra and ("faltou contar" in extra or "recontar" in extra):
            ctx.ocorrencia(
                "BATEL_CONTAGEM_INCOMPLETA",
                origem,
                f'Linha da contagem da Batel marcada "{extra}": o contado pode estar abaixo do real (o ajuste usa o contado).',
                "PENDENTE",
                id_origem=linha,
                original=f"{grafia} · {quantidade}",
            )
    return contadas


def ratear_savassi(ctx: Contexto, catalogo: Catalogo, movs: list[Mov], savassi_id: int) -> dict[int, int]:
    """Contagem por modelo → por variação, proporcional ao mix de entradas e vendas da variação na Savassi
    (ou na rede, se a Savassi não movimentou o modelo). Maior resto para fechar o total do modelo."""
    variacoes_do_modelo: dict[str, list[int]] = defaultdict(list)
    for variacao_id, sku in ctx.db.execute(select(m.Variacao.id, m.Variacao.sku).join(m.Produto).where(m.Produto.marca == VULTO)):
        if m_sku := re.match(r"VLT-([A-Z]{3})-(\d{3})-", sku):
            if not sku.endswith(SUFIXO_PECA_ANTIGA):
                variacoes_do_modelo[f"{m_sku[1]}-{m_sku[2]}"].append(variacao_id)
    peso_loja, peso_rede = defaultdict(int), defaultdict(int)
    for mov in movs:
        if mov.tipo in ("TRANSFERENCIA_ENTRADA", "ENTRADA", "VENDA"):
            peso_rede[mov.variacao] += abs(mov.quantidade)
            if mov.loja == savassi_id:
                peso_loja[mov.variacao] += abs(mov.quantidade)

    contadas: dict[int, int] = {}
    total_rateado = 0
    for linha, modelo, descricao, quantidade in ctx.db.execute(
        text("SELECT _linha, modelo, descricao, qtd_total FROM legado_vulto.contagem__savassi_por_modelo")
    ):
        origem = f"{ORIGEM_CONTAGEM}:savassi_por_modelo"
        variacoes = variacoes_do_modelo.get((modelo or "").strip().upper(), [])
        total = int(quantidade or 0)
        if not variacoes:
            ctx.ocorrencia(
                "SAVASSI_MODELO_SEM_PRODUTO",
                origem,
                "Modelo da contagem da Savassi que não está no catálogo.",
                "DESCARTADO",
                id_origem=linha,
                original=f"{modelo} {descricao} · {total}",
                impacto=-total,
            )
            continue
        pesos = (
            {v: peso_loja[v] for v in variacoes} if any(peso_loja[v] for v in variacoes) else {v: peso_rede[v] for v in variacoes}
        )
        if not any(pesos.values()):
            pesos = dict.fromkeys(variacoes, 1)
        soma = sum(pesos.values())
        cotas = {v: Decimal(total) * pesos[v] / soma for v in variacoes}
        inteiros = {v: int(c) for v, c in cotas.items()}
        sobra = total - sum(inteiros.values())
        for v in sorted(cotas, key=lambda v: cotas[v] - inteiros[v], reverse=True)[:sobra]:
            inteiros[v] += 1
        for v, q in inteiros.items():
            if q:
                contadas[v] = contadas.get(v, 0) + q
        total_rateado += total
        ctx.ocorrencia(
            "SAVASSI_CONTAGEM_POR_MODELO",
            origem,
            "A Savassi contou por modelo, não por SKU: o total do modelo foi rateado entre as variações pelo mix de entradas e "
            "vendas. Margem de erro: as peças do modelo podem estar em qualquer cor/tamanho (o total da loja é exato).",
            "ESTIMADO",
            id_origem=linha,
            original=f"{modelo} {descricao} · {total}",
            final=", ".join(f"{v}:{q}" for v, q in sorted(inteiros.items()) if q),
            impacto=total,
        )
    ctx.resultado.notas.append(f"Savassi: {total_rateado} peças contadas por modelo e rateadas entre as variações (ESTIMADO)")
    return contadas


# ---------- Reconstrução ----------


def reconstruir(ctx: Contexto, movs: list[Mov], contagens: dict[int, dict[int, int]]) -> dict[tuple[int, int], list[Mov]]:
    """Por loja e variação: abertura estimada, movimentos, ajuste da contagem e movimentos depois dela."""
    por_item: dict[tuple[int, int], list[Mov]] = defaultdict(list)
    for mov in movs:
        por_item[(mov.loja, mov.variacao)].append(mov)
    for loja, contadas in contagens.items():
        for variacao in contadas:
            por_item.setdefault((loja, variacao), [])

    final: dict[tuple[int, int], list[Mov]] = {}
    abertura_total = diferenca_total = negativos = 0
    abertura_por_loja: dict[int, int] = defaultdict(int)
    skus = dict(ctx.db.execute(select(m.Variacao.id, m.Variacao.sku)).all())
    for (loja, variacao), lista in por_item.items():
        lista.sort(key=lambda mov: (mov.quando, mov.tipo != "ENTRADA"))
        _, dia, estimada = CONTAGENS[loja]
        momento_contagem = datetime.combine(dia, FIM_DO_DIA, n.FUSO_ORIGEM)
        antes = [mov for mov in lista if mov.quando <= momento_contagem]
        depois = [mov for mov in lista if mov.quando > momento_contagem]
        saldo, minimo = 0, 0
        for mov in antes:
            saldo += mov.quantidade
            minimo = min(minimo, saldo)
        abertura = -minimo
        saida = []
        if abertura:
            saida.append(
                Mov(loja, variacao, ABERTURA, "AJUSTE", abertura, "abertura estimada (saldo de 01/01/2025 desconhecido)")
            )
            abertura_total += abertura
            abertura_por_loja[loja] += abertura
        saida += antes
        contado = contagens.get(loja, {}).get(variacao, 0)
        diferenca = contado - (saldo + abertura)
        if diferenca:
            saida.append(
                Mov(
                    loja,
                    variacao,
                    momento_contagem,
                    "AJUSTE",
                    diferenca,
                    f"contagem de set/26 ({dia:%d/%m}{', data estimada' if estimada else ''})",
                )
            )
            diferenca_total += abs(diferenca)
            ctx.ocorrencia(
                "CONTAGEM_DIFERE_DO_RECONSTRUIDO",
                f"{ORIGEM_CONTAGEM}:{CONTAGENS[loja][0].split('__')[1]}",
                "O contado em set/26 não bate com o saldo reconstruído (entradas, transferências, vendas e devoluções desde a "
                "abertura estimada): ajuste para o contado. Negativo = peça que sumiu (perda, furto, venda sem registro); "
                "positivo = peça que apareceu (entrada sem registro).",
                "CORRIGIDO",
                id_origem=f"{loja}:{skus.get(variacao, variacao)}",
                original=f"reconstruído {saldo + abertura}",
                final=f"contado {contado}",
                impacto=diferenca,
            )
        saida += depois
        final[(loja, variacao)] = saida
        if contado + sum(mov.quantidade for mov in depois) < 0:
            negativos += 1
    ctx.resultado.notas.append(
        f"abertura estimada: {abertura_total} peças · ajustes da contagem: {diferenca_total} peças (soma das diferenças)"
    )
    for loja, pecas in sorted(abertura_por_loja.items()):
        ctx.ocorrencia(
            "ABERTURA_ESTIMADA",
            ORIGEM_ENTRADAS,
            "Saldo de 01/01/2025 desconhecido: abertura estimada, a menor que deixa o histórico da peça sem saldo negativo "
            "até a contagem (a loja vendeu peças que já tinha antes de 2025). O ajuste da contagem corrige o resto.",
            "ESTIMADO",
            id_origem=loja,
            final=f"{pecas} peças na abertura",
            impacto=pecas,
        )
    if negativos:
        ctx.ocorrencia(
            "SALDO_NEGATIVO_DEPOIS_DA_CONTAGEM",
            ORIGEM_CONTAGEM,
            "Peças que venderam mais do que o contado entre a "
            "contagem e 01/10/2026 (contagem incompleta ou venda sem entrada lançada).",
            "PENDENTE",
            impacto=negativos,
        )
    return final


# ---------- Carga ----------


def _limpar(db: Session, lojas_ids: list[int]) -> None:
    """Refaz o estoque das lojas da Vulto inteiro (só a migração mexe nele até a virada)."""
    estoques = select(m.Estoque.id).where(m.Estoque.loja_id.in_(lojas_ids))
    movimentacoes = select(m.Movimentacao.id).where(m.Movimentacao.estoque_id.in_(estoques))
    db.execute(update(m.Devolucao).where(m.Devolucao.movimentacao_id.in_(movimentacoes)).values(movimentacao_id=None))
    db.execute(delete(m.Movimentacao).where(m.Movimentacao.estoque_id.in_(estoques)))
    db.execute(delete(m.Estoque).where(m.Estoque.loja_id.in_(lojas_ids)))


def migrar(db: Session) -> Resultado:
    ctx = Contexto(db)
    migracao_repository.limpar_ocorrencias(db, DOMINIO)
    lojas = {i: lojas_vulto.loja_da_vulto(db, i) for i in lojas_vulto.LOJAS}
    legado_por_loja = {loja.id: i for i, loja in lojas.items()}
    _limpar(db, list(legado_por_loja))
    catalogo = Catalogo(db)

    movs = ler_entradas(ctx, catalogo) + ler_vendas_e_devolucoes(db, legado_por_loja)
    contagens = {loja: ler_contagem(ctx, catalogo, loja) for loja in CONTAGENS if loja != 3}
    contagens[3] = ratear_savassi(ctx, catalogo, movs, 3)
    ctx.resultado.lidos = db.scalar(text("SELECT count(*) FROM legado_vulto.db__entradas_estoque")) + sum(
        db.scalar(text(f"SELECT count(*) FROM legado_vulto.{tabela}")) for tabela, _, _ in CONTAGENS.values()
    )
    for loja, (_, dia, estimada) in CONTAGENS.items():
        if estimada:
            ctx.ocorrencia(
                "CONTAGEM_SEM_DATA",
                ORIGEM_CONTAGEM,
                f"A planilha não diz o dia da contagem de {lojas[loja].nome}: ajuste em {dia:%d/%m/%Y} (estimativa aprovada). "
                "As vendas entre a contagem real e essa data podem ficar contadas duas vezes ou nenhuma.",
                "ESTIMADO",
                id_origem=loja,
            )

    reconstruido = reconstruir(ctx, movs, contagens)
    total_movs = 0
    devolucoes: list[tuple[m.Movimentacao, int]] = []
    for (loja, variacao), lista in reconstruido.items():
        estoque = m.Estoque(loja_id=lojas[loja].id, variacao_id=variacao, quantidade=0, quantidade_min=2)
        db.add(estoque)
        saldo = 0
        for mov in lista:
            saldo += mov.quantidade
            movimentacao = m.Movimentacao(
                estoque=estoque,
                tipo=mov.tipo,
                quantidade=mov.quantidade,
                origem=mov.origem[:255],
                saldo_resultante=saldo,
                criado_em=mov.quando,
            )
            db.add(movimentacao)
            if mov.devolucao_id:
                devolucoes.append((movimentacao, mov.devolucao_id))
            total_movs += 1
        estoque.quantidade = saldo
        estoque.atualizado_em = lista[-1].quando if lista else datetime.combine(CONTAGENS[loja][1], FIM_DO_DIA, n.FUSO_ORIGEM)
    db.flush()
    for movimentacao, devolucao_id in devolucoes:
        db.execute(update(m.Devolucao).where(m.Devolucao.id == devolucao_id).values(movimentacao_id=movimentacao.id))
    _comparar_com_o_legado(ctx, catalogo, reconstruido)

    ctx.resultado.carregados = total_movs
    ctx.resultado.ocorrencias = migracao_repository.ocorrencias_por_acao(db, DOMINIO)
    ctx.resultado.notas.insert(0, f"estoques (loja × variação): {len(reconstruido)} · movimentações: {total_movs}")
    return ctx.resultado


def _comparar_com_o_legado(ctx: Contexto, catalogo: Catalogo, reconstruido: dict[tuple[int, int], list[Mov]]) -> None:
    """A tabela estoque da Vulto não entra: só se compara com o saldo reconstruído em 01/10/2026."""
    nosso = {chave: sum(mov.quantidade for mov in lista) for chave, lista in reconstruido.items()}
    legado: dict[tuple[int, int], int] = defaultdict(int)
    virtuais = negativos = sem_produto = 0
    for sku, loja, quantidade in ctx.db.execute(text("SELECT sku, loja_id::int, qtd::int FROM legado_vulto.db__estoque")):
        negativos += quantidade < 0
        if loja in (5, 6):
            virtuais += quantidade
            continue
        variacao = catalogo.variacao(sku, date(2026, 9, 30))
        if variacao is None:
            sem_produto += 1
            continue
        legado[(loja, variacao)] += quantidade
    chaves = set(legado) | set(nosso)
    iguais = sum(1 for c in chaves if legado.get(c, 0) == nosso.get(c, 0))
    diferenca = sum(abs(legado.get(c, 0) - nosso.get(c, 0)) for c in chaves)
    ctx.ocorrencia(
        "ESTOQUE_DO_LEGADO_SO_COMPARACAO",
        "vulto.db:estoque",
        f"A tabela estoque da Vulto não tem histórico e tem {negativos} saldos negativos: não entra, só se compara. Dos "
        f"{len(chaves)} itens (loja × peça), {iguais} batem com o saldo reconstruído; a soma das diferenças é {diferenca} peças.",
        "DESCARTADO",
        original=f"{sum(legado.values())} peças nas lojas e no CD",
        final=f"{sum(nosso.values())} peças reconstruídas",
        impacto=sum(nosso.values()) - sum(legado.values()),
    )
    ctx.ocorrencia(
        "ESTOQUE_DAS_LOJAS_VIRTUAIS",
        "vulto.db:estoque",
        'Saldo das "lojas" site (5) e app (6) do legado: não existe estoque físico lá (site e app vendem do CD); desconsiderado.',
        "DESCARTADO",
        original=f"{virtuais} peças",
        impacto=-virtuais,
    )
