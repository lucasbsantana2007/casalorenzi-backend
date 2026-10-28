"""Canais externos de conversa com o cliente (decisão 108). O n8n recebe a mensagem no canal (hoje, o WhatsApp
Cloud API da Meta), chama esta rota e entrega a resposta no mesmo canal. Quem chama prova que é o n8n pelo segredo
do canal (X-Canal-Segredo), não por login: o cliente do WhatsApp não tem sessão no site."""

import hmac

from fastapi import APIRouter, Depends, Header
from pydantic import Field
from sqlalchemy.orm import Session

from src.config import settings
from src.database.connection import get_db
from src.schemas.comum import Entrada
from src.use_cases.assistente import canal_whatsapp
from src.utils.erros import DadosInvalidos, NaoAutenticado, NaoEncontrado

router = APIRouter(prefix="/canais", tags=["Canais (n8n)"])


class MensagemDoWhatsApp(Entrada):
    # Número de quem escreveu, com DDI (o "from" da Meta: 5511999999999)
    telefone: str = Field(max_length=32)
    # Vazio quando a mensagem não é de texto (áudio, foto, figurinha)
    texto: str | None = Field(None, max_length=4000)
    # O id da mensagem na Meta (wamid...): a mesma mensagem entregue duas vezes não gera duas respostas
    id_mensagem: str | None = Field(None, max_length=256)
    # O nome do perfil do WhatsApp, para o chamado de atendimento
    nome: str | None = Field(None, max_length=120)
    # Botão tocado (o id do button_reply da Meta): LUCIA, EQUIPE ou MENU (decisão 116)
    botao: str | None = Field(None, max_length=40)


def _canal_liberado(x_canal_segredo: str | None = Header(default=None)) -> None:
    if not settings.CANAL_WHATSAPP_SEGREDO:
        raise NaoEncontrado("Canal não configurado.")
    if not x_canal_segredo or not hmac.compare_digest(x_canal_segredo, settings.CANAL_WHATSAPP_SEGREDO):
        raise NaoAutenticado("Segredo do canal inválido.")


@router.post("/whatsapp/mensagens", dependencies=[Depends(_canal_liberado)])
def mensagem_do_whatsapp(dados: MensagemDoWhatsApp, db: Session = Depends(get_db)):
    """Responde a uma mensagem do WhatsApp. Devolve { responder, texto, mensagem, conversaId, protocolo }: "mensagem"
    é o corpo pronto para a Meta (texto ou botões); com responder=false (mensagem repetida), o n8n não manda nada."""
    telefone = canal_whatsapp.telefone_valido(dados.telefone)
    if telefone is None:
        raise DadosInvalidos("Telefone inválido: use só os números, com DDI e DDD.")
    return canal_whatsapp.responder(
        db, telefone=telefone, texto=dados.texto, id_mensagem=dados.id_mensagem, nome=dados.nome, botao=dados.botao
    )
