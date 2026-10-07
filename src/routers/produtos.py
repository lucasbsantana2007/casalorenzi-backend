from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.papeis import ADMINISTRADOR
from src.middlewares.autenticacao import Sessao, exigir_modulo, sessao_opcional
from src.schemas.produtos import ProdutoEntrada, produto_saida
from src.use_cases import produtos

router = APIRouter(prefix="/produtos", tags=["Produtos"])
acesso_admin = exigir_modulo("produtos")


def _ve_custo(sessao: Sessao | None) -> bool:
    return sessao is not None and sessao.usuario is not None and sessao.usuario.papel == ADMINISTRADOR


def _saida(db: Session, produto: m.Produto, com_custo: bool) -> dict:
    return produto_saida(produto, produtos.totais_de_estoque(db, [produto]), com_custo)


@router.get("")
def listar(
    busca: str | None = None,
    categoria: str | None = None,
    ativo: bool | None = None,
    db: Session = Depends(get_db),
    sessao: Sessao | None = Depends(sessao_opcional),
):
    """Pública: alimenta também a vitrine da loja. precoCusto das variações só para o Administrador."""
    lista = produtos.listar(db, busca, categoria, ativo)
    totais = produtos.totais_de_estoque(db, lista)
    com_custo = _ve_custo(sessao)
    return [produto_saida(p, totais, com_custo) for p in lista]


@router.get("/{produto_id}")
def obter(produto_id: int, db: Session = Depends(get_db), sessao: Sessao | None = Depends(sessao_opcional)):
    return _saida(db, produtos.obter(db, produto_id), _ve_custo(sessao))


@router.get("/{produto_id}/imagem", response_class=Response)
def imagem(produto_id: int, db: Session = Depends(get_db)):
    """Pública: a foto enviada no cadastro (o link, com ?v=, vem em imagemUrl)."""
    foto = produtos.imagem(db, produto_id)
    return Response(content=foto.dados, media_type=foto.tipo, headers={"Cache-Control": "public, max-age=604800"})


@router.post("", status_code=201)
def criar(dados: ProdutoEntrada, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso_admin)):
    """Só Administrador. Variações com precoCusto; foto opcional em `imagem` ({ nome, tipo, conteudoBase64 })."""
    return _saida(db, produtos.criar(db, dados, usuario), com_custo=True)


@router.put("/{produto_id}")
def atualizar(produto_id: int, dados: ProdutoEntrada, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso_admin)):
    """Só Administrador. `imagem` troca a foto; `removerImagem: true` volta à ilustração. Mudanças vão para o log."""
    return _saida(db, produtos.atualizar(db, produto_id, dados, usuario), com_custo=True)


@router.delete("/{produto_id}", status_code=204, response_class=Response)
def remover(produto_id: int, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso_admin)):
    """Só Administrador. Tira o produto da loja, do painel e do estoque; pedidos, vendas e o histórico
    continuam. Pedido em processamento ou transferência pendente da peça: 409."""
    produtos.remover(db, produto_id, usuario)
