"""Pedidos no painel (módulo pedidos): lista, detalhe e mudanças de expedição e status.
Regras em src/use_cases/pedidos.py."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.papeis import ADMINISTRADOR
from src.middlewares.autenticacao import exigir_modulo
from src.schemas.pedidos import PedidoAtualizacao, pedido_admin_saida
from src.use_cases import pedidos

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
    db: Session = Depends(get_db),
    usuario: m.Usuario = Depends(acesso),
):
    """busca: número do pedido, nome ou e-mail do cliente. Mais recentes primeiro.
    Lojista e Operador recebem só os pedidos que a própria loja expede (o lojaId é ignorado)."""
    return [_saida(db, p, usuario) for p in pedidos.listar(db, usuario, status=status, loja_id=lojaId, canal=canal, busca=busca)]


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
