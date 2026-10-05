"""Atendimento: painel interno (administrador e lojista) e abertura/resposta pelo cliente."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ATENDIMENTO_ABERTO, Atendimento, Mensagem, Pedido, TipoSolicitacao, Usuario
from app.schemas import AtendimentoAtualizacao, MensagemEntrada, SolicitacaoEntrada
from app.security import ACESSO, EQUIPE, exigir_modulo, usuario_atual
from app.utils import agora, corresponde
from app.views import atendimento_detalhado, atendimentos_view

router = APIRouter(prefix="/atendimentos", tags=["Atendimento"])
acesso_painel = exigir_modulo("atendimento")


def carregar_atendimento(db: Session, atendimento_id: int, usuario: Usuario) -> Atendimento:
    """Equipe de atendimento vê todos; cliente só vê os próprios (os demais aparecem como inexistentes)."""
    atendimento = db.get(Atendimento, atendimento_id)
    if usuario.papel == "CLIENTE":
        if atendimento is None or atendimento.solicitante_id != usuario.id:
            raise HTTPException(404, "Solicitação não encontrada.")
    elif usuario.papel not in ACESSO["atendimento"]:
        raise HTTPException(403, "Seu perfil não tem acesso a este recurso.")
    elif atendimento is None:
        raise HTTPException(404, "Atendimento não encontrado.")
    return atendimento


def _evento_sistema(db: Session, atendimento: Atendimento, conteudo: str) -> None:
    db.add(Mensagem(atendimento=atendimento, autor_id=None, autor_tipo="SISTEMA", conteudo=conteudo, enviado_em=agora()))


@router.get("")
def listar(
    busca: str | None = None,
    tipoSolicitacaoId: int | None = None,
    responsavelId: str | None = None,
    lojaId: int | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(acesso_painel),
):
    """responsavelId='nenhum' lista os atendimentos sem responsável."""
    consulta = select(Atendimento).order_by(Atendimento.atualizado_em.desc(), Atendimento.id)
    if tipoSolicitacaoId:
        consulta = consulta.where(Atendimento.tipo_solicitacao_id == tipoSolicitacaoId)
    if lojaId:
        consulta = consulta.where(Atendimento.loja_id == lojaId)
    if responsavelId == "nenhum":
        consulta = consulta.where(Atendimento.responsavel_id.is_(None))
    elif responsavelId:
        if not responsavelId.isdigit():
            raise HTTPException(422, "Responsável inválido.")
        consulta = consulta.where(Atendimento.responsavel_id == int(responsavelId))
    atendimentos = [
        a
        for a in db.scalars(consulta)
        if corresponde(busca, a.protocolo, a.solicitante.nome, a.tipo_solicitacao.titulo)
    ]
    return atendimentos_view(db, atendimentos)


@router.post("", status_code=201)
def abrir(dados: SolicitacaoEntrada, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)):
    """Abre uma solicitação. O cliente abre para si mesmo; a equipe de atendimento pode abrir para um cliente."""
    if usuario.papel == "CLIENTE":
        cliente = usuario
    elif usuario.papel in ACESSO["atendimento"]:
        cliente = db.get(Usuario, dados.cliente_id) if dados.cliente_id else None
        if cliente is None or cliente.papel != "CLIENTE":
            raise HTTPException(422, "Informe um cliente válido.")
    else:
        raise HTTPException(403, "Seu perfil não tem acesso a este recurso.")

    tipo = db.get(TipoSolicitacao, dados.tipo_solicitacao_id) if dados.tipo_solicitacao_id else None
    if tipo is None or not tipo.ativo:
        raise HTTPException(422, "Selecione o tipo de solicitação.")
    if tipo.exige_venda and not dados.pedido_id:
        raise HTTPException(422, "Este tipo de solicitação exige o número do pedido.")
    descricao = dados.descricao.strip()
    if len(descricao) < 10:
        raise HTTPException(422, "Descreva sua solicitação com pelo menos 10 caracteres.")

    pedido = None
    if dados.pedido_id:
        pedido = db.get(Pedido, dados.pedido_id)
        if pedido is None or pedido.cliente_id != cliente.id:
            raise HTTPException(422, "Pedido não encontrado entre os pedidos do cliente.")

    momento = agora()
    atendimento = Atendimento(
        protocolo=f"TMP-{uuid.uuid4().hex[:12]}",  # trocado pelo protocolo definitivo assim que o id existe
        solicitante_id=cliente.id,
        tipo_solicitacao_id=tipo.id,
        status="ABERTO",
        pedido_id=pedido.id if pedido else None,
        loja_id=pedido.loja_id if pedido else (cliente.loja_preferida_id or 1),
        criado_em=momento,
        atualizado_em=momento,
    )
    db.add(atendimento)
    db.flush()
    atendimento.protocolo = f"ATD-{26000 + atendimento.id * 37:06d}"
    db.add(Mensagem(atendimento=atendimento, autor_id=cliente.id, autor_tipo="CLIENTE", conteudo=descricao, enviado_em=momento))
    db.commit()
    db.refresh(atendimento)
    return atendimento_detalhado(db, atendimento)


@router.get("/{atendimento_id}")
def obter(atendimento_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)):
    return atendimento_detalhado(db, carregar_atendimento(db, atendimento_id, usuario))


@router.patch("/{atendimento_id}")
def atualizar(
    atendimento_id: int,
    dados: AtendimentoAtualizacao,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(acesso_painel),
):
    atendimento = carregar_atendimento(db, atendimento_id, usuario)
    if "responsavel_id" in dados.model_fields_set and dados.responsavel_id != atendimento.responsavel_id:
        responsavel = None
        if dados.responsavel_id is not None:
            responsavel = db.get(Usuario, dados.responsavel_id)
            if responsavel is None or responsavel.papel not in EQUIPE:
                raise HTTPException(422, "Responsável inválido.")
        atendimento.responsavel_id = dados.responsavel_id
        _evento_sistema(
            db, atendimento, f"Atendimento atribuído a {responsavel.nome}." if responsavel else "Responsável removido."
        )
    if dados.status and dados.status != atendimento.status:
        atendimento.status = dados.status
        _evento_sistema(db, atendimento, f'Status alterado para "{dados.status.replace("_", " ").lower()}".')
    atendimento.atualizado_em = agora()
    db.commit()
    db.refresh(atendimento)
    return atendimento_detalhado(db, atendimento)


@router.post("/{atendimento_id}/mensagens", status_code=201)
def enviar_mensagem(
    atendimento_id: int,
    dados: MensagemEntrada,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    """O autor e o tipo de autor vêm do token (os campos autorId/autorTipo do corpo são ignorados)."""
    atendimento = carregar_atendimento(db, atendimento_id, usuario)
    conteudo = dados.conteudo.strip()
    if not conteudo:
        raise HTTPException(422, "A mensagem não pode ficar vazia.")
    autor_tipo = "CLIENTE" if usuario.papel == "CLIENTE" else "ATENDENTE"
    db.add(Mensagem(atendimento=atendimento, autor_id=usuario.id, autor_tipo=autor_tipo, conteudo=conteudo, enviado_em=agora()))

    # Resposta interna move o caso para "aguardando cliente"; resposta do cliente reabre.
    if autor_tipo == "ATENDENTE" and atendimento.status in ATENDIMENTO_ABERTO:
        atendimento.status = "AGUARDANDO_CLIENTE"
        if atendimento.responsavel_id is None:
            atendimento.responsavel_id = usuario.id
    if autor_tipo == "CLIENTE" and atendimento.status == "AGUARDANDO_CLIENTE":
        atendimento.status = "EM_ANDAMENTO"
    atendimento.atualizado_em = agora()
    db.commit()
    db.refresh(atendimento)
    return atendimento_detalhado(db, atendimento)
