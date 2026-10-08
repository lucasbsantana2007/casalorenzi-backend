from pydantic import Field

from src import models as m
from src.schemas.comum import AnexoEntrada, Entrada
from src.utils.urls import url_da_api


class VariacaoEntrada(Entrada):
    id: int | None = None
    sku: str
    tamanho: str = ""
    cor: str = ""
    # Quanto a peça custa para a loja (obrigatório no cadastro; só o Administrador vê)
    preco_custo: float | None = None


class ProdutoEntrada(Entrada):
    nome: str = ""
    categoria: str = ""
    preco_base: float = 0
    ativo: bool = True
    # Coleção da vitrine (Masculino ou Feminino), obrigatória no cadastro; estação: Inverno, Verão
    # ou Atemporal (padrão). Na edição, só mudam se forem enviadas
    genero: str | None = None
    estacao: str | None = None
    # Textos da página do produto: na edição, só mudam se forem enviados
    descricao: str | None = None
    composicao: str | None = None
    cuidados: str | None = None
    variacoes: list[VariacaoEntrada] = Field(default_factory=list)
    # Foto: { nome, tipo, conteudoBase64 } troca a foto; removerImagem volta à ilustração do site
    imagem: AnexoEntrada | None = None
    remover_imagem: bool = False


def imagem_url(produto: m.Produto) -> str | None:
    """Link da foto enviada no cadastro; ?v= muda a cada troca para o navegador não usar a antiga."""
    if produto.imagem is None:
        return None
    return url_da_api(f"/produtos/{produto.id}/imagem?v={int(produto.imagem.atualizado_em.timestamp())}")


def produto_resumo(produto: m.Produto) -> dict:
    return {
        "id": produto.id,
        "nome": produto.nome,
        "categoria": produto.categoria.nome,
        "precoBase": float(produto.preco_base),
        "ativo": produto.ativo,
        "imagemUrl": imagem_url(produto),
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


def produto_saida(
    produto: m.Produto, totais: dict[int, int], com_custo: bool = False, disponiveis: dict[int, int] | None = None
) -> dict:
    """totais: estoque físico somado de todas as lojas por variação (a vitrine não vê o estoque por loja).
    disponiveis: o que ainda pode ser vendido (desconta pedidos não enviados); a vitrine usa este.
    com_custo: só para o Administrador (preço de custo de cada variação)."""
    variacoes = [
        {
            **variacao_base(v),
            "estoqueTotal": totais.get(v.id, 0),
            "disponivel": (disponiveis if disponiveis is not None else totais).get(v.id, 0),
            **({"precoCusto": float(v.preco_custo) if v.preco_custo is not None else None} if com_custo else {}),
        }
        for v in produto.variacoes
    ]
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
        "imagemUrl": imagem_url(produto),
        "variacoes": variacoes,
        "estoqueTotal": sum(v["estoqueTotal"] for v in variacoes),
        "disponivel": sum(v["disponivel"] for v in variacoes),
    }
