from pydantic import Field

from src import models as m
from src.schemas.comum import Entrada


class VariacaoEntrada(Entrada):
    id: int | None = None
    sku: str
    tamanho: str = ""
    cor: str = ""


class ProdutoEntrada(Entrada):
    nome: str = ""
    categoria: str = ""
    preco_base: float = 0
    ativo: bool = True
    genero: str | None = None
    estacao: str | None = None
    # Textos da página do produto: na edição, só mudam se forem enviados
    descricao: str | None = None
    composicao: str | None = None
    cuidados: str | None = None
    variacoes: list[VariacaoEntrada] = Field(default_factory=list)


def produto_resumo(produto: m.Produto) -> dict:
    return {
        "id": produto.id,
        "nome": produto.nome,
        "categoria": produto.categoria.nome,
        "precoBase": float(produto.preco_base),
        "ativo": produto.ativo,
    }


def variacao_base(variacao: m.Variacao) -> dict:
    return {
        "id": variacao.id,
        "produtoId": variacao.produto_id,
        "sku": variacao.sku,
        "tamanho": variacao.tamanho,
        "cor": variacao.cor,
    }


def variacao_saida(variacao: m.Variacao) -> dict:
    """Variação com o resumo do produto embutido."""
    return {**variacao_base(variacao), "produto": produto_resumo(variacao.produto)}


def produto_saida(produto: m.Produto, totais: dict[int, int]) -> dict:
    """totais: estoque somado de todas as lojas por variação (a vitrine não vê o estoque por loja)."""
    variacoes = [{**variacao_base(v), "estoqueTotal": totais.get(v.id, 0)} for v in produto.variacoes]
    return {
        "id": produto.id,
        "nome": produto.nome,
        "categoria": produto.categoria.nome,
        "precoBase": float(produto.preco_base),
        "genero": produto.genero,
        "estacao": produto.estacao,
        "descricao": produto.descricao,
        "composicao": produto.composicao,
        "cuidados": produto.cuidados,
        "ativo": produto.ativo,
        "variacoes": variacoes,
        "estoqueTotal": sum(v["estoqueTotal"] for v in variacoes),
    }
