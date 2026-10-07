"""Transferências entre lojas (fluxo em src/entities/transferencia.py)."""

import uuid

from sqlalchemy.orm import Session

from src import models as m
from src.entities.transferencia import codigo, pode_mudar
from src.repositories import cadastro_repository, estoque_repository, produto_repository, sessao, transferencia_repository
from src.use_cases import log_acoes
from src.use_cases.estoque import aplicar_movimentacao
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos, NaoEncontrado
from src.utils.texto import corresponde


def listar(db: Session, status: str | None = None, loja_id: int | None = None, busca: str | None = None) -> list[m.Transferencia]:
    return [
        t
        for t in transferencia_repository.listar(db, status=status, loja_id=loja_id)
        if corresponde(busca, t.codigo, t.variacao.produto.nome, t.variacao.sku)
    ]


def nova(
    db: Session,
    *,
    variacao_id: int,
    loja_origem_id: int,
    loja_destino_id: int,
    quantidade: int,
    solicitante_id: int | None,
    observacao: str = "",
) -> m.Transferencia:
    """Cria a transferência (sem confirmar). O código definitivo depende do id gerado pelo banco."""
    transferencia = m.Transferencia(
        codigo=f"TMP-{uuid.uuid4().hex[:12]}",
        variacao_id=variacao_id,
        loja_origem_id=loja_origem_id,
        loja_destino_id=loja_destino_id,
        quantidade=quantidade,
        status="SOLICITADA",
        solicitante_id=solicitante_id,
        observacao=observacao,
        criado_em=agora(),
    )
    sessao.adicionar(db, transferencia)
    sessao.gerar_ids(db)
    transferencia.codigo = codigo(transferencia.id)
    return transferencia


def criar(
    db: Session,
    *,
    variacao_id: int | None,
    loja_origem_id: int,
    loja_destino_id: int,
    quantidade: int,
    observacao: str,
    usuario_id: int,
) -> m.Transferencia:
    variacao = produto_repository.variacao(db, variacao_id) if variacao_id else None
    if variacao is None:
        raise DadosInvalidos("Selecione o item a transferir.")
    if variacao.produto.removido_em is not None:
        raise Conflito("Este produto foi removido do catálogo.")
    if loja_origem_id == loja_destino_id:
        raise DadosInvalidos("A loja de destino deve ser diferente da origem.")
    origem = estoque_repository.por_loja_e_variacao(db, loja_origem_id, variacao_id)
    if origem is None:
        raise NaoEncontrado("Item não encontrado na loja de origem.")
    if estoque_repository.por_loja_e_variacao(db, loja_destino_id, variacao_id) is None:
        raise NaoEncontrado("Item não encontrado na loja de destino.")
    if quantidade <= 0:
        raise DadosInvalidos("Informe uma quantidade válida.")
    if quantidade > origem.quantidade:
        raise DadosInvalidos(f"A loja de origem possui apenas {origem.quantidade} unidade(s).")

    transferencia = nova(
        db,
        variacao_id=variacao_id,
        loja_origem_id=loja_origem_id,
        loja_destino_id=loja_destino_id,
        quantidade=quantidade,
        solicitante_id=usuario_id,
        observacao=observacao.strip(),
    )
    log_acoes.registrar(
        db,
        usuario_id,
        "TRANSFERENCIAS",
        "SOLICITOU",
        f"Solicitou a transferência {transferencia.codigo}: {quantidade}× {origem.variacao.sku} "
        f"de {origem.loja.nome} para {transferencia_destino_nome(db, loja_destino_id)}",
        referencia=("transferencia", transferencia.id),
    )
    sessao.confirmar(db)
    return transferencia


def transferencia_destino_nome(db: Session, loja_id: int) -> str:
    loja = cadastro_repository.loja(db, loja_id)
    return loja.nome if loja else "—"


def mudar_status(db: Session, transferencia_id: int, status: str, usuario_id: int) -> m.Transferencia:
    t = transferencia_repository.obter(db, transferencia_id, travar=True)
    if t is None:
        raise NaoEncontrado("Transferência não encontrada.")
    if not pode_mudar(t.status, status):
        raise Conflito("Mudança de status não permitida.")
    rota = f"{t.codigo} · {t.loja_origem.nome} → {t.loja_destino.nome}"

    if status == "EM_TRANSITO":
        origem = estoque_repository.por_loja_e_variacao(db, t.loja_origem_id, t.variacao_id, travar=True)
        aplicar_movimentacao(
            db,
            origem,
            tipo="TRANSFERENCIA_SAIDA",
            quantidade=-t.quantidade,
            origem=rota,
            usuario_id=usuario_id,
            transferencia_id=t.id,
        )
        t.status, t.enviado_em, t.responsavel_id = "EM_TRANSITO", agora(), usuario_id
    elif status == "CONCLUIDA":
        destino = estoque_repository.por_loja_e_variacao(db, t.loja_destino_id, t.variacao_id, travar=True)
        aplicar_movimentacao(
            db,
            destino,
            tipo="TRANSFERENCIA_ENTRADA",
            quantidade=t.quantidade,
            origem=rota,
            usuario_id=usuario_id,
            transferencia_id=t.id,
        )
        t.status, t.recebido_em = "CONCLUIDA", agora()
    else:
        t.status = "CANCELADA"

    verbo = {"EM_TRANSITO": "Enviou", "CONCLUIDA": "Recebeu", "CANCELADA": "Cancelou"}[status]
    log_acoes.registrar(
        db, usuario_id, "TRANSFERENCIAS", status, f"{verbo} a transferência {rota}", referencia=("transferencia", t.id)
    )
    sessao.confirmar(db, t)
    return t
