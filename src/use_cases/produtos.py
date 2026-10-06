from sqlalchemy.orm import Session

from src import models as m
from src.repositories import cadastro_repository, estoque_repository, produto_repository, sessao
from src.schemas.produtos import ProdutoEntrada
from src.use_cases.estoque import criar_estoques_zerados
from src.utils.erros import DadosInvalidos, NaoEncontrado
from src.utils.texto import chave_texto, corresponde


def listar(db: Session, busca: str | None = None, categoria: str | None = None, ativo: bool | None = None) -> list[m.Produto]:
    produtos = [
        p
        for p in produto_repository.listar(db, categoria=categoria, ativo=ativo)
        if corresponde(busca, p.nome, p.categoria.nome, *(v.sku for v in p.variacoes))
    ]
    produtos.sort(key=lambda p: chave_texto(p.nome))
    return produtos


def obter(db: Session, produto_id: int) -> m.Produto:
    produto = produto_repository.obter(db, produto_id)
    if produto is None:
        raise NaoEncontrado("Produto não encontrado.")
    return produto


def totais_de_estoque(db: Session, produtos: list[m.Produto]) -> dict[int, int]:
    return estoque_repository.totais_por_variacao(db, [v.id for p in produtos for v in p.variacoes])


def _validar(db: Session, dados: ProdutoEntrada, produto_id: int | None) -> m.Categoria:
    if not dados.nome.strip():
        raise DadosInvalidos("Informe o nome do produto.")
    if not dados.categoria:
        raise DadosInvalidos("Selecione a categoria.")
    categoria = cadastro_repository.categoria_por_nome(db, dados.categoria)
    if categoria is None:
        raise DadosInvalidos(f"Categoria '{dados.categoria}' não existe.")
    if not dados.preco_base > 0:
        raise DadosInvalidos("Informe um preço base válido.")
    skus = [v.sku.strip().upper() for v in dados.variacoes]
    if any(not sku for sku in skus):
        raise DadosInvalidos("Toda variação precisa de um SKU.")
    if len(set(skus)) != len(skus):
        raise DadosInvalidos("Há SKUs repetidos nas variações.")
    if skus and (duplicado := produto_repository.sku_em_uso(db, skus, produto_id)):
        raise DadosInvalidos(f"O SKU {duplicado.sku} já está em uso.")
    return categoria


def _salvar_variacoes(db: Session, produto: m.Produto, dados: ProdutoEntrada) -> None:
    """Atualiza as variações enviadas; as novas recebem estoque zerado em todas as lojas.
    Variações omitidas não são apagadas, porque têm histórico de estoque."""
    existentes = {v.id: v for v in produto.variacoes}
    for entrada in dados.variacoes:
        campos = {"sku": entrada.sku.strip().upper(), "tamanho": entrada.tamanho.strip(), "cor": entrada.cor.strip()}
        if entrada.id is not None:
            variacao = existentes.get(entrada.id)
            if variacao is None:
                raise DadosInvalidos(f"A variação {entrada.id} não pertence a este produto.")
            for campo, valor in campos.items():
                setattr(variacao, campo, valor)
        else:
            variacao = m.Variacao(produto=produto, **campos)
            sessao.adicionar(db, variacao)
            criar_estoques_zerados(db, variacao)


def criar(db: Session, dados: ProdutoEntrada) -> m.Produto:
    categoria = _validar(db, dados, None)
    produto = m.Produto(
        nome=dados.nome.strip(),
        categoria=categoria,
        preco_base=dados.preco_base,
        ativo=dados.ativo,
        genero=dados.genero,
        estacao=dados.estacao,
        descricao=dados.descricao,
        composicao=dados.composicao,
        cuidados=dados.cuidados,
    )
    sessao.adicionar(db, produto)
    _salvar_variacoes(db, produto, dados)
    sessao.confirmar(db)
    return obter(db, produto.id)


def atualizar(db: Session, produto_id: int, dados: ProdutoEntrada) -> m.Produto:
    produto = obter(db, produto_id)
    produto.categoria = _validar(db, dados, produto.id)
    produto.nome = dados.nome.strip()
    produto.preco_base = dados.preco_base
    produto.ativo = dados.ativo
    # Campos que não aparecem no formulário do painel: só mudam se forem enviados
    for campo in ("genero", "estacao", "descricao", "composicao", "cuidados"):
        if campo in dados.model_fields_set:
            setattr(produto, campo, getattr(dados, campo))
    _salvar_variacoes(db, produto, dados)
    sessao.confirmar(db)
    sessao.descartar_cache(db)
    return obter(db, produto.id)
