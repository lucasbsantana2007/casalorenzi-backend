from typing import Literal

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.marca import MARCA_DO_SITE, marca_do_escopo
from src.entities.papeis import ADMINISTRADOR
from src.middlewares.autenticacao import Sessao, escopo_marca, exigir_modulo, sessao_opcional
from src.schemas.produtos import ProdutoEntrada, produto_saida
from src.use_cases import produtos

router = APIRouter(prefix="/produtos", tags=["Produtos"])
acesso_admin = exigir_modulo("produtos")


def _ve_custo(sessao: Sessao | None) -> bool:
    return sessao is not None and sessao.usuario is not None and sessao.usuario.papel == ADMINISTRADOR


def _marca_visivel(sessao: Sessao | None, marca: str | None, x_marca: str | None = None) -> str | None:
    """A vitrine de cada marca pede a sua; sem marca, o visitante recebe a do início do site. A equipe vê
    só a marca dela (o Administrador do grupo, as duas ou a do seletor do painel)."""
    if sessao is not None and sessao.usuario is not None:
        escopo = marca_do_escopo(sessao.usuario.marca, x_marca)
        if escopo and marca and marca != escopo:
            return "-"  # pediu a outra marca: nada
        return escopo or marca
    return marca or MARCA_DO_SITE


def _saida(db: Session, produto: m.Produto, com_custo: bool) -> dict:
    return produto_saida(
        produto, produtos.totais_de_estoque(db, [produto]), com_custo, produtos.disponiveis_para_venda(db, [produto])
    )


@router.get("")
def listar(
    busca: str | None = None,
    categoria: str | None = None,
    ativo: bool | None = None,
    marca: Literal["LORENZI", "VULTO"] | None = None,
    db: Session = Depends(get_db),
    sessao: Sessao | None = Depends(sessao_opcional),
    x_marca: str | None = Header(default=None, alias="X-Marca"),
):
    """Pública: alimenta também a vitrine da loja. estoqueTotal é o físico; disponivel desconta as peças
    reservadas por pedidos ainda não enviados. precoCusto das variações só para o Administrador."""
    lista = produtos.listar(db, busca, categoria, ativo, _marca_visivel(sessao, marca, x_marca))
    totais = produtos.totais_de_estoque(db, lista)
    disponiveis = produtos.disponiveis_para_venda(db, lista)
    com_custo = _ve_custo(sessao)
    return [produto_saida(p, totais, com_custo, disponiveis) for p in lista]


@router.get("/{produto_id}")
def obter(
    produto_id: int,
    db: Session = Depends(get_db),
    sessao: Sessao | None = Depends(sessao_opcional),
    x_marca: str | None = Header(default=None, alias="X-Marca"),
):
    """Pública: a página da peça abre as das duas marcas. A equipe só abre as da marca dela."""
    escopo = marca_do_escopo(sessao.usuario.marca, x_marca) if sessao is not None and sessao.usuario is not None else None
    return _saida(db, produtos.obter(db, produto_id, escopo), _ve_custo(sessao))


@router.get("/{produto_id}/imagem", response_class=Response)
def imagem(produto_id: int, db: Session = Depends(get_db)):
    """Pública: a foto enviada no cadastro (o link, com ?v=, vem em imagemUrl)."""
    foto = produtos.imagem(db, produto_id)
    return Response(content=foto.dados, media_type=foto.tipo, headers={"Cache-Control": "public, max-age=604800"})


@router.post("", status_code=201)
def criar(
    dados: ProdutoEntrada,
    db: Session = Depends(get_db),
    usuario: m.Usuario = Depends(acesso_admin),
    marca: str | None = Depends(escopo_marca),
):
    """Só Administrador. Variações com precoCusto; foto opcional em `imagem` ({ nome, tipo, conteudoBase64 }).
    A peça é da marca do Administrador; o do grupo escolhe em `marca` (sem ela, Casa Lorenzi)."""
    return _saida(db, produtos.criar(db, dados, usuario, marca), com_custo=True)


@router.put("/{produto_id}")
def atualizar(
    produto_id: int,
    dados: ProdutoEntrada,
    db: Session = Depends(get_db),
    usuario: m.Usuario = Depends(acesso_admin),
    marca: str | None = Depends(escopo_marca),
):
    """Só Administrador. `imagem` troca a foto; `removerImagem: true` volta à ilustração. Mudanças vão para o log.
    Peça de outra marca: 404."""
    produtos.obter(db, produto_id, marca)
    return _saida(db, produtos.atualizar(db, produto_id, dados, usuario), com_custo=True)


@router.delete("/{produto_id}", status_code=204, response_class=Response)
def remover(
    produto_id: int,
    db: Session = Depends(get_db),
    usuario: m.Usuario = Depends(acesso_admin),
    marca: str | None = Depends(escopo_marca),
):
    """Só Administrador. Tira o produto da loja, do painel e do estoque; pedidos, vendas e o histórico
    continuam. Pedido em processamento ou transferência pendente da peça: 409. Outra marca: 404."""
    produtos.obter(db, produto_id, marca)
    produtos.remover(db, produto_id, usuario)
