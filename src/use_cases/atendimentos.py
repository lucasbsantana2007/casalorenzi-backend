"""Atendimento: chamados dos clientes. A equipe (administrador e lojista) trata pelo painel.

O cliente logado (conta com CPF) abre e responde os próprios chamados (`abrir_para_cliente`,
`responder_como_cliente`); a equipe também abre em nome dele (`abrir`).
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from src import models as m
from src.entities.atendimento import DESCRICAO_MINIMA, EM_ABERTO, protocolo, status_apos_mensagem
from src.entities.cliente import cpf_do_id
from src.entities.marca import MARCA_PADRAO, MARCAS
from src.entities.papeis import EQUIPE
from src.repositories import (
    atendimento_repository,
    cadastro_repository,
    cliente_repository,
    pedido_repository,
    sessao,
    usuario_repository,
)
from src.schemas.atendimentos import AnexoEntrada
from src.use_cases import anexos
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos, NaoEncontrado
from src.utils.texto import corresponde


def carregar(db: Session, atendimento_id: int) -> m.Atendimento:
    """O acesso (módulo atendimento) é conferido na rota."""
    atendimento = atendimento_repository.obter(db, atendimento_id)
    if atendimento is None:
        raise NaoEncontrado("Atendimento não encontrado.")
    return atendimento


def registrar_evento(db: Session, atendimento: m.Atendimento, conteudo: str) -> None:
    """Mensagem automática do SISTEMA no histórico do atendimento (sem confirmar)."""
    sessao.adicionar(
        db, m.Mensagem(atendimento=atendimento, autor_id=None, autor_tipo="SISTEMA", conteudo=conteudo, enviado_em=agora())
    )


def _nova_mensagem(
    db: Session,
    atendimento: m.Atendimento,
    *,
    autor_tipo: str,
    autor_id: int | None,
    conteudo: str,
    anexo: AnexoEntrada | None,
    quando: datetime,
) -> m.Mensagem:
    """Mensagem de texto, com imagem opcional. Só com anexo, o texto pode ficar vazio."""
    conteudo = conteudo.strip()
    arquivo = anexos.preparar(anexo.nome, anexo.tipo, anexo.conteudo_base64) if anexo else None
    if not conteudo and arquivo is None:
        raise DadosInvalidos("A mensagem não pode ficar vazia.")
    mensagem = m.Mensagem(
        atendimento=atendimento, autor_id=autor_id, autor_tipo=autor_tipo, conteudo=conteudo, enviado_em=quando, anexo=arquivo
    )
    sessao.adicionar(db, mensagem)
    return mensagem


def listar(
    db: Session,
    *,
    busca: str | None = None,
    tipo_solicitacao_id: int | None = None,
    responsavel_id: str | None = None,
    loja_id: int | None = None,
) -> list[m.Atendimento]:
    """responsavel_id='nenhum' lista os atendimentos sem responsável."""
    if responsavel_id and responsavel_id != "nenhum" and not responsavel_id.isdigit():
        raise DadosInvalidos("Responsável inválido.")
    atendimentos = atendimento_repository.listar(
        db,
        tipo_solicitacao_id=tipo_solicitacao_id,
        loja_id=loja_id,
        sem_responsavel=responsavel_id == "nenhum",
        responsavel_id=int(responsavel_id) if responsavel_id and responsavel_id.isdigit() else None,
    )
    return [a for a in atendimentos if corresponde(busca, a.protocolo, *_textos_do_cliente(a), a.tipo_solicitacao.titulo)]


def _textos_do_cliente(atendimento: m.Atendimento) -> tuple[str, ...]:
    """Nome e e-mail do cliente para a busca; sem cliente identificado (WhatsApp, Instagram), o contato."""
    if atendimento.cliente is None:
        return atendimento.contato_nome or "", atendimento.contato or ""
    return atendimento.cliente.nome, atendimento.cliente.email or ""


def abrir_para_cliente(
    db: Session,
    cliente: m.Cliente,
    *,
    tipo_solicitacao_id: int | None,
    pedido_id: int | None,
    descricao: str,
    anexo: AnexoEntrada | None = None,
    aberto_por: m.Usuario | None = None,
) -> m.Atendimento:
    """A descrição entra como mensagem do CLIENTE. aberto_por: membro da equipe que registrou o pedido."""
    tipo = cadastro_repository.tipo_solicitacao(db, tipo_solicitacao_id) if tipo_solicitacao_id else None
    if tipo is None or not tipo.ativo:
        raise DadosInvalidos("Selecione o tipo de solicitação.")
    if tipo.exige_venda and not pedido_id:
        raise DadosInvalidos("Este tipo de solicitação exige o número do pedido.")
    if len(descricao.strip()) < DESCRICAO_MINIMA:
        raise DadosInvalidos("Descreva sua solicitação com pelo menos 10 caracteres.")

    pedido = None
    if pedido_id:
        pedido = pedido_repository.obter(db, pedido_id)
        if pedido is None or pedido.cliente_id != cliente.id:
            raise DadosInvalidos("Pedido não encontrado entre os pedidos do cliente.")

    # Marca do chamado: a do pedido; sem pedido, a de quem abriu pela equipe (o grupo e o próprio
    # cliente abrem na Casa Lorenzi, a loja do site). Sem pedido na Vulto: atendimento central (sem loja)
    marca = pedido.loja.marca if pedido else (aberto_por.marca if aberto_por and aberto_por.marca in MARCAS else MARCA_PADRAO)
    momento = agora()
    atendimento = m.Atendimento(
        marca=marca,
        protocolo=f"TMP-{uuid.uuid4().hex[:12]}",  # trocado pelo protocolo definitivo assim que o id existe
        cliente_id=cliente.id,
        tipo_solicitacao_id=tipo.id,
        status="ABERTO",
        pedido_id=pedido.id if pedido else None,
        loja_id=pedido.loja_id if pedido else ((cliente.loja_preferida_id or 1) if marca == MARCA_PADRAO else None),
        criado_em=momento,
        atualizado_em=momento,
    )
    sessao.adicionar(db, atendimento)
    sessao.gerar_ids(db)
    atendimento.protocolo = protocolo(atendimento.id)
    _nova_mensagem(db, atendimento, autor_tipo="CLIENTE", autor_id=None, conteudo=descricao, anexo=anexo, quando=momento)
    if aberto_por is not None:
        registrar_evento(db, atendimento, f"Aberto por {aberto_por.nome} em nome do cliente.")
    sessao.confirmar(db, atendimento)
    return atendimento


def abrir_pelo_whatsapp(
    db: Session, cliente: m.Cliente | None, *, marca: str | None, tipo_solicitacao_id: int, descricao: str
) -> m.Atendimento:
    """Chamado que o cliente leva do assistente do site para o WhatsApp do atendimento (decisão 81). Com login,
    já fica ligado à conta; sem login, nasce sem cliente, como os atendimentos de WhatsApp da Vulto, e a equipe
    o encontra pelo protocolo que vai escrito na mensagem. Sem loja: é o atendimento central da marca."""
    tipo = cadastro_repository.tipo_solicitacao(db, tipo_solicitacao_id)
    if tipo is None or not tipo.ativo or tipo.exige_venda:
        raise DadosInvalidos("Tipo de solicitação inválido para o WhatsApp.")
    momento = agora()
    atendimento = m.Atendimento(
        marca=marca if marca in MARCAS else MARCA_PADRAO,
        protocolo=f"TMP-{uuid.uuid4().hex[:12]}",  # trocado pelo protocolo definitivo assim que o id existe
        cliente_id=cliente.id if cliente else None,
        contato=None if cliente else "WhatsApp",
        contato_nome=None if cliente else "Visitante do site",
        canal="WHATSAPP",
        tipo_solicitacao_id=tipo.id,
        status="ABERTO",
        criado_em=momento,
        atualizado_em=momento,
    )
    sessao.adicionar(db, atendimento)
    sessao.gerar_ids(db)
    atendimento.protocolo = protocolo(atendimento.id)
    _nova_mensagem(db, atendimento, autor_tipo="CLIENTE", autor_id=None, conteudo=descricao, anexo=None, quando=momento)
    sessao.confirmar(db, atendimento)
    return atendimento


def abrir(
    db: Session,
    usuario: m.Usuario,
    *,
    cliente_id: str | int | None,
    tipo_solicitacao_id: int | None,
    pedido_id: int | None,
    descricao: str,
    anexo: AnexoEntrada | None = None,
) -> m.Atendimento:
    """A equipe de atendimento abre o chamado para um cliente (cliente_id = CPF, o id público)."""
    cpf = cpf_do_id(cliente_id)
    cliente = cliente_repository.por_cpf(db, cpf) if cpf else None
    if cliente is None:
        raise DadosInvalidos("Informe um cliente válido.")
    return abrir_para_cliente(
        db,
        cliente,
        tipo_solicitacao_id=tipo_solicitacao_id,
        pedido_id=pedido_id,
        descricao=descricao,
        anexo=anexo,
        aberto_por=usuario,
    )


def atualizar(
    db: Session,
    atendimento_id: int,
    *,
    status: str | None,
    responsavel_id: int | None,
    mudar_responsavel: bool,
) -> m.Atendimento:
    """mudar_responsavel=False mantém o responsável atual (campo omitido no corpo)."""
    atendimento = carregar(db, atendimento_id)
    if mudar_responsavel and responsavel_id != atendimento.responsavel_id:
        responsavel = None
        if responsavel_id is not None:
            responsavel = usuario_repository.por_id(db, responsavel_id)
            if responsavel is None or not responsavel.ativo or responsavel.papel not in EQUIPE:
                raise DadosInvalidos("Responsável inválido.")
        atendimento.responsavel_id = responsavel_id
        registrar_evento(
            db, atendimento, f"Atendimento atribuído a {responsavel.nome}." if responsavel else "Responsável removido."
        )
    if status and status != atendimento.status:
        atendimento.status = status
        registrar_evento(db, atendimento, f'Status alterado para "{status.replace("_", " ").lower()}".')
    atendimento.atualizado_em = agora()
    sessao.confirmar(db, atendimento)
    return atendimento


def enviar_mensagem(
    db: Session, atendimento_id: int, usuario: m.Usuario, conteudo: str, anexo: AnexoEntrada | None = None
) -> m.Atendimento:
    """Resposta da equipe. O autor vem do token, nunca do corpo da requisição."""
    atendimento = carregar(db, atendimento_id)
    momento = agora()
    _nova_mensagem(db, atendimento, autor_tipo="ATENDENTE", autor_id=usuario.id, conteudo=conteudo, anexo=anexo, quando=momento)
    # Quem da equipe responde um caso em aberto sem responsável passa a ser o responsável
    if atendimento.status in EM_ABERTO and atendimento.responsavel_id is None:
        atendimento.responsavel_id = usuario.id
    atendimento.status = status_apos_mensagem(atendimento.status, "ATENDENTE")
    atendimento.atualizado_em = momento
    sessao.confirmar(db, atendimento)
    return atendimento


def responder_como_cliente(
    db: Session, atendimento_id: int, cliente: m.Cliente, conteudo: str, anexo: AnexoEntrada | None = None
) -> m.Atendimento:
    """Resposta do cliente logado. Chamado de outro cliente aparece como inexistente."""
    atendimento = atendimento_repository.obter(db, atendimento_id)
    if atendimento is None or atendimento.cliente_id != cliente.id:
        raise NaoEncontrado("Solicitação não encontrada.")
    if atendimento.status == "CONCLUIDO":
        raise Conflito("Esta solicitação foi encerrada. Abra um novo chamado se precisar.")
    momento = agora()
    _nova_mensagem(db, atendimento, autor_tipo="CLIENTE", autor_id=None, conteudo=conteudo, anexo=anexo, quando=momento)
    atendimento.status = status_apos_mensagem(atendimento.status, "CLIENTE")
    atendimento.atualizado_em = momento
    sessao.confirmar(db, atendimento)
    return atendimento


def mensagem_do_whatsapp(db: Session, atendimento: m.Atendimento, conteudo: str) -> m.Atendimento:
    """Mensagem que o cliente mandou pelo WhatsApp depois de pedir a equipe (decisão 114): entra no mesmo chamado,
    para a equipe ler no painel. O telefone já está no chamado; sem login, não há conta a conferir."""
    momento = agora()
    _nova_mensagem(db, atendimento, autor_tipo="CLIENTE", autor_id=None, conteudo=conteudo, anexo=None, quando=momento)
    atendimento.status = status_apos_mensagem(atendimento.status, "CLIENTE")
    atendimento.atualizado_em = momento
    sessao.confirmar(db, atendimento)
    return atendimento


def totais_do_cliente(db: Session, cliente_id: int | None) -> tuple[int, int]:
    """(pedidos, atendimentos) do cliente, mostrados no detalhe do atendimento (zero sem cliente identificado)."""
    if cliente_id is None:
        return 0, 0
    return pedido_repository.contar_do_cliente(db, cliente_id), atendimento_repository.contar_do_cliente(db, cliente_id)
