"""Área "Meus pedidos" da loja: o cliente não tem login. E-mail + PIN de 4 dígitos (criado no
checkout) liberam os pedidos e os chamados daquele e-mail (regras em src/entities/cliente.py).

- O PIN só existe como hash (bcrypt). Erros seguidos bloqueiam o e-mail por 15 minutos; o
  contador fica no banco, então vale para todos os servidores e não some ao reiniciar.
- E-mail inexistente e PIN errado dão a mesma resposta, para não revelar quem já comprou.
- "Esqueci o PIN" cria um link de uso único que vale 30 minutos.
"""

import logging
import secrets

from sqlalchemy.orm import Session

from src import models as m
from src.config.settings import PIN_LINK_NA_RESPOSTA
from src.entities.cliente import VALIDADE_TOKEN_PIN, apos_erro_de_pin, bloqueado, email_valido, normalizar_email, pin_valido
from src.repositories import atendimento_repository, cliente_repository, pedido_repository, sessao
from src.schemas.atendimentos import AnexoEntrada
from src.use_cases import atendimentos
from src.utils.datas import agora
from src.utils.erros import DadosInvalidos, Expirado, MuitasTentativas, NaoAutenticado, NaoEncontrado
from src.utils.seguranca import confere_hash, gerar_hash

log = logging.getLogger("casalorenzi")

PIN_INCORRETO = "E-mail ou PIN incorretos."
PIN_BLOQUEADO = "Muitas tentativas incorretas. Tente de novo em 15 minutos."
CAMINHO_NOVO_PIN = "/meus-pedidos/novo-pin"


def texto_do_pin(pin) -> str:
    """O PIN pode chegar como texto ou número; "0123" precisa continuar com o zero."""
    return str(pin).strip() if pin is not None else ""


def conferir_pin(db: Session, cliente: m.Cliente, pin: str) -> bool:
    """Confere o PIN contando os erros. O contador é gravado na hora (mesmo que a operação
    seguinte falhe). Bloqueado: 429."""
    momento = agora()
    if bloqueado(cliente.bloqueado_ate, momento):
        raise MuitasTentativas(PIN_BLOQUEADO)
    if confere_hash(pin, cliente.pin_hash):
        if cliente.tentativas_pin or cliente.bloqueado_ate:
            cliente.tentativas_pin, cliente.bloqueado_ate = 0, None
            sessao.confirmar(db)
        return True
    cliente.tentativas_pin, bloqueado_ate = apos_erro_de_pin(cliente.tentativas_pin, momento)
    if bloqueado_ate is not None:
        cliente.bloqueado_ate = bloqueado_ate
    sessao.confirmar(db)
    return False


def identificar(db: Session, email: str | None, pin) -> m.Cliente:
    """Cliente dono do e-mail, se o PIN confere. Sem cliente, sem PIN criado ou PIN errado: a mesma resposta (401)."""
    cliente = cliente_repository.por_email(db, email, travar=True) if email_valido(email) else None
    if cliente is None or not cliente.pin_hash:
        raise NaoAutenticado(PIN_INCORRETO)
    if not conferir_pin(db, cliente, texto_do_pin(pin)):
        raise NaoAutenticado(PIN_INCORRETO)
    return cliente


def validar_novo_pin(pin, confirmacao) -> str:
    pin, confirmacao = texto_do_pin(pin), texto_do_pin(confirmacao)
    if not pin_valido(pin):
        raise DadosInvalidos("O PIN deve ter 4 números.")
    if pin != confirmacao:
        raise DadosInvalidos("Os PINs não conferem.")
    return pin


# ---------- Pedidos e chamados ----------


def pedidos(db: Session, email: str | None, pin) -> list[m.Pedido]:
    cliente = identificar(db, email, pin)
    return pedido_repository.do_cliente(db, cliente.id)


def solicitacoes(db: Session, email: str | None, pin) -> list[m.Atendimento]:
    """Chamados do cliente, com a conversa (mais recentes primeiro)."""
    cliente = identificar(db, email, pin)
    chamados = atendimento_repository.do_cliente(db, cliente.id)
    return sorted(chamados, key=lambda a: (a.atualizado_em, a.id), reverse=True)


def abrir_solicitacao(
    db: Session,
    email: str | None,
    pin,
    *,
    numero: str | None,
    tipo_solicitacao_id: int | None,
    descricao: str,
    anexo: AnexoEntrada | None = None,
) -> m.Atendimento:
    """Troca, devolução, reclamação etc. sobre um pedido do cliente. A foto (opcional) vai na primeira mensagem."""
    cliente = identificar(db, email, pin)
    pedido = pedido_repository.do_cliente_por_numero(db, cliente.id, numero or "")
    if pedido is None:
        raise NaoEncontrado("Pedido não encontrado.")
    return atendimentos.abrir_para_cliente(
        db, cliente, tipo_solicitacao_id=tipo_solicitacao_id, pedido_id=pedido.id, descricao=descricao, anexo=anexo
    )


def responder(db: Session, email: str | None, pin, atendimento_id: int, conteudo: str) -> m.Atendimento:
    cliente = identificar(db, email, pin)
    return atendimentos.responder_como_cliente(db, atendimento_id, cliente, conteudo)


# ---------- Esqueci o PIN ----------


def solicitar_novo_pin(db: Session, email: str | None) -> str | None:
    """Gera o link de troca para um cliente existente. A resposta da rota é a mesma exista ou não o
    e-mail. Devolve o link só com PIN_LINK_NA_RESPOSTA=true (demonstração); senão, ele sai no log."""
    alvo = normalizar_email(email)
    if not email_valido(alvo):
        raise DadosInvalidos("Informe um e-mail válido.")
    cliente = cliente_repository.por_email(db, alvo)
    if cliente is None:
        return None
    token = secrets.token_urlsafe(32)
    cliente_repository.criar_token_pin(db, cliente, token, agora() + VALIDADE_TOKEN_PIN)
    sessao.confirmar(db)
    link = f"{CAMINHO_NOVO_PIN}?token={token}"
    # Enquanto não há envio de e-mail, o link sai no log da API
    log.info("Link de troca de PIN para %s: %s", alvo, link)
    return link if PIN_LINK_NA_RESPOSTA else None


def redefinir_pin(db: Session, token: str | None, pin, confirmacao) -> str:
    """Define o novo PIN, desbloqueia o e-mail e invalida o link. Devolve o e-mail."""
    momento = agora()
    registro = cliente_repository.token_pin(db, (token or "").strip(), travar=True) if token else None
    if registro is None or registro.usado_em is not None or registro.expira_em < momento:
        raise Expirado("Este link expirou ou já foi usado. Peça um novo em Meus pedidos.")
    novo = validar_novo_pin(pin, confirmacao)
    cliente = registro.cliente
    cliente.pin_hash = gerar_hash(novo)
    cliente.tentativas_pin, cliente.bloqueado_ate = 0, None
    registro.usado_em = momento
    sessao.confirmar(db)
    return cliente.email
