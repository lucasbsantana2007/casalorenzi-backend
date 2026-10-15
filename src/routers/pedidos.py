"""Pedidos no painel (módulo pedidos): lista, detalhe e mudanças de expedição e status.
Regras em src/use_cases/pedidos.py."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.papeis import ADMINISTRADOR
from src.middlewares.autenticacao import exigir_modulo
from src.schemas.pedidos import PedidoAtualizacao, pedido_admin_saida
from src.use_cases import faturamento, pedidos

router = APIRouter(prefix="/pedidos", tags=["Pedidos"])
acesso = exigir_modulo("pedidos")


def _saida(db: Session, pedido: m.Pedido, usuario: m.Usuario) -> dict:
    return pedido_admin_saida(pedido, pedidos.saldos_na_loja(db, pedido), ve_custo=usuario.papel == ADMINISTRADOR)


@router.get("")
def listar(
    status: str | None = None,
    lojaId: int | None = None,
    canal: str | None = None,
    busca: str | None = None,
    marca: Literal["LORENZI", "VULTO", "TODAS"] = "LORENZI",
    db: Session = Depends(get_db),
    usuario: m.Usuario = Depends(acesso),
):
    """busca: número do pedido (ou o do site/app da Vulto), nome ou e-mail do cliente. Mais recentes primeiro.
    Lojista e Operador recebem só os pedidos que a própria loja expede (o lojaId é ignorado).
    marca: padrão LORENZI (a lista do painel continua a mesma); VULTO traz os pedidos migrados da Vulto
    (use com status, lojaId ou busca: são ~18 mil) e TODAS, as duas marcas."""
    filtro = None if marca == "TODAS" else marca
    lista = pedidos.listar(db, usuario, status=status, loja_id=lojaId, canal=canal, busca=busca, marca=filtro)
    return [_saida(db, p, usuario) for p in lista]


@router.get("/vulto/{referencia}")
def venda_vulto(referencia: str, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    """Uma venda da Vulto na plataforma: pelo id da venda no sistema antigo (ex.: 1234), pelo número do
    pedido no site/app (S100234, APP-7001205) ou pelo número aqui (VLT-01234). `vendaVulto` é o id no
    sistema antigo. Venda que não virou pedido (teste, duplicata, devolução): 404 com o motivo."""
    pedido, venda_id = faturamento.venda_vulto(db, referencia, usuario)
    return {**_saida(db, pedido, usuario), "vendaVulto": venda_id}


@router.get("/{pedido_id}")
def obter(pedido_id: int, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    """O custo do frete só vem para o Administrador. Pedido de outra loja (Lojista e Operador): 404."""
    return _saida(db, pedidos.obter(db, pedido_id, usuario), usuario)


@router.patch("/{pedido_id}")
def atualizar(pedido_id: int, dados: PedidoAtualizacao, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    """{ lojaId } troca a loja de expedição (só o Administrador, antes do envio; os demais: 403).
    { status: 'ENVIADO', codigoRastreio }
    exige todas as peças na loja e baixa o estoque. { status: 'ENTREGUE' } e { status: 'CANCELADO' }
    (estorna o pagamento). Fora do fluxo: 409."""
    pedido = pedidos.atualizar(
        db, pedido_id, usuario, loja_id=dados.loja_id, status=dados.status, codigo_rastreio=dados.codigo_rastreio
    )
    return _saida(db, pedido, usuario)
