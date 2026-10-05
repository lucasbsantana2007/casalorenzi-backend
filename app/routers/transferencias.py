"""Transferências entre lojas.

Fluxo: SOLICITADA → EM_TRANSITO (baixa na origem) → CONCLUIDA (entrada no destino)
       SOLICITADA → CANCELADA
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Transferencia, Usuario, Variacao
from app.schemas import TransferenciaEntrada, TransferenciaStatusEntrada
from app.security import exigir_modulo
from app.services import aplicar_movimentacao, estoque_por
from app.utils import agora, corresponde
from app.views import transferencia_view

router = APIRouter(prefix="/transferencias", tags=["Transferências"])
acesso = exigir_modulo("transferencias")


@router.get("")
def listar(
    status: str | None = None,
    lojaId: int | None = None,
    busca: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(acesso),
):
    consulta = select(Transferencia).order_by(Transferencia.criado_em.desc(), Transferencia.id)
    if status:
        consulta = consulta.where(Transferencia.status == status)
    if lojaId:
        consulta = consulta.where(
            or_(Transferencia.loja_origem_id == lojaId, Transferencia.loja_destino_id == lojaId)
        )
    return [
        transferencia_view(t)
        for t in db.scalars(consulta)
        if corresponde(busca, t.codigo, t.variacao.produto.nome, t.variacao.sku)
    ]


@router.post("", status_code=201)
def criar(dados: TransferenciaEntrada, db: Session = Depends(get_db), usuario: Usuario = Depends(acesso)):
    if not dados.variacao_id or db.get(Variacao, dados.variacao_id) is None:
        raise HTTPException(422, "Selecione o item a transferir.")
    if dados.loja_origem_id == dados.loja_destino_id:
        raise HTTPException(422, "A loja de destino deve ser diferente da origem.")
    origem = estoque_por(db, dados.loja_origem_id, dados.variacao_id)
    if origem is None:
        raise HTTPException(404, "Item não encontrado na loja de origem.")
    if estoque_por(db, dados.loja_destino_id, dados.variacao_id) is None:
        raise HTTPException(404, "Item não encontrado na loja de destino.")
    if dados.quantidade <= 0:
        raise HTTPException(422, "Informe uma quantidade válida.")
    if dados.quantidade > origem.quantidade:
        raise HTTPException(422, f"A loja de origem possui apenas {origem.quantidade} unidade(s).")

    transferencia = Transferencia(
        codigo=f"TMP-{uuid.uuid4().hex[:12]}",  # trocado pelo código definitivo assim que o id existe
        variacao_id=dados.variacao_id,
        loja_origem_id=dados.loja_origem_id,
        loja_destino_id=dados.loja_destino_id,
        quantidade=dados.quantidade,
        status="SOLICITADA",
        solicitante_id=usuario.id,
        observacao=dados.observacao.strip(),
        criado_em=agora(),
    )
    db.add(transferencia)
    db.flush()
    transferencia.codigo = f"TRF-{transferencia.id:04d}"
    db.commit()
    return transferencia_view(transferencia)


@router.patch("/{transferencia_id}")
def atualizar_status(
    transferencia_id: int,
    dados: TransferenciaStatusEntrada,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(acesso),
):
    t = db.get(Transferencia, transferencia_id, with_for_update={"of": Transferencia})
    if t is None:
        raise HTTPException(404, "Transferência não encontrada.")
    rota = f"{t.codigo} · {t.loja_origem.nome} → {t.loja_destino.nome}"

    if dados.status == "EM_TRANSITO" and t.status == "SOLICITADA":
        origem = estoque_por(db, t.loja_origem_id, t.variacao_id, travar=True)
        aplicar_movimentacao(
            db, origem, tipo="TRANSFERENCIA_SAIDA", quantidade=-t.quantidade,
            origem=rota, usuario_id=usuario.id, transferencia_id=t.id,
        )
        t.status, t.enviado_em, t.responsavel_id = "EM_TRANSITO", agora(), usuario.id
    elif dados.status == "CONCLUIDA" and t.status == "EM_TRANSITO":
        destino = estoque_por(db, t.loja_destino_id, t.variacao_id, travar=True)
        aplicar_movimentacao(
            db, destino, tipo="TRANSFERENCIA_ENTRADA", quantidade=t.quantidade,
            origem=rota, usuario_id=usuario.id, transferencia_id=t.id,
        )
        t.status, t.recebido_em = "CONCLUIDA", agora()
    elif dados.status == "CANCELADA" and t.status == "SOLICITADA":
        t.status = "CANCELADA"
    else:
        raise HTTPException(409, "Mudança de status não permitida.")

    db.commit()
    db.refresh(t)
    return transferencia_view(t)
