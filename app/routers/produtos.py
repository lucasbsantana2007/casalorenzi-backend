from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Categoria, Produto, Usuario, Variacao
from app.schemas import ProdutoEntrada
from app.security import exigir_modulo
from app.services import criar_estoques_zerados
from app.utils import chave_texto, corresponde
from app.views import estoque_por_variacao, produto_view

router = APIRouter(prefix="/produtos", tags=["Produtos"])


def _carregar(db: Session, produto_id: int) -> Produto:
    produto = db.scalar(
        select(Produto).options(selectinload(Produto.variacoes)).where(Produto.id == produto_id)
    )
    if produto is None:
        raise HTTPException(404, "Produto não encontrado.")
    return produto


def _view(db: Session, produto: Produto) -> dict:
    return produto_view(produto, estoque_por_variacao(db, [v.id for v in produto.variacoes]))


@router.get("")
def listar(
    busca: str | None = None,
    categoria: str | None = None,
    ativo: bool | None = None,
    db: Session = Depends(get_db),
):
    """Pública: alimenta também a vitrine da loja."""
    consulta = (
        select(Produto).join(Produto.categoria).options(selectinload(Produto.variacoes)).order_by(Produto.id)
    )
    if categoria:
        consulta = consulta.where(Categoria.nome == categoria)
    if ativo is not None:
        consulta = consulta.where(Produto.ativo.is_(ativo))
    produtos = [
        p
        for p in db.scalars(consulta)
        if corresponde(busca, p.nome, p.categoria.nome, *(v.sku for v in p.variacoes))
    ]
    produtos.sort(key=lambda p: chave_texto(p.nome))
    totais = estoque_por_variacao(db, [v.id for p in produtos for v in p.variacoes])
    return [produto_view(p, totais) for p in produtos]


@router.get("/{produto_id}")
def obter(produto_id: int, db: Session = Depends(get_db)):
    return _view(db, _carregar(db, produto_id))


def _validar(db: Session, dados: ProdutoEntrada, produto_id: int | None) -> Categoria:
    if not dados.nome.strip():
        raise HTTPException(422, "Informe o nome do produto.")
    if not dados.categoria:
        raise HTTPException(422, "Selecione a categoria.")
    categoria = db.scalar(select(Categoria).where(Categoria.nome == dados.categoria))
    if categoria is None:
        raise HTTPException(422, f"Categoria '{dados.categoria}' não existe.")
    if not dados.preco_base > 0:
        raise HTTPException(422, "Informe um preço base válido.")
    skus = [v.sku.strip().upper() for v in dados.variacoes]
    if any(not sku for sku in skus):
        raise HTTPException(422, "Toda variação precisa de um SKU.")
    if len(set(skus)) != len(skus):
        raise HTTPException(422, "Há SKUs repetidos nas variações.")
    if skus:
        consulta = select(Variacao).where(Variacao.sku.in_(skus))
        if produto_id is not None:
            consulta = consulta.where(Variacao.produto_id != produto_id)
        duplicado = db.scalar(consulta)
        if duplicado:
            raise HTTPException(422, f"O SKU {duplicado.sku} já está em uso.")
    return categoria


def _salvar_variacoes(db: Session, produto: Produto, dados: ProdutoEntrada) -> None:
    """Atualiza as variações enviadas; as novas recebem estoque zerado em todas as lojas.
    Variações omitidas não são apagadas, porque têm histórico de estoque."""
    existentes = {v.id: v for v in produto.variacoes}
    for entrada in dados.variacoes:
        campos = {"sku": entrada.sku.strip().upper(), "tamanho": entrada.tamanho.strip(), "cor": entrada.cor.strip()}
        if entrada.id is not None:
            variacao = existentes.get(entrada.id)
            if variacao is None:
                raise HTTPException(422, f"A variação {entrada.id} não pertence a este produto.")
            for campo, valor in campos.items():
                setattr(variacao, campo, valor)
        else:
            variacao = Variacao(produto=produto, **campos)
            db.add(variacao)
            criar_estoques_zerados(db, variacao)


@router.post("", status_code=201)
def criar(
    dados: ProdutoEntrada,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_modulo("produtos")),
):
    categoria = _validar(db, dados, None)
    produto = Produto(
        nome=dados.nome.strip(),
        categoria=categoria,
        preco_base=dados.preco_base,
        ativo=dados.ativo,
        genero=dados.genero,
        estacao=dados.estacao,
    )
    db.add(produto)
    _salvar_variacoes(db, produto, dados)
    db.commit()
    return _view(db, _carregar(db, produto.id))


@router.put("/{produto_id}")
def atualizar(
    produto_id: int,
    dados: ProdutoEntrada,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_modulo("produtos")),
):
    produto = _carregar(db, produto_id)
    produto.categoria = _validar(db, dados, produto.id)
    produto.nome = dados.nome.strip()
    produto.preco_base = dados.preco_base
    produto.ativo = dados.ativo
    # genero/estacao não aparecem no formulário do painel: só mudam se forem enviados
    if "genero" in dados.model_fields_set:
        produto.genero = dados.genero
    if "estacao" in dados.model_fields_set:
        produto.estacao = dados.estacao
    _salvar_variacoes(db, produto, dados)
    db.commit()
    db.expire_all()
    return _view(db, _carregar(db, produto.id))
