"""Atendimento: painel interno (administrador e lojista) e o cliente logado, que abre e responde
os próprios chamados. A equipe também abre chamados em nome do cliente."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import Sessao, exigir_cliente_ou_modulo, exigir_modulo
from src.repositories import atendimento_repository
from src.schemas.atendimentos import (
    AtendimentoAtualizacao,
    MensagemEntrada,
    SolicitacaoEntrada,
    atendimento_detalhado_saida,
    atendimento_saida,
)
from src.use_cases import atendimentos

router = APIRouter(prefix="/atendimentos", tags=["Atendimento"])
acesso_painel = exigir_modulo("atendimento")
acesso = exigir_cliente_ou_modulo("atendimento")


def lista_saida(db: Session, lista: list[m.Atendimento]) -> list[dict]:
    ultimas = atendimento_repository.ultimas_mensagens(db, [a.id for a in lista])
    return [atendimento_saida(a, ultimas.get(a.id)) for a in lista]


def detalhe_saida(db: Session, a: m.Atendimento) -> dict:
    return atendimento_detalhado_saida(a, *atendimentos.totais_do_cliente(db, a.cliente_id))


@router.get("")
def listar(
    busca: str | None = None,
    tipoSolicitacaoId: int | None = None,
    responsavelId: str | None = None,
    lojaId: int | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso_painel),
):
    """responsavelId='nenhum' lista os atendimentos sem responsável."""
    lista = atendimentos.listar(
        db, busca=busca, tipo_solicitacao_id=tipoSolicitacaoId, responsavel_id=responsavelId, loja_id=lojaId
    )
    return lista_saida(db, lista)


@router.post("", status_code=201)
def abrir(dados: SolicitacaoEntrada, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    """Cliente logado: abre o chamado para si (clienteId do corpo é ignorado).
    Equipe: abre em nome do cliente (clienteId obrigatório). A descrição entra como mensagem do cliente."""
    campos = {
        "tipo_solicitacao_id": dados.tipo_solicitacao_id,
        "pedido_id": dados.pedido_id,
        "descricao": dados.descricao,
        "anexo": dados.anexo,
    }
    if sessao.cliente is not None:
        a = atendimentos.abrir_para_cliente(db, sessao.cliente, **campos)
    else:
        a = atendimentos.abrir(db, sessao.usuario, cliente_id=dados.cliente_id, **campos)
    return detalhe_saida(db, a)


@router.get("/{atendimento_id}")
def obter(atendimento_id: int, db: Session = Depends(get_db), _: m.Usuario = Depends(acesso_painel)):
    return detalhe_saida(db, atendimentos.carregar(db, atendimento_id))


@router.patch("/{atendimento_id}")
def atualizar(
    atendimento_id: int, dados: AtendimentoAtualizacao, db: Session = Depends(get_db), _: m.Usuario = Depends(acesso_painel)
):
    a = atendimentos.atualizar(
        db,
        atendimento_id,
        status=dados.status,
        responsavel_id=dados.responsavel_id,
        mudar_responsavel="responsavel_id" in dados.model_fields_set,
    )
    return detalhe_saida(db, a)


@router.post("/{atendimento_id}/mensagens", status_code=201)
def enviar_mensagem(atendimento_id: int, dados: MensagemEntrada, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    """Resposta com imagem opcional em `anexo` ({ nome, tipo, conteudoBase64 }, até 2 MB).
    O autor vem do token (autorId/autorTipo do corpo são ignorados): cliente só responde os próprios chamados."""
    if sessao.cliente is not None:
        a = atendimentos.responder_como_cliente(db, atendimento_id, sessao.cliente, dados.conteudo, dados.anexo)
    else:
        a = atendimentos.enviar_mensagem(db, atendimento_id, sessao.usuario, dados.conteudo, dados.anexo)
    return detalhe_saida(db, a)
