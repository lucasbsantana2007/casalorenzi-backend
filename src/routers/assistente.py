"""Assistente do site (público). A conversa sem login é de quem tem a chave (cabeçalho X-Conversa-Chave);
com login de cliente, é da conta. Dados pessoais (pontos, pedidos) saem só do cliente do token."""

from typing import Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import Field
from sqlalchemy.orm import Session

from src.database.connection import get_db
from src.entities import assistente as regra
from src.middlewares import limite
from src.middlewares.autenticacao import Sessao, sessao_opcional
from src.schemas.comum import Entrada
from src.use_cases.assistente import conversas
from src.utils.erros import DadosInvalidos

router = APIRouter(prefix="/assistente", tags=["Assistente IA (site)"])


class AbrirConversa(Entrada):
    marca: Literal["LORENZI", "VULTO"] | None = None


class Acao(Entrada):
    tipo: Literal["FOCAR_PRODUTO"]
    produto_id: int


class MensagemEntrada(Entrada):
    texto: str = Field(max_length=4000)
    # Gerado pelo navegador: o reenvio da mesma mensagem devolve a mesma resposta
    id_cliente: str | None = Field(None, max_length=64)
    acao: Acao | None = None


class EventoEntrada(Entrada):
    tipo: Literal["SACOLA_ADICIONADA", "SACOLA_REMOVIDA", "ACAO_CONCLUIDA"]
    mensagem_id: int
    # Sacola: a peça do cartão
    variacao_id: int | None = None
    # ACAO_CONCLUIDA: o cliente confirmou no cartão e a rota da conta fez a ação (decisões 95 a 97)
    acao: Literal["EMAIL", "CANCELAMENTO", "DEVOLUCAO"] | None = None
    detalhe: str | None = Field(None, max_length=200)


class EncaminharEntrada(Entrada):
    motivo: str | None = Field(None, max_length=300)
    # SITE: a equipe responde em Minha conta (exige login). WHATSAPP: link wa.me com o protocolo (sem login)
    canal: Literal["SITE", "WHATSAPP"] = "SITE"


def _ip(request: Request) -> str:
    return request.client.host if request.client else "desconhecido"


def _cliente(sessao: Sessao | None):
    """Só conta de cliente identifica o dono; a equipe no site conversa como visitante."""
    return sessao.cliente if sessao is not None else None


@router.post("/conversas", status_code=201)
def abrir(
    dados: AbrirConversa, request: Request, db: Session = Depends(get_db), sessao: Sessao | None = Depends(sessao_opcional)
):
    """Conversa nova. A resposta traz a `chave`, que o navegador guarda e manda em X-Conversa-Chave."""
    maximo, janela = regra.LIMITE_CONVERSAS_POR_IP
    limite.conferir(f"assistente:abrir:{_ip(request)}", maximo=maximo, janela_segundos=janela)
    conversa, chave = conversas.abrir_cliente(db, cliente=_cliente(sessao), marca=dados.marca)
    return {**conversas.conversa_saida(db, conversa), "chave": chave}


@router.get("/conversas/{conversa_id}")
def obter(
    conversa_id: str,
    db: Session = Depends(get_db),
    sessao: Sessao | None = Depends(sessao_opcional),
    chave: str | None = Header(default=None, alias="X-Conversa-Chave"),
):
    """Histórico (últimas 50 mensagens). De outra pessoa: 404."""
    conversa = conversas.conversa_do_site(db, conversa_id, chave, _cliente(sessao))
    return conversas.conversa_saida(db, conversa)


@router.post("/conversas/{conversa_id}/mensagens")
def enviar(
    conversa_id: str,
    dados: MensagemEntrada,
    request: Request,
    db: Session = Depends(get_db),
    sessao: Sessao | None = Depends(sessao_opcional),
    chave: str | None = Header(default=None, alias="X-Conversa-Chave"),
):
    """Responde à mensagem. 409: a anterior ainda está sendo respondida. 410: conversa encerrada ou
    parada há mais de IA_CONVERSA_EXPIRA_HORAS (comece outra). 429: mensagens demais."""
    cliente = _cliente(sessao)
    conversa = conversas.conversa_do_site(db, conversa_id, chave, cliente)
    maximo, janela = regra.LIMITE_POR_CONVERSA[regra.CLIENTE]
    limite.conferir(f"assistente:conversa:{conversa.id}", maximo=maximo, janela_segundos=janela)
    maximo, janela = regra.LIMITE_POR_IP
    limite.conferir(f"assistente:ip:{_ip(request)}", maximo=maximo, janela_segundos=janela)
    pergunta, resposta = conversas.enviar(
        db,
        conversa,
        dados.texto,
        id_cliente=dados.id_cliente,
        acao={"tipo": dados.acao.tipo, "produtoId": dados.acao.produto_id} if dados.acao else None,
        cliente=cliente,
        request_id=getattr(request.state, "request_id", None),
    )
    return {
        "pergunta": conversas.mensagem_saida(pergunta),
        "resposta": conversas.mensagem_saida(resposta),
        "status": conversa.status,
    }


@router.post("/conversas/{conversa_id}/eventos", status_code=204, response_class=Response)
def evento(
    conversa_id: str,
    dados: EventoEntrada,
    db: Session = Depends(get_db),
    sessao: Sessao | None = Depends(sessao_opcional),
    chave: str | None = Header(default=None, alias="X-Conversa-Chave"),
):
    """A peça entrou na sacola do navegador (SACOLA_ADICIONADA), o cliente tocou em "Desfazer" (SACOLA_REMOVIDA) ou
    confirmou uma ação no cartão (ACAO_CONCLUIDA: e-mail, cancelamento ou devolução, já feita pela rota da conta).
    Só muda o cartão e a memória da conversa; a ação em si é sempre da rota da conta."""
    conversa = conversas.conversa_do_site(db, conversa_id, chave, _cliente(sessao))
    if dados.tipo == "ACAO_CONCLUIDA":
        if dados.acao is None:
            raise DadosInvalidos("Informe a ação concluída.")
        conversas.registrar_acao(db, conversa, dados.mensagem_id, dados.acao, dados.detalhe)
        return
    if dados.variacao_id is None:
        raise DadosInvalidos("Informe a peça.")
    removida = dados.tipo == "SACOLA_REMOVIDA"
    conversas.registrar_sacola(db, conversa, dados.mensagem_id, dados.variacao_id, removida=removida)


@router.post("/conversas/{conversa_id}/atendimento", status_code=201)
def encaminhar(
    conversa_id: str,
    dados: EncaminharEntrada,
    db: Session = Depends(get_db),
    sessao: Sessao | None = Depends(sessao_opcional),
    chave: str | None = Header(default=None, alias="X-Conversa-Chave"),
):
    """Abre um chamado de atendimento com o resumo da conversa. canal SITE exige login de cliente (401 sem
    ele); WHATSAPP não, e devolve `whatsappUrl` (422 se o WhatsApp do atendimento não estiver configurado).
    Chamar de novo devolve o mesmo chamado."""
    cliente = _cliente(sessao)
    conversa = conversas.conversa_do_site(db, conversa_id, chave, cliente)
    atendimento = conversas.encaminhar(db, conversa, cliente, dados.motivo, dados.canal)
    return {
        "atendimentoId": atendimento.id,
        "protocolo": atendimento.protocolo,
        "link": f"/cliente/solicitacoes/{atendimento.id}" if atendimento.cliente_id else None,
        "whatsappUrl": conversas.link_whatsapp(atendimento, dados.motivo) if dados.canal == "WHATSAPP" else None,
    }


@router.post("/conversas/{conversa_id}/encerrar", status_code=204, response_class=Response)
def encerrar(
    conversa_id: str,
    db: Session = Depends(get_db),
    sessao: Sessao | None = Depends(sessao_opcional),
    chave: str | None = Header(default=None, alias="X-Conversa-Chave"),
):
    """Botão "Nova conversa": esta deixa de receber mensagens (o histórico fica até a retenção)."""
    conversas.encerrar(db, conversas.conversa_do_site(db, conversa_id, chave, _cliente(sessao)))
