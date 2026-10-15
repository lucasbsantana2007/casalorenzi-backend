"""Domínio produtos: o catálogo da Vulto vira produtos e variações da marca VULTO.

Origem: as abas do catálogo no staging (Verão 25, Inverno 25, Verão 26, a sub-tabela Inverno 26 dentro
da aba Verão 26, Atemporais) e a planilha antiga de 2024, que ainda tem peças vendidas em 2025–26.

- Produto = modelo (CAT-NNN); variação = cor + tamanho, com o SKU canônico VLT-CAT-NNN-COR-TAM.
  Linhas de vários tamanhos ("P/M/G/GG") viram uma variação por tamanho.
- Código reaproveitado (regra 8 de Compras): o modelo da planilha antiga com outro nome é outra peça.
  Ela vira outro produto (inativo, SKU com sufixo -2024), e as grafias que as duas peças compartilham
  ganham vigência: até a véspera do lançamento da peça nova, apontam para a antiga.
- Todas as grafias (catálogo, vendas, entradas, estoque, contagem) vão para sku_alias.
- Preço: o mais frequente da aba (os outros viram ocorrência); entre coleções vale REGRA_PRECO.
- Custo: preco_custo = último custo (o da aba mais recente; sem ele, a última nota de entrada);
  custo_medio = média ponderada das notas de entrada (entradas com NF e custo).
- Descontinuada (linha tachada ou vermelha na aba mais recente) = variação inativa; o produto fica
  inativo quando todas estão. Peças só da planilha antiga ficam inativas.
- Vendido como DIVERSO ou PRODUTO SEM CADASTRO: produto "não catalogado" (categoria própria).
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from src import models as m
from src.entities.marca import VULTO
from src.migracao_vulto import normalizacao as n
from src.migracao_vulto.relatorio import Resultado
from src.migracao_vulto.staging import SCHEMA
from src.repositories import migracao_repository

DOMINIO = "produtos"
ARQUIVO = "catalogo.xlsx"

# Peça em mais de uma coleção: Compras (Marina) diz que vale o preço da coleção mais nova; Operações
# e Financeiro (Diego, REGRAS_OPERACAO.txt, que prevalece) dizem que vale o menor, por causa do Procon.
REGRA_PRECO = "MENOR"  # ou "MAIS_NOVA"

# Grafias vendidas sem produto: viram um produto "não catalogado"
GRAFIAS_NAO_CATALOGADO = {"DIVERSO", "PRODUTO SEM CADASTRO"}
SKU_NAO_CATALOGADO = "VLT-NAO-CATALOGADO"
SUFIXO_PECA_ANTIGA = "-2024"

COR_DESCONTINUADO = ("FFFF0000", "FFC00000")  # vermelho e vermelho-escuro
COR_REVISAR_PRECO = "FFFFFF00"  # amarelo


@dataclass(frozen=True, eq=False)
class Colecao:
    nome: str
    aba: str
    tabela: str
    ordem: int  # mais nova = maior
    estacao: str | None
    valida: bool  # False: planilha antiga (2024), só referência
    colunas: dict = field(compare=False, hash=False)  # campo padrão → coluna no staging

    def __hash__(self) -> int:
        return hash(self.nome)

    def __eq__(self, outra) -> bool:
        return isinstance(outra, Colecao) and outra.nome == self.nome


_COLUNAS_PADRAO = ("sku", "nome", "categoria", "cor", "tamanho", "preco", "custo", "ean")
COLECOES = (
    Colecao(
        "2024 (planilha antiga)",
        "PLANILHA ANTIGA NAO USAR",
        "catalogo__planilha_antiga_nao_usar",
        0,
        None,
        False,
        dict(zip(_COLUNAS_PADRAO, ("sku", "descricao", "grupo", "cor", "tam", "preco", "custo", "ean"), strict=True)),
    ),
    Colecao(
        "Verão 25",
        "VERAO 25",
        "catalogo__verao_25",
        1,
        "Verão",
        True,
        dict(zip(_COLUNAS_PADRAO, ("sku", "produto", "categoria", "cor", "tam", "preco", "custo", "ean"), strict=True)),
    ),
    Colecao(
        "Inverno 25",
        "inverno25",
        "catalogo__inverno25",
        2,
        "Inverno",
        True,
        dict(
            zip(_COLUNAS_PADRAO, ("cod", "descricao", "cat", "cor", "tamanho", "preco_venda", "custo_unit", "ean13"), strict=True)
        ),
    ),
    Colecao(
        "Verão 26",
        "Verão 26",
        "catalogo__verao_26",
        3,
        "Verão",
        True,
        dict(zip(_COLUNAS_PADRAO, ("codigo", "nome", "categoria", "cor", "tamanho", "preco_r", "custo", "ean"), strict=True)),
    ),
    # Atemporais: preço revisado todo ano em março (mar/26), depois do lançamento do Verão 26
    Colecao(
        "Atemporais",
        "Atemporais",
        "catalogo__atemporais",
        4,
        "Atemporal",
        True,
        dict(zip(_COLUNAS_PADRAO, ("sku", "nome", "categoria", "cor", "tam", "preco", "custo_medio", "ean"), strict=True)),
    ),
    # Sub-tabela "INVERNO 26 (provisório - Marina)" dentro da aba Verão 26
    Colecao(
        "Inverno 26",
        "Verão 26",
        "catalogo__verao_26",
        5,
        "Inverno",
        True,
        dict(zip(_COLUNAS_PADRAO, ("codigo", "nome", "categoria", "cor", "tamanho", "preco_r", "custo", "ean"), strict=True)),
    ),
)
MARCADOR_INVERNO_26 = "INVERNO 26"


@dataclass
class Linha:
    """Uma linha do catálogo, já com a chave do SKU (uma por tamanho, nas linhas de vários tamanhos)."""

    colecao: Colecao
    numero: int
    sku: str
    chave: n.ChaveSku
    nome: str
    categoria: str | None
    cor: str | None
    preco: str | None
    custo: str | None
    ean: str | None
    descontinuada: bool
    revisar_preco: bool
    lancamento: str | None
    expandida: bool = False

    @property
    def origem(self) -> str:
        return f"{ARQUIVO}:{self.colecao.aba}"

    @property
    def id_origem(self) -> str:
        return f"{self.numero}:{self.chave.tamanho}" if self.expandida else str(self.numero)


@dataclass
class Peca:
    """Um produto a criar: um modelo (ou a versão antiga de um modelo reaproveitado)."""

    modelo: str
    antiga: bool = False  # versão 2024 de um código reaproveitado
    linhas: list[Linha] = field(default_factory=list)

    @property
    def id_origem(self) -> str:
        return f"{self.modelo}@2024" if self.antiga else self.modelo

    @property
    def validas(self) -> list[Linha]:
        return [linha for linha in self.linhas if linha.colecao.valida]


@dataclass
class Contexto:
    """O que a migração vai acumulando: ocorrências e contadores do relatório."""

    db: Session
    resultado: Resultado
    corrigidas: set = field(default_factory=set)

    def ocorrencia(
        self, codigo, origem, descricao, acao, *, id_origem=None, original=None, final=None, impacto=None, unidade=None
    ):
        migracao_repository.registrar_ocorrencia(
            self.db,
            codigo_problema=codigo,
            dominio=DOMINIO,
            origem=origem,
            id_origem=id_origem,
            descricao=descricao,
            acao_tomada=acao,
            valor_original=None if original is None else str(original),
            valor_final=None if final is None else str(final),
            impacto=impacto,
            impacto_unidade=unidade,
        )
        if acao == "CORRIGIDO" and id_origem:
            self.corrigidas.add((origem, id_origem))


def _moeda(valor: Decimal | None) -> str:
    return "—" if valor is None else f"R$ {valor:.2f}".replace(".", ",")


# ---------- Leitura do catálogo ----------


def _ler(db: Session, tabela: str, colunas: dict, extras: tuple[str, ...] = ()) -> pd.DataFrame:
    selecao = ", ".join([f'"{origem}" AS {padrao}' for padrao, origem in colunas.items()] + list(extras))
    return pd.read_sql(
        text(f'SELECT _linha, _tachado, _cor_fundo, {selecao} FROM {SCHEMA}."{tabela}" ORDER BY _linha'), db.connection()
    )


def ler_catalogo(ctx: Contexto) -> list[Linha]:
    linhas: list[Linha] = []
    lidas = 0
    inicio_inverno_26 = None
    for colecao in COLECOES:
        extras = ("lancamento",) if colecao.tabela == "catalogo__verao_26" else ()
        tabela = _ler(ctx.db, colecao.tabela, colecao.colunas, extras)
        if colecao.tabela == "catalogo__verao_26":
            marcador = tabela[tabela["sku"].fillna("").str.startswith(MARCADOR_INVERNO_26)]["_linha"]
            inicio_inverno_26 = int(marcador.iloc[0]) if len(marcador) else None
            if inicio_inverno_26 is None:
                raise RuntimeError("Sub-tabela INVERNO 26 não encontrada na aba Verão 26")
            # A linha do título e a do cabeçalho da sub-tabela não são produtos
            tabela = tabela[~tabela["_linha"].isin((inicio_inverno_26, inicio_inverno_26 + 1))]
            no_inverno = tabela["_linha"] > inicio_inverno_26
            tabela = tabela[no_inverno] if colecao.nome == "Inverno 26" else tabela[~no_inverno]
        for r in tabela.to_dict("records"):
            r = {k: (None if pd.isna(v) else v) for k, v in r.items()}
            if not r["sku"]:
                continue
            lidas += 1
            linhas += _interpretar_linha(ctx, colecao, r)
    ctx.resultado.lidos = lidas
    return linhas


def _interpretar_linha(ctx: Contexto, colecao: Colecao, r: dict) -> list[Linha]:
    origem, numero = f"{ARQUIVO}:{colecao.aba}", str(r["_linha"])
    try:
        chave = n.interpretar_sku(r["sku"])
    except n.ValorInvalido as erro:
        ctx.ocorrencia(
            "SKU_ILEGIVEL", origem, f"Linha sem SKU reconhecível: {erro}", "DESCARTADO", id_origem=numero, original=r["sku"]
        )
        ctx.resultado.descartados += 1
        return []
    fundos = (r["_cor_fundo"] or "").split(",")
    descontinuada = r["_tachado"] == "1" or any(c in COR_DESCONTINUADO for c in fundos)
    base = dict(
        colecao=colecao,
        numero=int(r["_linha"]),
        sku=r["sku"],
        nome=n.nome_pessoa(r["nome"]) or "",
        categoria=r["categoria"],
        cor=r["cor"],
        preco=r["preco"],
        custo=r["custo"],
        ean=r["ean"],
        descontinuada=descontinuada,
        revisar_preco=COR_REVISAR_PRECO in fundos,
        lancamento=r.get("lancamento"),
    )
    # A cor vem do SKU; a coluna cor só completa quando o SKU não a traz e serve para conferir
    try:
        cor_coluna = n.codigo_cor(r["cor"])
    except n.ValorInvalido:
        cor_coluna = None
    if chave.cor and cor_coluna and cor_coluna != chave.cor:
        ctx.ocorrencia(
            "COR_DIVERGE_DO_SKU",
            origem,
            "A coluna cor não bate com a cor do SKU: vale o SKU.",
            "MANTIDO",
            id_origem=numero,
            original=r["cor"],
            final=n.CORES[chave.cor],
        )
    cor = chave.cor or cor_coluna
    if cor is None:
        ctx.ocorrencia(
            "SEM_COR",
            origem,
            "Linha sem cor reconhecível no SKU nem na coluna cor.",
            "DESCARTADO",
            id_origem=numero,
            original=f"{r['sku']} · {r['cor']}",
        )
        ctx.resultado.descartados += 1
        return []

    if chave.tamanho:
        try:
            tam_coluna = n.tamanho(r["tamanho"])
        except n.ValorInvalido:
            tam_coluna = None
        if tam_coluna and tam_coluna != chave.tamanho:
            ctx.ocorrencia(
                "TAMANHO_DIVERGE_DO_SKU",
                origem,
                "A coluna tamanho não bate com o SKU: vale o SKU.",
                "MANTIDO",
                id_origem=numero,
                original=r["tamanho"],
                final=chave.tamanho,
            )
        return [Linha(chave=n.ChaveSku(chave.categoria, chave.numero, cor, chave.tamanho), **base)]

    tams = n.tamanhos(r["tamanho"])
    ctx.ocorrencia(
        "LINHA_VARIOS_TAMANHOS",
        origem,
        "Uma linha para vários tamanhos: vira uma variação por tamanho, com o mesmo preço e custo e sem EAN "
        "(o EAN da linha não identifica um tamanho).",
        "CORRIGIDO",
        id_origem=numero,
        original=f"{r['sku']} · {r['tamanho']} · EAN {r['ean']}",
        final=", ".join(n.ChaveSku(chave.categoria, chave.numero, cor, t).canonico for t in tams),
    )
    return [Linha(chave=n.ChaveSku(chave.categoria, chave.numero, cor, t), expandida=True, **{**base, "ean": None}) for t in tams]


# ---------- Peças (produtos) ----------


def _nome_chave(nome: str) -> str:
    return n.sem_acento(nome).lower().strip()


def montar_pecas(ctx: Contexto, linhas: list[Linha]) -> list[Peca]:
    por_modelo: dict[str, list[Linha]] = defaultdict(list)
    for linha in linhas:
        por_modelo[linha.chave.modelo].append(linha)

    pecas = []
    for modelo, doModelo in sorted(por_modelo.items()):
        validas = [linha for linha in doModelo if linha.colecao.valida]
        antigas = [linha for linha in doModelo if not linha.colecao.valida]
        nomes_validos = {_nome_chave(linha.nome) for linha in validas}
        nomes_antigos = {_nome_chave(linha.nome) for linha in antigas}
        if len(nomes_validos) > 1:
            ctx.ocorrencia(
                "NOME_DIVERGE_ENTRE_COLECOES",
                f"{ARQUIVO}:modelo",
                "O mesmo modelo tem nomes diferentes nas coleções: fica o nome da coleção mais nova.",
                "MANTIDO",
                id_origem=modelo,
                original=" · ".join(sorted(nomes_validos)),
            )
        if validas and antigas and not (nomes_validos & nomes_antigos):
            # Código reaproveitado: a peça de 2024 é outra
            atual = Peca(modelo, linhas=validas)
            antiga = Peca(modelo, antiga=True, linhas=antigas)
            ctx.ocorrencia(
                "CODIGO_REAPROVEITADO",
                f"{ARQUIVO}:modelo",
                "Código reaproveitado por outra peça (regra 8 de Compras): a peça de 2024 vira outro produto, inativo, "
                f"com SKU terminado em {SUFIXO_PECA_ANTIGA}; as grafias em comum valem para a peça antiga até a véspera "
                "do lançamento da nova.",
                "CORRIGIDO",
                id_origem=modelo,
                original=f"2024: {antigas[0].nome} · atual: {validas[-1].nome}",
                final=f"{modelo}@2024 e {modelo}",
            )
            pecas += [atual, antiga]
        else:
            pecas.append(Peca(modelo, linhas=doModelo))
    return pecas


def lancamento(peca: Peca) -> date | None:
    datas = [n.data_hora(linha.lancamento) for linha in peca.linhas if linha.lancamento]
    return min(d.momento.date() for d in datas) if datas else None


def _moda(valores: list[Decimal]) -> Decimal:
    contagem = Counter(valores)
    return max(contagem, key=lambda v: (contagem[v], v))


def preco_da_peca(ctx: Contexto, peca: Peca) -> Decimal | None:
    """Preço por coleção = o mais frequente da aba; entre coleções, REGRA_PRECO."""
    por_colecao: dict[Colecao, Decimal] = {}
    fonte = peca.validas or peca.linhas
    for colecao in sorted({linha.colecao for linha in fonte}, key=lambda c: c.ordem):
        precos = []
        for linha in fonte:
            if linha.colecao != colecao:
                continue
            try:
                valor = n.dinheiro(linha.preco)
            except n.ValorInvalido:
                valor = None
            if valor is not None:
                precos.append((linha, valor))
            if linha.revisar_preco:
                ctx.ocorrencia(
                    "PRECO_A_REVISAR",
                    linha.origem,
                    'Linha marcada em amarelo na planilha ("revisar preço").',
                    "PENDENTE",
                    id_origem=linha.id_origem,
                    original=linha.preco,
                )
        if not precos:
            continue
        moda = _moda([v for _, v in precos])
        for linha, valor in precos:
            if valor != moda:
                ctx.ocorrencia(
                    "PRECO_DIVERGE_NA_ABA",
                    linha.origem,
                    f"Preço diferente do resto do modelo na mesma aba ({colecao.nome}): vale o mais frequente.",
                    "CORRIGIDO",
                    id_origem=linha.id_origem,
                    original=linha.preco,
                    final=_moeda(moda),
                    impacto=valor - moda,
                    unidade="REAIS",
                )
        por_colecao[colecao] = moda

    if not por_colecao:
        return None
    mais_nova = max(por_colecao, key=lambda c: c.ordem)
    escolhido = min(por_colecao.values()) if REGRA_PRECO == "MENOR" else por_colecao[mais_nova]
    if len(set(por_colecao.values())) > 1:
        ctx.ocorrencia(
            "PRECO_ENTRE_COLECOES",
            f"{ARQUIVO}:modelo",
            f"Peça em mais de uma coleção com preços diferentes. Regra aplicada: {REGRA_PRECO} "
            "(Operações/Financeiro, por causa do Procon); Compras usaria o da coleção mais nova. "
            "Impacto: diferença por peça entre o preço da coleção mais nova e o aplicado.",
            "CORRIGIDO",
            id_origem=peca.id_origem,
            original=" · ".join(f"{c.nome}: {_moeda(v)}" for c, v in por_colecao.items()),
            final=_moeda(escolhido),
            impacto=por_colecao[mais_nova] - escolhido,
            unidade="REAIS",
        )
    return escolhido


# ---------- Custos das notas de entrada ----------


@dataclass
class Notas:
    """Entradas com nota fiscal e custo, por variação: [(data, quantidade, custo)]."""

    por_variacao: dict[str, list[tuple[date, int, Decimal]]] = field(default_factory=lambda: defaultdict(list))

    def ultimo_custo(self, sku: str) -> Decimal | None:
        notas = self.por_variacao.get(sku)
        return max(notas, key=lambda nota: nota[0])[2] if notas else None

    def custo_medio(self, sku: str) -> Decimal | None:
        notas = self.por_variacao.get(sku)
        quantidade = sum(q for _, q, _ in notas or [])
        if not quantidade:
            return None
        return (sum(q * c for _, q, c in notas) / quantidade).quantize(n.CENTAVO)


# ---------- Carga ----------


@dataclass
class VariacaoPlano:
    peca: Peca
    chave: n.ChaveSku
    linhas: list[Linha]
    sku: str
    ean: str | None = None
    ativa: bool = True
    preco_custo: Decimal | None = None
    custo_medio: Decimal | None = None
    variacao_id: int | None = None


def _sku(peca: Peca, chave: n.ChaveSku) -> str:
    return chave.canonico + (SUFIXO_PECA_ANTIGA if peca.antiga else "")


def planejar_variacoes(ctx: Contexto, pecas: list[Peca]) -> list[VariacaoPlano]:
    planos = []
    for peca in pecas:
        por_chave: dict[n.ChaveSku, list[Linha]] = defaultdict(list)
        for linha in peca.linhas:
            por_chave[linha.chave].append(linha)
        for chave, linhas in sorted(por_chave.items(), key=lambda item: item[0].canonico):
            linhas.sort(key=lambda linha: (linha.colecao.ordem, linha.numero))
            plano = VariacaoPlano(peca, chave, linhas, _sku(peca, chave))
            mais_recente = max(linhas, key=lambda linha: (linha.colecao.valida, linha.colecao.ordem))
            plano.ativa = not peca.antiga and mais_recente.colecao.valida and not mais_recente.descontinuada
            plano.ean = _ean(ctx, linhas)
            plano.preco_custo = _ultimo_custo_da_aba(linhas)
            planos.append(plano)

    # EAN único na plataforma: repetido em variações diferentes fica só na mais recente
    por_ean: dict[str, list[VariacaoPlano]] = defaultdict(list)
    for plano in planos:
        if plano.ean:
            por_ean[plano.ean].append(plano)
    for codigo, donos in por_ean.items():
        if len(donos) > 1:
            donos.sort(key=lambda p: (not p.peca.antiga, max(linha.colecao.ordem for linha in p.linhas)))
            for plano in donos[:-1]:
                ctx.ocorrencia(
                    "EAN_EM_PECAS_DIFERENTES",
                    f"{ARQUIVO}:ean",
                    f"O mesmo EAN aparece em peças diferentes: fica só em {donos[-1].sku} (a mais recente).",
                    "CORRIGIDO",
                    id_origem=plano.sku,
                    original=codigo,
                    final=None,
                )
                plano.ean = None
    return planos


def _ean(ctx: Contexto, linhas: list[Linha]) -> str | None:
    validos = []
    for linha in linhas:
        if linha.ean is None:
            continue
        try:
            validos.append((linha, n.ean(linha.ean)))
        except n.ValorInvalido as erro:
            ctx.ocorrencia(
                "EAN_INVALIDO",
                linha.origem,
                f"EAN não usado: {erro}",
                "DESCARTADO",
                id_origem=linha.id_origem,
                original=linha.ean,
            )
    distintos = {codigo for _, codigo in validos}
    if len(distintos) > 1:
        ctx.ocorrencia(
            "EAN_DIVERGE_ENTRE_COLECOES",
            f"{ARQUIVO}:ean",
            "A mesma peça tem EANs diferentes nas coleções: fica o da coleção mais nova.",
            "MANTIDO",
            id_origem=validos[-1][0].chave.canonico,
            original=" · ".join(sorted(distintos)),
            final=validos[-1][1],
        )
    return validos[-1][1] if validos else None


def _ultimo_custo_da_aba(linhas: list[Linha]) -> Decimal | None:
    for linha in sorted(linhas, key=lambda linha: (linha.colecao.valida, linha.colecao.ordem), reverse=True):
        try:
            custo = n.dinheiro(linha.custo)
        except n.ValorInvalido:
            custo = None
        if custo is not None:
            return custo
    return None


def _garantir_categorias(db: Session) -> dict[str, m.Categoria]:
    categorias = {c.nome: c for c in db.scalars(select(m.Categoria))}
    for nome in {*n.CATEGORIA_POR_PREFIXO.values(), *n.CATEGORIAS_NOVAS}:
        if nome not in categorias:
            categorias[nome] = m.Categoria(nome=nome)
            db.add(categorias[nome])
    db.flush()
    return categorias


def _produto(db: Session, id_origem: str) -> m.Produto | None:
    produto_id = migracao_repository.destino(db, f"{ARQUIVO}:modelo", id_origem, "produtos")
    return db.get(m.Produto, produto_id) if produto_id else None


def migrar(db: Session) -> Resultado:
    ctx = Contexto(db, Resultado(DOMINIO))
    migracao_repository.limpar_ocorrencias(db, DOMINIO)
    categorias = _garantir_categorias(db)

    linhas = ler_catalogo(ctx)
    pecas = montar_pecas(ctx, linhas)
    planos = planejar_variacoes(ctx, pecas)

    # Grafias de SKU de todas as origens (para os aliases e para achar o que foi vendido sem cadastro)
    grafias = _grafias(db, linhas)
    por_chave = defaultdict(list)
    for plano in planos:
        por_chave[plano.chave].append(plano)
    lancamentos = {p.modelo: lancamento(p) for p in pecas if not p.antiga}

    # Variação vendida/movimentada que não está no catálogo, de um modelo que está: entra inativa
    modelos = {p.modelo: p for p in pecas if not p.antiga}
    for grafia, origem in grafias.items():
        chave = _chave_ou_none(grafia)
        if chave is None or not chave.cor or not chave.tamanho or chave in por_chave or chave.modelo not in modelos:
            continue
        peca = modelos[chave.modelo]
        plano = VariacaoPlano(peca, chave, [], _sku(peca, chave), ativa=False)
        planos.append(plano)
        por_chave[chave].append(plano)
        ctx.ocorrencia(
            "VARIACAO_FORA_DO_CATALOGO",
            origem,
            "Cor/tamanho que aparece nas vendas ou no estoque, mas não no "
            "catálogo, de um modelo que está nele: entra como variação inativa, sem EAN e sem custo.",
            "CORRIGIDO",
            id_origem=grafia,
            original=grafia,
            final=plano.sku,
        )

    notas = _notas(db, grafias, por_chave, lancamentos)
    produtos_criados, variacoes_por_sku = _gravar(ctx, categorias, pecas, planos, notas)

    nao_catalogado = _gravar_nao_catalogado(ctx, categorias, grafias)
    aliases = _gravar_aliases(ctx, grafias, por_chave, lancamentos, variacoes_por_sku, nao_catalogado)

    ctx.resultado.carregados = len(variacoes_por_sku) + (1 if nao_catalogado else 0)
    ctx.resultado.corrigidos = len(ctx.corrigidas)
    ctx.resultado.ocorrencias = migracao_repository.ocorrencias_por_acao(db, DOMINIO)
    ativos = sum(1 for p in variacoes_por_sku.values() if p.ativa)
    ctx.resultado.notas = [
        f"produtos: {produtos_criados} ({sum(1 for p in pecas if p.antiga)} peças de 2024 de códigos reaproveitados)",
        f"variações: {len(variacoes_por_sku)} ({ativos} ativas, {len(variacoes_por_sku) - ativos} descontinuadas ou só de 2024)",
        f"grafias de SKU em sku_alias: {aliases}",
        f"regra de preço entre coleções: {REGRA_PRECO}",
    ]
    return ctx.resultado


def _chave_ou_none(grafia: str) -> n.ChaveSku | None:
    try:
        return n.interpretar_sku(grafia)
    except n.ValorInvalido:
        return None


def _grafias(db: Session, linhas: list[Linha]) -> dict[str, str]:
    """Grafia normalizada → primeira origem em que aparece (catálogo primeiro)."""
    grafias: dict[str, str] = {}
    for linha in linhas:
        grafias.setdefault(n.alias_normalizado(linha.sku), linha.origem)
    consultas = (
        ("vulto.db:itens_venda", "SELECT DISTINCT sku FROM legado_vulto.db__itens_venda"),
        ("vulto.db:entradas_estoque", "SELECT DISTINCT sku FROM legado_vulto.db__entradas_estoque"),
        ("vulto.db:estoque", "SELECT DISTINCT sku FROM legado_vulto.db__estoque"),
        ("contagem.xlsx:PINHEIROS 20-09", "SELECT DISTINCT sku FROM legado_vulto.contagem__pinheiros_20_09"),
        ("contagem.xlsx:Eldorado", "SELECT DISTINCT codigo FROM legado_vulto.contagem__eldorado"),
        ("contagem.xlsx:batel", "SELECT DISTINCT sku FROM legado_vulto.contagem__batel"),
        ("contagem.xlsx:CD - posicao WMS 28-09", "SELECT DISTINCT sku FROM legado_vulto.contagem__cd_posicao_wms_28_09"),
    )
    for origem, sql in consultas:
        for (valor,) in db.execute(text(sql)):
            if valor and valor.strip():
                grafias.setdefault(n.alias_normalizado(valor), origem)
    return grafias


def _vigencia(
    chave: n.ChaveSku, plano: VariacaoPlano, donos: list[VariacaoPlano], lancamentos
) -> tuple[date | None, date | None]:
    """Grafia que existe na peça antiga e na nova de um código reaproveitado: a antiga vale até a véspera
    do lançamento da nova; a nova, a partir dele."""
    if len(donos) < 2:
        return None, None
    inicio = lancamentos.get(chave.modelo)
    if inicio is None:
        return None, None
    return (None, inicio - timedelta(days=1)) if plano.peca.antiga else (inicio, None)


def _notas(db: Session, grafias, por_chave, lancamentos) -> Notas:
    notas = Notas()
    # Só as entradas com nota fiscal têm custo (as transferências do CD vêm sem)
    consulta = text(
        "SELECT sku, qtd, custo_unit, data FROM legado_vulto.db__entradas_estoque "
        "WHERE coalesce(nf, '') <> '' AND custo_unit IS NOT NULL"
    )
    for grafia, qtd, custo, quando in db.execute(consulta):
        chave = _chave_ou_none(grafia)
        donos = por_chave.get(chave, []) if chave else []
        dia = n.data_hora(quando).momento.date()
        for plano in donos:
            de, ate = _vigencia(chave, plano, donos, lancamentos)
            if (de is None or dia >= de) and (ate is None or dia <= ate):
                notas.por_variacao[plano.sku].append((dia, int(qtd), n.dinheiro(custo)))
    return notas


def _gravar(ctx: Contexto, categorias, pecas: list[Peca], planos: list[VariacaoPlano], notas: Notas):
    db = ctx.db
    # EANs das variações da Vulto saem antes de serem redistribuídos (o EAN é único)
    db.execute(
        m.Variacao.__table__.update()
        .where(m.Variacao.produto_id.in_(select(m.Produto.id).where(m.Produto.marca == VULTO)))
        .values(ean=None)
    )
    planos_por_peca: dict[int, list[VariacaoPlano]] = defaultdict(list)
    for plano in planos:
        planos_por_peca[id(plano.peca)].append(plano)

    variacoes_por_sku: dict[str, VariacaoPlano] = {}
    criados = 0
    for peca in pecas:
        doPeca = planos_por_peca[id(peca)]
        recente = max(peca.linhas, key=lambda linha: (linha.colecao.valida, linha.colecao.ordem, linha.numero))
        categoria = n.categoria_do_sku(recente.chave)
        _conferir_categoria(ctx, peca, categoria)
        preco = preco_da_peca(ctx, peca)
        if preco is None:
            ctx.ocorrencia(
                "SEM_PRECO",
                f"{ARQUIVO}:modelo",
                "Peça sem nenhum preço legível no catálogo: entra com preço zero e inativa até Compras definir.",
                "PENDENTE",
                id_origem=peca.id_origem,
            )
            preco = Decimal("0.00")
            sem_preco = True
        else:
            sem_preco = False
        if not peca.validas:
            ctx.ocorrencia(
                "SO_NA_PLANILHA_ANTIGA",
                f"{ARQUIVO}:modelo",
                "Peça que só está na planilha antiga (2024) mas ainda tem vendas: entra inativa, com o preço de 2024.",
                "MANTIDO",
                id_origem=peca.id_origem,
                final=_moeda(preco),
            )

        produto = _produto(db, peca.id_origem)
        if produto is None:
            produto = m.Produto(marca=VULTO)
            db.add(produto)
            criados += 1
        produto.nome = recente.nome if not peca.antiga else f"{recente.nome} (2024)"
        produto.categoria = categorias[categoria]
        produto.preco_base = preco
        produto.marca = VULTO
        produto.colecao = recente.colecao.nome
        produto.estacao = recente.colecao.estacao
        produto.genero = None
        db.flush()
        migracao_repository.vincular(db, f"{ARQUIVO}:modelo", peca.id_origem, "produtos", produto.id)

        for plano in doPeca:
            plano.custo_medio = notas.custo_medio(plano.sku)
            if plano.preco_custo is None:
                plano.preco_custo = notas.ultimo_custo(plano.sku)
                if plano.preco_custo is not None and plano.linhas:
                    ctx.ocorrencia(
                        "CUSTO_DA_NOTA",
                        f"{ARQUIVO}:custo",
                        "Sem custo na planilha: vale o da última nota de entrada.",
                        "CORRIGIDO",
                        id_origem=plano.sku,
                        final=_moeda(plano.preco_custo),
                    )
            variacao = db.scalar(select(m.Variacao).where(m.Variacao.sku == plano.sku))
            if variacao is None:
                variacao = m.Variacao(sku=plano.sku)
                db.add(variacao)
            variacao.produto = produto
            variacao.cor = n.CORES[plano.chave.cor]
            variacao.tamanho = plano.chave.tamanho
            variacao.ean = plano.ean
            variacao.ativa = plano.ativa
            variacao.preco_custo = plano.preco_custo
            variacao.custo_medio = plano.custo_medio
            db.flush()
            for linha in plano.linhas:
                migracao_repository.vincular(db, linha.origem, linha.id_origem, "variacoes", variacao.id)
            variacoes_por_sku[plano.sku] = plano
            plano.variacao_id = variacao.id
        produto.ativo = any(p.ativa for p in doPeca) and not sem_preco
    db.flush()
    return criados, variacoes_por_sku


def _conferir_categoria(ctx: Contexto, peca: Peca, categoria: str) -> None:
    textos = {}
    for linha in peca.linhas:
        try:
            pelo_texto = n.categoria(linha.categoria)
        except n.ValorInvalido:
            pelo_texto = None
        if pelo_texto and pelo_texto != categoria:
            textos[linha.categoria] = pelo_texto
    if textos:
        ctx.ocorrencia(
            "CATEGORIA_DIVERGE_DO_SKU",
            f"{ARQUIVO}:categoria",
            f"O texto da categoria indica outra categoria: vale o prefixo do SKU ({categoria}).",
            "MANTIDO",
            id_origem=peca.id_origem,
            original=" · ".join(sorted(textos)),
            final=categoria,
        )


def _gravar_nao_catalogado(ctx: Contexto, categorias, grafias: dict[str, str]) -> m.Variacao | None:
    """DIVERSO e PRODUTO SEM CADASTRO: um produto inativo na categoria Não catalogado, com o preço mais
    frequente dessas vendas."""
    db = ctx.db
    vendidas = [g for g in grafias if g in GRAFIAS_NAO_CATALOGADO]
    if not vendidas:
        return None
    precos = []
    consulta = text("SELECT preco_unit FROM legado_vulto.db__itens_venda WHERE upper(trim(sku)) = ANY(:skus)")
    for (preco,) in db.execute(consulta, {"skus": vendidas}):
        try:
            if (valor := n.dinheiro(preco)) is not None:
                precos.append(abs(valor))
        except n.ValorInvalido:
            pass
    produto = _produto(db, "NAO_CATALOGADO")
    if produto is None:
        produto = m.Produto(marca=VULTO)
        db.add(produto)
    produto.nome = "Item sem cadastro (Vulto)"
    produto.categoria = categorias[n.CATEGORIA_NAO_CATALOGADO]
    produto.preco_base = _moda(precos) if precos else Decimal("0.00")
    produto.marca, produto.ativo, produto.colecao = VULTO, False, None
    db.flush()
    migracao_repository.vincular(db, f"{ARQUIVO}:modelo", "NAO_CATALOGADO", "produtos", produto.id)
    variacao = db.scalar(select(m.Variacao).where(m.Variacao.sku == SKU_NAO_CATALOGADO))
    if variacao is None:
        variacao = m.Variacao(sku=SKU_NAO_CATALOGADO)
        db.add(variacao)
    variacao.produto, variacao.cor, variacao.tamanho, variacao.ativa = produto, "NÃO INFORMADA", "U", False
    db.flush()
    for grafia in vendidas:
        ctx.ocorrencia(
            "VENDIDO_SEM_CADASTRO",
            "vulto.db:itens_venda.sku",
            'Item vendido sem produto no catálogo: entra no produto "Item sem cadastro (Vulto)", categoria Não catalogado.',
            "CORRIGIDO",
            id_origem=grafia,
            original=grafia,
            final=SKU_NAO_CATALOGADO,
        )
    return variacao


def _gravar_aliases(ctx: Contexto, grafias, por_chave, lancamentos, variacoes_por_sku, nao_catalogado) -> int:
    db = ctx.db
    vulto = select(m.Variacao.id).join(m.Variacao.produto).where(m.Produto.marca == VULTO)
    db.execute(delete(m.SkuAlias).where(m.SkuAlias.variacao_id.in_(vulto)))
    ids = {sku: plano.variacao_id for sku, plano in variacoes_por_sku.items()}

    def criar(grafia, variacao_id, origem, de=None, ate=None):
        db.add(
            m.SkuAlias(
                variacao_id=variacao_id,
                alias=grafia,
                alias_normalizado=n.alias_normalizado(grafia),
                origem=origem,
                valido_de=de,
                valido_ate=ate,
            )
        )

    # O próprio SKU canônico também é uma grafia (a busca é sempre pelo alias, que tem a vigência)
    todas = dict(grafias)
    for sku in variacoes_por_sku:
        todas.setdefault(sku, "sku canônico")
    total = 0
    for grafia, origem in sorted(todas.items()):
        if nao_catalogado is not None and grafia in GRAFIAS_NAO_CATALOGADO:
            criar(grafia, nao_catalogado.id, origem)
            total += 1
            continue
        if grafia.endswith(SUFIXO_PECA_ANTIGA) and grafia in ids:
            criar(grafia, ids[grafia], origem)
            total += 1
            continue
        chave = _chave_ou_none(grafia)
        if chave is None or not chave.tamanho:
            if chave is None:
                ctx.ocorrencia(
                    "GRAFIA_DE_SKU_ILEGIVEL",
                    origem,
                    "Grafia de SKU que não dá para interpretar (erro de digitação ou código de teste): não vira alias.",
                    "PENDENTE",
                    id_origem=grafia,
                    original=grafia,
                )
            continue
        donos = por_chave.get(chave, [])
        if not donos:
            ctx.ocorrencia(
                "GRAFIA_SEM_PRODUTO",
                origem,
                "Grafia de um modelo que não está no catálogo: não vira alias.",
                "PENDENTE",
                id_origem=grafia,
                original=grafia,
            )
            continue
        if len(donos) > 1 and lancamentos.get(chave.modelo) is None:
            ctx.ocorrencia(
                "REAPROVEITADO_SEM_LANCAMENTO",
                origem,
                "Código reaproveitado sem data de lançamento da peça nova: a grafia aponta só para a peça atual.",
                "PENDENTE",
                id_origem=grafia,
                original=grafia,
            )
            donos = [plano for plano in donos if not plano.peca.antiga]
        for plano in donos:
            de, ate = _vigencia(chave, plano, donos, lancamentos)
            criar(grafia, ids[plano.sku], origem, de, ate)
            total += 1
    db.flush()
    return total
