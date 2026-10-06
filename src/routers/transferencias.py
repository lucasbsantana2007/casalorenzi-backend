from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.schemas.transferencias import TransferenciaEntrada, TransferenciaStatusEntrada, transferencia_saida
from src.use_cases import transferencias

router = APIRouter(prefix="/transferencias", tags=["Transferências"])
acesso = exigir_modulo("transferencias")


@router.get("")
def listar(
    status: str | None = None,
    lojaId: int | None = None,
    busca: str | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
):
    return [transferencia_saida(t) for t in transferencias.listar(db, status, lojaId, busca)]


@router.post("", status_code=201)
def criar(dados: TransferenciaEntrada, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    t = transferencias.criar(
        db,
        variacao_id=dados.variacao_id,
        loja_origem_id=dados.loja_origem_id,
        loja_destino_id=dados.loja_destino_id,
        quantidade=dados.quantidade,
        observacao=dados.observacao,
        usuario_id=usuario.id,
    )
    return transferencia_saida(t)


@router.patch("/{transferencia_id}")
def atualizar_status(
    transferencia_id: int, dados: TransferenciaStatusEntrada, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)
):
    """SOLICITADA → EM_TRANSITO → CONCLUIDA, ou SOLICITADA → CANCELADA. Outras mudanças: 409."""
    return transferencia_saida(transferencias.mudar_status(db, transferencia_id, dados.status, usuario.id))
