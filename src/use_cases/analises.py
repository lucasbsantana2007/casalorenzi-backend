"""Análises da operação para o copiloto gerencial e para as automações. Só leitura.

Nenhuma conta de negócio é refeita aqui: o faturamento é o de financeiro.resumo (a regra da diretoria),
o status do estoque é o de src/entities/estoque.py, o saldo livre é o de estoque_repository.livres_por_loja
(que desconta reservas e soma o que está a caminho) e os pontos usam os lotes do Helo de
src/use_cases/fidelidade.py. Aqui só se recorta, agrupa e ordena o que essas regras devolvem.

marca: a marca que a pessoa pode ver (None = as duas). lojas: ids já conferidos contra essa marca.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from src import models as m
from src.config.settings import FUSO
from src.entities import fidelidade as regra_pontos
from src.entities.estoque import status_estoque
from src.entities.marca import MARCAS, na_marca
from src.entities.periodo import Periodo
from src.entities.produto import STATUS_VENDAVEIS
from src.repositories import analise_repository, cadastro_repository, estoque_repository, fidelidade_repository
from src.use_cases import financeiro
from src.use_cases.fidelidade import lotes_em_aberto
from src.utils.datas import agora, hoje, inicio_do_dia

CENTAVO = Decimal("0.01")


def reais(valor) -> Decimal:
    """float do financeiro (somas com resto de ponto flutuante) -> Decimal com 2 casas."""
    return Decimal(str(valor or 0)).quantize(CENTAVO)


def _intervalo(periodo: Periodo) -> tuple[datetime, datetime]:
    return inicio_do_dia(periodo.inicio), inicio_do_dia(periodo.fim + timedelta(days=1))


def dados_ate(db: Session, marca: str | None) -> datetime | None:
    """Data do pedido mais recente: até onde vão os dados de vendas."""
    return analise_repository.ultimo_pedido_em(db, marca)


# ---------- Vendas ----------


def _resumo(db: Session, periodo: Periodo, *, marca, lojas, canal, comparar: str, agrupar: str = "dia") -> dict:
    return financeiro.resumo(
        db,
        de=periodo.inicio.isoformat(),
        ate=periodo.fim.isoformat(),
        comparar=comparar,
        agrupar=agrupar,
        lojas=",".join(str(i) for i in lojas) if lojas else None,
        canais=canal,
        categorias=None,
        generos=None,
        marca=marca,
    )


def _metricas(resumo: dict, sufixo: str = "") -> dict:
    receita = reais(resumo[f"receita{sufixo}"])
    pedidos = resumo[f"pedidos{sufixo}"] or 0
    return {
        "faturamento": reais(resumo[f"receitaLiquida{sufixo}"]),
        "receitaBruta": receita,
        "devolucoes": reais(resumo[f"devolucoesValor{sufixo}"]),
        "pedidos": pedidos,
        "pecas": resumo[f"pecas{sufixo}"] or 0,
        "ticketMedio": (receita / pedidos).quantize(CENTAVO) if pedidos else Decimal("0.00"),
    }


def faturamento(
    db: Session,
    periodo: Periodo,
    *,
    marca: str | None,
    lojas: list[int] | None = None,
    canal: str | None = None,
    comparar: str = "nenhum",
    agrupar: str = "dia",
) -> dict:
    """Faturamento oficial do período (financeiro.resumo), com a comparação pedida ('anterior' ou 'ano')."""
    resumo = _resumo(db, periodo, marca=marca, lojas=lojas, canal=canal, comparar=comparar, agrupar=agrupar)
    resultado = {
        **_metricas(resumo),
        "cancelados": resumo["cancelados"],
        "serie": [{"data": p["data"], "valor": reais(p["receita"])} for p in resumo["serie"]],
        "porLoja": [
            {
                "lojaId": linha["loja"]["id"],
                "loja": linha["loja"]["nome"],
                "marca": linha["loja"]["marca"],
                "tipo": linha["loja"]["tipo"],
                "faturamento": reais(linha["receitaLiquida"]),
                "receitaBruta": reais(linha["receita"]),
                "devolucoes": reais(linha["devolucoes"]),
                "pedidos": linha["pedidos"],
            }
            for linha in resumo["porLoja"]
        ],
        "porCanal": [
            {
                "canal": linha["canal"],
                "faturamento": reais(linha["receitaLiquida"]),
                "receitaBruta": reais(linha["receita"]),
                "devolucoes": reais(linha["devolucoes"]),
                "pedidos": linha["pedidos"],
            }
            for linha in resumo["porCanal"]
        ],
        "porCategoria": [
            {"categoria": linha["categoria"], "receitaItens": reais(linha["receita"])}
            for linha in resumo["porCategoria"]
            if linha["receita"]
        ],
        "anterior": _metricas(resumo, "Anterior") if comparar != "nenhum" else None,
    }
    if comparar != "nenhum":
        anterior = resultado["anterior"]["faturamento"]
        resultado["variacao"] = ((resultado["faturamento"] - anterior) / anterior) if anterior else None
    return resultado


def faturamento_por_marca(db: Session, periodo: Periodo, *, marca: str | None, lojas=None, canal=None) -> list[dict]:
    """Uma linha por marca que a pessoa vê. Usa as lojas de cada marca (a soma fecha com o total)."""
    por_loja = faturamento(db, periodo, marca=marca, lojas=lojas, canal=canal)["porLoja"]
    linhas = []
    for nome in MARCAS:
        if not na_marca(marca, nome):
            continue
        da_marca = [linha for linha in por_loja if linha["marca"] == nome]
        linhas.append(
            {
                "marca": nome,
                "faturamento": sum((linha["faturamento"] for linha in da_marca), Decimal("0.00")),
                "receitaBruta": sum((linha["receitaBruta"] for linha in da_marca), Decimal("0.00")),
                "devolucoes": sum((linha["devolucoes"] for linha in da_marca), Decimal("0.00")),
                "pedidos": sum(linha["pedidos"] for linha in da_marca),
            }
        )
    return linhas


def mais_vendidos(
    db: Session,
    periodo: Periodo,
    *,
    marca: str | None,
    lojas: list[int] | None = None,
    canal: str | None = None,
    categoria: str | None = None,
    ordenar_por: str = "pecas",
    limite: int = 10,
) -> list[dict]:
    inicio, fim = _intervalo(periodo)
    linhas = analise_repository.mais_vendidos(
        db, inicio, fim, marca=marca, lojas=lojas, canal=canal, categoria=categoria, ordenar_por=ordenar_por, limite=limite
    )
    return [
        {
            "produtoId": linha.id,
            "produto": linha.nome,
            "marca": linha.marca,
            "categoria": linha.categoria,
            "pecas": int(linha.pecas or 0),
            "valor": reais(linha.valor),
            "pedidos": int(linha.pedidos or 0),
        }
        for linha in linhas
    ]


def cancelamentos(db: Session, periodo: Periodo, *, marca: str | None, lojas: list[int] | None = None) -> dict:
    """Pedidos de venda cancelados no período: quantos, quanto somavam, por motivo de origem e por canal."""
    inicio, fim = _intervalo(periodo)
    linhas = analise_repository.pedidos_de_venda(db, inicio, fim, marca=marca, lojas=lojas)
    canceladas = [linha for linha in linhas if linha.status == "CANCELADO"]
    total_pedidos = sum(int(linha.quantidade) for linha in linhas)
    quantidade = sum(int(linha.quantidade) for linha in canceladas)
    por_motivo: dict[str, list] = defaultdict(lambda: [0, Decimal("0")])
    por_canal: dict[str, list] = defaultdict(lambda: [0, Decimal("0")])
    for linha in canceladas:
        motivo = linha.status_origem or "Cancelado na plataforma"
        por_motivo[motivo][0] += int(linha.quantidade)
        por_motivo[motivo][1] += Decimal(linha.valor)
        por_canal[linha.canal][0] += int(linha.quantidade)
        por_canal[linha.canal][1] += Decimal(linha.valor)
    return {
        "quantidade": quantidade,
        "valor": sum((Decimal(linha.valor) for linha in canceladas), Decimal("0")).quantize(CENTAVO),
        "pedidosNoPeriodo": total_pedidos,
        "taxa": (Decimal(quantidade) / Decimal(total_pedidos)) if total_pedidos else Decimal("0"),
        "porMotivo": [
            {"motivo": motivo, "quantidade": q, "valor": v.quantize(CENTAVO)}
            for motivo, (q, v) in sorted(por_motivo.items(), key=lambda item: -item[1][0])
        ],
        "porCanal": [
            {"canal": canal, "quantidade": q, "valor": v.quantize(CENTAVO)}
            for canal, (q, v) in sorted(por_canal.items(), key=lambda item: -item[1][0])
        ],
    }


# ---------- Estoque ----------


def _estoques_vendaveis(db: Session, *, marca: str | None, loja_id: int | None = None, categoria: str | None = None):
    """Itens de estoque de peças ativas e vendáveis, em lojas ativas da marca."""
    return [
        e
        for e in estoque_repository.listar(db, loja_id=loja_id, categoria=categoria)
        if e.loja.ativa and na_marca(marca, e.loja.marca) and e.variacao.produto.ativo and e.variacao.status in STATUS_VENDAVEIS
    ]


def _item(e: m.Estoque) -> dict:
    v = e.variacao
    return {
        "estoqueId": e.id,
        "lojaId": e.loja_id,
        "loja": e.loja.nome,
        "marca": e.loja.marca,
        "produtoId": v.produto_id,
        "produto": v.produto.nome,
        "categoria": v.produto.categoria.nome,
        "variacaoId": v.id,
        "sku": v.sku,
        "cor": v.cor,
        "tamanho": v.tamanho,
        "quantidade": e.quantidade,
        "minimo": e.quantidade_min,
    }


def estoque_baixo(
    db: Session,
    *,
    marca: str | None,
    loja_id: int | None = None,
    categoria: str | None = None,
    somente_com_demanda: bool = True,
    janela_dias: int = 60,
    limite: int = 20,
) -> dict:
    """Itens no mínimo ou zerados (status_estoque). Com demanda: a peça vendeu naquele local na janela.
    Ordem: zerados primeiro, depois quem mais vendeu na janela."""
    desde = agora() - timedelta(days=janela_dias)
    vendas = analise_repository.vendas_por_estoque_desde(db, desde)
    itens = []
    for e in _estoques_vendaveis(db, marca=marca, loja_id=loja_id, categoria=categoria):
        status = status_estoque(e.quantidade, e.quantidade_min)
        if status == "NORMAL":
            continue
        vendidas = vendas.get(e.id, 0)
        if somente_com_demanda and vendidas <= 0:
            continue
        itens.append({**_item(e), "status": status, "vendasJanela": vendidas})
    if itens:
        livres = estoque_repository.livres_por_loja(db, list({i["variacaoId"] for i in itens}))
        for item in itens:
            item["livre"] = max(livres.get((item["lojaId"], item["variacaoId"]), item["quantidade"]), 0)
    itens.sort(key=lambda i: (i["status"] != "SEM_ESTOQUE", -i["vendasJanela"], i["produto"], i["loja"]))
    return {
        "total": len(itens),
        "zerados": sum(1 for i in itens if i["status"] == "SEM_ESTOQUE"),
        "janelaDias": janela_dias,
        "itens": itens[:limite],
    }


def estoque_parado(db: Session, *, marca: str | None, loja_id: int | None = None, dias: int = 30, limite: int = 20) -> dict:
    """Itens com saldo e sem venda no local há `dias` dias ou mais. Ordem: maior valor parado primeiro."""
    referencia = hoje()
    ultima = analise_repository.ultima_venda_por_estoque(db)
    primeira = analise_repository.primeira_movimentacao_por_estoque(db)
    itens = []
    for e in _estoques_vendaveis(db, marca=marca, loja_id=loja_id):
        if e.quantidade <= 0:
            continue
        ultima_venda = ultima.get(e.id)
        desde = ultima_venda or primeira.get(e.id)
        if desde is None:
            continue
        sem_venda = (referencia - desde.astimezone(FUSO).date()).days
        if sem_venda < dias:
            continue
        preco = e.variacao.preco_vigente
        itens.append(
            {
                **_item(e),
                "ultimaVenda": ultima_venda,
                "diasSemVenda": sem_venda,
                "nuncaVendeuNoLocal": ultima_venda is None,
                "valor": (preco * e.quantidade).quantize(CENTAVO),
            }
        )
    itens.sort(key=lambda i: (-i["valor"], -i["diasSemVenda"]))
    por_loja: dict[int, dict] = {}
    for item in itens:
        linha = por_loja.setdefault(
            item["lojaId"],
            {
                "lojaId": item["lojaId"],
                "loja": item["loja"],
                "marca": item["marca"],
                "itens": 0,
                "pecas": 0,
                "valor": Decimal("0.00"),
            },
        )
        linha["itens"] += 1
        linha["pecas"] += item["quantidade"]
        linha["valor"] += item["valor"]
    return {
        "dias": dias,
        "total": len(itens),
        "pecas": sum(i["quantidade"] for i in itens),
        "valor": sum((i["valor"] for i in itens), Decimal("0.00")),
        "porLoja": sorted(por_loja.values(), key=lambda linha: -linha["valor"]),
        "itens": itens[:limite],
    }


def estoque_por_loja(db: Session, *, marca: str | None) -> list[dict]:
    """Peças e valor (peças × preço de venda do produto, como no dashboard) de cada loja e CD."""
    linhas: dict[int, dict] = {}
    for loja in cadastro_repository.lojas(db, somente_ativas=True):
        if na_marca(marca, loja.marca):
            linhas[loja.id] = {
                "lojaId": loja.id,
                "loja": loja.nome,
                "marca": loja.marca,
                "tipo": loja.tipo,
                "pecas": 0,
                "skus": 0,
                "valor": Decimal("0.00"),
            }
    for e in _estoques_vendaveis(db, marca=marca):
        linha = linhas.get(e.loja_id)
        if linha is None or e.quantidade <= 0:
            continue
        linha["pecas"] += e.quantidade
        linha["skus"] += 1
        linha["valor"] += (Decimal(e.variacao.produto.preco_base) * e.quantidade).quantize(CENTAVO)
    total = sum(linha["pecas"] for linha in linhas.values())
    for linha in linhas.values():
        linha["participacao"] = (Decimal(linha["pecas"]) / Decimal(total)) if total else Decimal("0")
    return sorted(linhas.values(), key=lambda linha: -linha["pecas"])


def maiores_estoques(db: Session, *, marca: str | None, loja_id: int | None = None, limite: int = 10) -> list[dict]:
    """Produtos com mais peças em estoque (somadas nos locais do escopo)."""
    produtos: dict[int, dict] = {}
    for e in _estoques_vendaveis(db, marca=marca, loja_id=loja_id):
        if e.quantidade <= 0:
            continue
        p = e.variacao.produto
        linha = produtos.setdefault(
            p.id,
            {
                "produtoId": p.id,
                "produto": p.nome,
                "marca": p.marca,
                "categoria": p.categoria.nome,
                "pecas": 0,
                "locais": set(),
                "valor": Decimal("0.00"),
            },
        )
        linha["pecas"] += e.quantidade
        linha["locais"].add(e.loja_id)
        linha["valor"] += (Decimal(p.preco_base) * e.quantidade).quantize(CENTAVO)
    linhas = sorted(produtos.values(), key=lambda linha: (-linha["pecas"], linha["produto"]))[:limite]
    return [{**linha, "locais": len(linha["locais"])} for linha in linhas]


def avarias(db: Session, *, marca: str | None, loja_id: int | None = None, periodo: Periodo | None = None) -> dict:
    inicio, fim = _intervalo(periodo) if periodo else (None, None)
    linhas = analise_repository.avarias(db, inicio, fim, marca=marca, loja_id=loja_id)
    por_produto: dict[int, dict] = {}
    por_loja: dict[int, dict] = {}
    for linha in linhas:
        pecas = -int(linha.quantidade)
        produto = por_produto.setdefault(
            linha.produto_id,
            {"produtoId": linha.produto_id, "produto": linha.produto, "pecas": 0, "estimadas": 0, "ultima": linha.criado_em},
        )
        produto["pecas"] += pecas
        produto["estimadas"] += pecas if linha.estimado else 0
        loja = por_loja.setdefault(linha.loja_id, {"lojaId": linha.loja_id, "loja": linha.loja, "pecas": 0, "estimadas": 0})
        loja["pecas"] += pecas
        loja["estimadas"] += pecas if linha.estimado else 0
    return {
        "registros": len(linhas),
        "pecas": sum(p["pecas"] for p in por_produto.values()),
        "estimadas": sum(p["estimadas"] for p in por_produto.values()),
        "porLoja": sorted(por_loja.values(), key=lambda linha: -linha["pecas"]),
        "porProduto": sorted(por_produto.values(), key=lambda linha: -linha["pecas"]),
    }


@dataclass
class _Local:
    loja: m.Loja
    estoque: m.Estoque
    livre: int


def sugestoes_transferencia(db: Session, *, marca: str | None, janela_dias: int = 60, limite: int = 10) -> list[dict]:
    """Peças que faltam numa loja que as vende e sobram em outro local da mesma marca. Só sugere: quem
    decide e cria a transferência é a equipe (tela de transferências).

    Destino: loja (não o CD) com o item no mínimo ou zerado e venda da peça na janela. Origem: loja ou CD
    da mesma marca com saldo livre acima do dobro do próprio mínimo (fica com o dobro do mínimo depois de
    mandar). Quantidade: o que leva o destino ao dobro do mínimo dele, sem passar do excedente da origem."""
    baixos = estoque_baixo(db, marca=marca, somente_com_demanda=True, janela_dias=janela_dias, limite=10_000)["itens"]
    lojas_fisicas = {loja.id for loja in cadastro_repository.lojas(db, somente_ativas=True, tipo="LOJA")}
    destinos = [i for i in baixos if i["lojaId"] in lojas_fisicas]
    if not destinos:
        return []
    variacoes = list({i["variacaoId"] for i in destinos})
    livres = estoque_repository.livres_por_loja(db, variacoes)
    por_variacao: dict[int, list[m.Estoque]] = defaultdict(list)
    for e in _estoques_vendaveis(db, marca=marca):
        if e.variacao_id in variacoes:
            por_variacao[e.variacao_id].append(e)
    sugestoes = []
    for destino in destinos:
        necessidade = max(destino["minimo"] * 2 - destino["livre"], 1)
        candidatos = []
        for e in por_variacao[destino["variacaoId"]]:
            if e.loja_id == destino["lojaId"] or e.loja.marca != destino["marca"]:
                continue
            livre = livres.get((e.loja_id, e.variacao_id), e.quantidade)
            excedente = min(livre, e.quantidade) - e.quantidade_min * 2
            if excedente > 0:
                candidatos.append((excedente, e))
        if not candidatos:
            continue
        excedente, origem = max(candidatos, key=lambda c: (c[0], c[1].loja.tipo == "CD", -c[1].loja_id))
        quantidade = min(necessidade, excedente)
        sugestoes.append(
            {
                **{k: destino[k] for k in ("produtoId", "produto", "variacaoId", "sku", "cor", "tamanho", "marca")},
                "origemId": origem.loja_id,
                "origem": origem.loja.nome,
                "destinoId": destino["lojaId"],
                "destino": destino["loja"],
                "quantidade": quantidade,
                "saldoOrigem": origem.quantidade,
                "livreDestino": destino["livre"],
                "minimoDestino": destino["minimo"],
                "vendasDestino": destino["vendasJanela"],
            }
        )
    sugestoes.sort(key=lambda s: (-s["vendasDestino"], s["livreDestino"], s["produto"]))
    return sugestoes[:limite]


# ---------- Helo ----------


def fidelidade(db: Session, *, dias_a_vencer: int = 30, referencia: date | None = None, com_ids: bool = False) -> dict:
    """Números do programa sem dado pessoal: pontos válidos (passivo), valor em reais, clientes por
    categoria e o que vence nos próximos dias. Pontos já vencidos que ainda não foram baixados (o
    vencimento é lançado na próxima consulta ou compra de cada cliente) aparecem à parte."""
    referencia = referencia or hoje()
    limite_vencimento = referencia + timedelta(days=dias_a_vencer)
    por_cliente: dict[int, list] = defaultdict(list)
    for mov in fidelidade_repository.movimentos_de_todos(db):
        por_cliente[mov.cliente_id].append(mov)
    categorias = {nome: {"clientes": 0, "pontos": 0} for nome in regra_pontos.CATEGORIAS_FIDELIDADE}
    validos = vencidos_pendentes = a_vencer = clientes_a_vencer = 0
    a_vencer_por_categoria: dict[str, int] = defaultdict(int)
    ids_a_vencer: list[int] = []
    for cliente_id, movimentos in por_cliente.items():
        lotes = lotes_em_aberto(movimentos)
        saldo = sum(pontos for vence, pontos in lotes if vence >= referencia)
        vencidos_pendentes += sum(pontos for vence, pontos in lotes if vence < referencia)
        vencendo = sum(pontos for vence, pontos in lotes if referencia <= vence <= limite_vencimento)
        validos += saldo
        categoria = regra_pontos.categoria_pelo_saldo(saldo)
        if categoria:
            categorias[categoria]["clientes"] += 1
            categorias[categoria]["pontos"] += saldo
        if vencendo:
            a_vencer += vencendo
            clientes_a_vencer += 1
            ids_a_vencer.append(cliente_id)
            a_vencer_por_categoria[categoria or "SEM_CATEGORIA"] += 1
    resultado = {
        "referencia": referencia,
        "clientesComSaldo": sum(c["clientes"] for c in categorias.values()),
        "pontosValidos": validos,
        "valorValidos": regra_pontos.valor_em_reais(validos),
        "porCategoria": [{"categoria": nome, **dados} for nome, dados in categorias.items()],
        "diasAVencer": dias_a_vencer,
        "pontosAVencer": a_vencer,
        "valorAVencer": regra_pontos.valor_em_reais(a_vencer),
        "clientesAVencer": clientes_a_vencer,
        "clientesAVencerPorCategoria": dict(a_vencer_por_categoria),
        "vencidosNaoBaixados": vencidos_pendentes,
    }
    if com_ids:
        # Só para as automações contarem quem aceita contato; nunca vai para a tela nem para o modelo
        resultado["idsAVencer"] = ids_a_vencer
    return resultado
