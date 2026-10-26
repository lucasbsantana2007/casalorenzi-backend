"""Busca de peças e disponibilidade para o assistente do site, sobre o catálogo e o estoque reais.

Reaproveita as regras da vitrine: só produtos ativos e não removidos (produtos.listar), só SKUs vendáveis,
e o disponível de cada peça é o mesmo da página do produto (pedidos.disponiveis_na_rede: saldo + a caminho −
reservas). Numa loja específica, o que está na prateleira e livre: min(saldo físico, saldo livre).
O cliente vê a situação (disponível, últimas unidades, indisponível), não a quantidade exata.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m
from src.entities.busca import (
    PALAVRAS_VAZIAS,
    TAMANHOS_LETRA,
    PedidoBusca,
    e_do_tipo,
    familia_da_cor,
    nota_da_cor,
    tamanho_do_catalogo,
    termos_no_texto,
)
from src.entities.produto import STATUS_VENDAVEIS
from src.repositories import cadastro_repository, estoque_repository, produto_repository
from src.schemas.produtos import imagem_url
from src.use_cases import produtos as produtos_uc
from src.utils.texto import chave_texto, moeda, normalizar

ULTIMAS_UNIDADES = 2

DISPONIVEL = "DISPONIVEL"
ULTIMAS = "ULTIMAS_UNIDADES"
ESGOTADO = "ESGOTADO"
ROTULO_SITUACAO = {DISPONIVEL: "Disponível", ULTIMAS: "Últimas unidades", ESGOTADO: "Indisponível"}


def situacao(quantidade: int) -> str:
    if quantidade <= 0:
        return ESGOTADO
    return ULTIMAS if quantidade <= ULTIMAS_UNIDADES else DISPONIVEL


def ordem_tamanho(tamanho: str) -> tuple:
    t = tamanho_do_catalogo(tamanho)
    if t in TAMANHOS_LETRA:
        return (0, TAMANHOS_LETRA.index(t), "")
    if t.isdigit():
        return (1, int(t), "")
    return (2, 0, t)


def caminho_do_produto(produto: m.Produto) -> str:
    """O mesmo endereço da vitrine: a peça da Vulto abre em /vulto/produto/:id."""
    return f"/vulto/produto/{produto.id}" if produto.marca == "VULTO" else f"/produto/{produto.id}"


def nome_da_marca(marca: str | None) -> str:
    return "Vulto" if marca == "VULTO" else "Casa Lorenzi"


@dataclass
class Achado:
    produto: m.Produto
    variacoes: list[m.Variacao]
    disponivel: dict[int, int]
    nota: tuple = ()

    @property
    def total(self) -> int:
        return sum(self.disponivel.get(v.id, 0) for v in self.variacoes)

    @property
    def preco(self) -> Decimal:
        return min(v.preco_vigente for v in self.variacoes)


@dataclass
class ResultadoBusca:
    pedido: PedidoBusca
    achados: list[Achado] = field(default_factory=list)
    total: int = 0
    # O que precisou mudar para achar alguma peça (a resposta conta isso ao cliente)
    afrouxado: list[str] = field(default_factory=list)
    # Peças que batem com o pedido, mas estão esgotadas
    esgotados: list[str] = field(default_factory=list)
    # Palavras que não existem no catálogo (ex.: "terno")
    desconhecidos: list[str] = field(default_factory=list)


def _texto_da_peca(produto: m.Produto) -> list[str]:
    return [
        produto.nome,
        produto.categoria.nome,
        produto.colecao,
        produto.descricao,
        produto.composicao,
        " ".join({v.cor for v in produto.variacoes}),
    ]


def _livres_na_loja(db: Session, loja_id: int, variacao_ids: list[int]) -> dict[int, int]:
    """O que pode ser vendido na loja agora: saldo físico sem o que já está prometido."""
    if not variacao_ids:
        return {}
    livres = estoque_repository.livres_por_loja(db, variacao_ids)
    fisico = dict(
        db.execute(
            select(m.Estoque.variacao_id, m.Estoque.quantidade).where(
                m.Estoque.loja_id == loja_id, m.Estoque.variacao_id.in_(variacao_ids)
            )
        ).all()
    )
    return {vid: max(min(fisico.get(vid, 0), livres.get((loja_id, vid), 0)), 0) for vid in variacao_ids}


def buscar(
    db: Session,
    pedido: PedidoBusca,
    *,
    loja_id: int | None = None,
    marca_preferida: str | None = None,
    limite: int = 6,
) -> ResultadoBusca:
    """Peças do catálogo que atendem o pedido e estão disponíveis (na rede, ou na loja informada).
    Sem nada exato, afrouxa um filtro por vez, nesta ordem: cor parecida, tamanho, palavras livres, cor e,
    por último, o preço. Cada afrouxamento fica em ResultadoBusca.afrouxado."""
    resultado = ResultadoBusca(pedido=pedido)
    produtos = [p for p in produtos_uc.listar(db, ativo=True) if not pedido.marca or p.marca == pedido.marca]
    if pedido.genero:
        produtos = [p for p in produtos if p.genero in (None, pedido.genero)]
    if not produtos:
        return resultado

    # Palavra que não aparece em nenhuma peça não filtra nada: é avisada e sai da busca
    textos = {p.id: normalizar(" ".join(t or "" for t in _texto_da_peca(p))) for p in produtos}
    conhecidos = [t for t in pedido.termos if any(t in texto for texto in textos.values())]
    resultado.desconhecidos = [t for t in pedido.termos if t not in conhecidos]
    termos = conhecidos
    if not (pedido.tipos or pedido.cor or pedido.tamanho or pedido.preco_min or pedido.preco_max or termos):
        return resultado

    ids = [v.id for p in produtos for v in p.variacoes]
    disponivel = _livres_na_loja(db, loja_id, ids) if loja_id else produtos_uc.disponiveis_para_venda(db, produtos)

    def preco_ok(valor: Decimal) -> bool:
        return (pedido.preco_min is None or valor >= pedido.preco_min) and (pedido.preco_max is None or valor <= pedido.preco_max)

    def avaliar(produto, *, cor_minima: int, com_tamanho: bool, com_termos: bool, com_cor: bool, com_preco: bool):
        if not e_do_tipo(produto.nome, produto.categoria.nome, pedido.tipos):
            return None, False
        acertos = termos_no_texto(termos, *_texto_da_peca(produto)) if com_termos else 0
        if com_termos and termos and acertos == 0:
            return None, False
        variacoes = [v for v in produto.variacoes if v.status in STATUS_VENDAVEIS]
        if com_cor and pedido.cor:
            variacoes = [v for v in variacoes if nota_da_cor(v.cor, pedido.cor) >= cor_minima]
        if com_tamanho and pedido.tamanho:
            variacoes = [v for v in variacoes if tamanho_do_catalogo(v.tamanho) == pedido.tamanho]
        if com_preco:
            variacoes = [v for v in variacoes if preco_ok(v.preco_vigente)]
        if not variacoes:
            return None, False
        livres = [v for v in variacoes if disponivel.get(v.id, 0) > 0]
        if not livres:
            return None, True  # bate com o pedido, mas está esgotada
        cor_exata = any(nota_da_cor(v.cor, pedido.cor) == 2 for v in livres)
        nota = (acertos, cor_exata, produto.marca == marca_preferida, sum(disponivel.get(v.id, 0) for v in livres))
        return Achado(produto, livres, disponivel, nota), False

    tentativas = [("exato", dict(cor_minima=2, com_tamanho=True, com_termos=True, com_cor=True, com_preco=True))]
    if pedido.cor:
        tentativas.append(("cor parecida", dict(cor_minima=1, com_tamanho=True, com_termos=True, com_cor=True, com_preco=True)))
    if pedido.tamanho:
        tentativas.append(
            (
                f"outros tamanhos (sem o {pedido.tamanho} disponível)",
                dict(cor_minima=1, com_tamanho=False, com_termos=True, com_cor=True, com_preco=True),
            )
        )
    if termos:
        tentativas.append(
            (f"sem '{' '.join(termos)}'", dict(cor_minima=1, com_tamanho=False, com_termos=False, com_cor=True, com_preco=True))
        )
    if pedido.cor:
        tentativas.append(
            ("outras cores", dict(cor_minima=0, com_tamanho=False, com_termos=False, com_cor=False, com_preco=True))
        )
    if pedido.preco_min is not None or pedido.preco_max is not None:
        tentativas.append(
            ("fora da faixa de preço", dict(cor_minima=1, com_tamanho=False, com_termos=True, com_cor=True, com_preco=False))
        )

    for rotulo, regras in tentativas:
        achados, esgotados = [], []
        for produto in produtos:
            achado, esgotado = avaliar(produto, **regras)
            if achado:
                achados.append(achado)
            elif esgotado:
                esgotados.append(produto.nome)
        if rotulo == "exato":
            resultado.esgotados = sorted(esgotados, key=chave_texto)[:3]
        if achados and termos and regras["com_termos"]:
            # "camisa de linho toscana": fica a peça que tem todas as palavras, não as que têm só "linho"
            maior = max(a.nota[0] for a in achados)
            achados = [a for a in achados if a.nota[0] == maior]
        if achados:
            # Mais palavras livres achadas, cor exata, marca da vitrine aberta, mais peças disponíveis
            achados.sort(key=lambda a: (-a.nota[0], not a.nota[1], not a.nota[2], -a.nota[3], chave_texto(a.produto.nome)))
            resultado.achados = achados[:limite]
            resultado.total = len(achados)
            if rotulo != "exato":
                resultado.afrouxado.append(rotulo)
            break
    return resultado


def card(achado: Achado) -> dict:
    """Card da peça para a tela e o resumo dela para o modelo (sem quantidade exata)."""
    produto = achado.produto
    variacoes = sorted(achado.variacoes, key=lambda v: (v.cor, ordem_tamanho(v.tamanho)))
    cores = list(dict.fromkeys(v.cor for v in variacoes))
    tamanhos = sorted({v.tamanho for v in variacoes}, key=ordem_tamanho)
    return {
        "produtoId": produto.id,
        "nome": produto.nome,
        "marca": produto.marca,
        "categoria": produto.categoria.nome,
        "preco": float(achado.preco),
        "precoFormatado": moeda(achado.preco),
        "cores": cores,
        "tamanhos": tamanhos,
        "situacao": situacao(achado.total),
        "imagemUrl": imagem_url(produto),
        "codigoModelo": produto.codigo_modelo,
        "link": caminho_do_produto(produto),
    }


def produto_ativo(db: Session, produto_id: int) -> m.Produto | None:
    produto = produto_repository.obter(db, produto_id)
    if produto is None or produto.removido_em is not None or not produto.ativo:
        return None
    return produto


def variacoes_escolhidas(produto: m.Produto, cor: str | None, tamanho: str | None) -> list[m.Variacao]:
    """SKUs vendáveis do produto na cor (nome exato ou família) e no tamanho pedidos."""
    variacoes = [v for v in produto.variacoes if v.status in STATUS_VENDAVEIS]
    if cor:
        exatas = [v for v in variacoes if normalizar(v.cor) == normalizar(cor)]
        familia = familia_da_cor(cor)
        variacoes = exatas or [v for v in variacoes if familia and nota_da_cor(v.cor, familia) == 2]
    if tamanho:
        alvo = tamanho_do_catalogo(tamanho)
        variacoes = [v for v in variacoes if tamanho_do_catalogo(v.tamanho) == alvo]
    return variacoes


def disponibilidade(db: Session, produto: m.Produto, variacoes: list[m.Variacao]) -> dict:
    """Situação da peça (nas cores e tamanhos escolhidos) no site e em cada loja física da marca."""
    ids = [v.id for v in variacoes]
    rede = produtos_uc.disponiveis_para_venda(db, [produto]) if ids else {}
    lojas = [loja for loja in cadastro_repository.lojas(db, somente_ativas=True, marca=produto.marca, tipo="LOJA")]
    por_loja = []
    for loja in lojas:
        livres = _livres_na_loja(db, loja.id, ids)
        tamanhos = sorted({v.tamanho for v in variacoes if livres.get(v.id, 0) > 0}, key=ordem_tamanho)
        quantidade = sum(livres.values())
        por_loja.append(
            {
                "lojaId": loja.id,
                "loja": loja.nome,
                "cidade": loja.cidade,
                "uf": loja.uf,
                "situacao": situacao(quantidade),
                "tamanhos": tamanhos,
            }
        )
    no_site = sum(rede.get(i, 0) for i in ids)
    return {
        "site": situacao(no_site),
        "tamanhosNoSite": sorted({v.tamanho for v in variacoes if rede.get(v.id, 0) > 0}, key=ordem_tamanho),
        "lojas": por_loja,
    }


# ---------- Lojas ----------

_ABREVIACOES = {
    "bh": "belo horizonte",
    "sampa": "sao paulo",
    "sp": "sao paulo",
    "rio": "rio de janeiro",
    "rj": "rio de janeiro",
    "bsb": "brasilia",
    "cwb": "curitiba",
}
_PALAVRAS_GENERICAS = PALAVRAS_VAZIAS | {
    "loja",
    "lojas",
    "unidade",
    "unidades",
    "fisica",
    "fisicas",
    "perto",
    "proxima",
    "endereco",
    "horario",
    "horarios",
    "funciona",
    "abre",
    "fecha",
    "telefone",
    "fica",
    "onde",
    "vulto",
    "lorenzi",
    "rua",
    "avenida",
    "av",
    "piso",
    "terreo",
    "andar",
    "centro",
}


def _indice_da_loja(loja: m.Loja) -> tuple[set[str], set[str]]:
    """(palavras do nome, palavras do endereço e da cidade) da loja, normalizadas."""
    nome = set(re.findall(r"[a-z]{3,}", normalizar(loja.nome))) - _PALAVRAS_GENERICAS
    # Do endereço, só palavras com 4 letras ou mais ("r", "st", "ca" apareceriam em qualquer frase)
    resto = set(re.findall(r"[a-z]{4,}", normalizar(f"{loja.endereco} {loja.cidade}"))) - _PALAVRAS_GENERICAS
    # "shopping" está no nome de uma loja e no endereço de outras: vale o mesmo nos dois
    if "shopping" in nome:
        nome.discard("shopping")
        resto.add("shopping")
    return nome, resto


def encontrar_lojas(db: Session, texto: str, *, marca: str | None = None) -> list[m.Loja]:
    """Lojas físicas ativas citadas no texto ('loja do shopping', 'Pinheiros', 'em BH'). Empate: todas."""
    normalizado = normalizar(texto)
    for curta, longa in _ABREVIACOES.items():
        normalizado = re.sub(rf"\b{curta}\b", longa, normalizado)
    palavras = set(re.findall(r"[a-z]{3,}", normalizado)) - _PALAVRAS_GENERICAS
    if not palavras:
        return []
    melhores, maior = [], 0
    for loja in cadastro_repository.lojas(db, somente_ativas=True, marca=marca, tipo="LOJA"):
        nome, resto = _indice_da_loja(loja)
        nota = 3 * len(palavras & nome) + len(palavras & resto)
        if nota > maior:
            melhores, maior = [loja], nota
        elif nota == maior and nota > 0:
            melhores.append(loja)
    return melhores
