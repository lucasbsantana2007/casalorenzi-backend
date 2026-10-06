from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.schemas.produtos import ProdutoEntrada, produto_saida
from src.use_cases import produtos

router = APIRouter(prefix="/produtos", tags=["Produtos"])


def _saida(db: Session, produto: m.Produto) -> dict:
    return produto_saida(produto, produtos.totais_de_estoque(db, [produto]))


@router.get("")
def listar(busca: str | None = None, categoria: str | None = None, ativo: bool | None = None, db: Session = Depends(get_db)):
    """Pública: alimenta também a vitrine da loja."""
    lista = produtos.listar(db, busca, categoria, ativo)
    totais = produtos.totais_de_estoque(db, lista)
    return [produto_saida(p, totais) for p in lista]


@router.get("/{produto_id}")
def obter(produto_id: int, db: Session = Depends(get_db)):
    return _saida(db, produtos.obter(db, produto_id))


@router.post("", status_code=201)
def criar(dados: ProdutoEntrada, db: Session = Depends(get_db), _: m.Usuario = Depends(exigir_modulo("produtos"))):
    return _saida(db, produtos.criar(db, dados))


@router.put("/{produto_id}")
def atualizar(
    produto_id: int, dados: ProdutoEntrada, db: Session = Depends(get_db), _: m.Usuario = Depends(exigir_modulo("produtos"))
):
    return _saida(db, produtos.atualizar(db, produto_id, dados))
