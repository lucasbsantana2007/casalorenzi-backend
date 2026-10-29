import base64
from datetime import datetime
from typing import Literal

from src import models as m
from src.config import settings
from src.entities.atendimento import atrasado
from src.schemas.clientes import cliente_saida
from src.schemas.comum import AnexoEntrada, Entrada, loja_saida, usuario_resumo  # noqa: F401 (AnexoEntrada é reexportada)
from src.schemas.pedidos import pedido_saida
from src.utils.datas import agora, ms

StatusAtendimento = Literal["ABERTO", "EM_ANDAMENTO", "AGUARDANDO_CLIENTE", "CONCLUIDO"]


class AtendimentoAtualizacao(Entrada):
    status: StatusAtendimento | None = None
    # Enviar null remove o responsável; omitir o campo mantém o atual
    responsavel_id: int | None = None


class MensagemEntrada(Entrada):
    conteudo: str = ""
    anexo: AnexoEntrada | None = None
    # Ignorados: autor e tipo vêm do token
    autor_id: int | None = None
    autor_tipo: Literal["ATENDENTE", "CLIENTE"] | None = None


class SolicitacaoEntrada(Entrada):
    """Cliente logado abre para si (clienteId ignorado); a equipe abre em nome de um cliente."""

    # CPF do cliente (id público); a equipe informa ao abrir em nome dele
    cliente_id: str | int | None = None
    tipo_solicitacao_id: int | None = None
    pedido_id: int | None = None
    descricao: str = ""
    anexo: AnexoEntrada | None = None


def tipo_solicitacao_saida(tipo: m.TipoSolicitacao) -> dict:
    return {
        "id": tipo.id,
        "titulo": tipo.titulo,
        "categoria": tipo.categoria,
        "descricao": tipo.descricao,
        "exigeVenda": tipo.exige_venda,
        "ordemExibicao": tipo.ordem_exibicao,
        "ativo": tipo.ativo,
    }


def _cliente_resumo(a: m.Atendimento) -> dict:
    """Sem cliente identificado (WhatsApp, Instagram da Vulto): o nome e o contato que ele deu."""
    if a.cliente is None:
        return {"id": None, "nome": a.contato_nome or a.contato}
    return {"id": a.cliente.cpf, "nome": a.cliente.nome}


def atendimento_saida(a: m.Atendimento, ultima: m.Mensagem | None, espera: datetime | None = None) -> dict:
    """espera: desde quando o cliente espera a equipe num chamado aberto pela Lúcia (decisão 122)."""
    cliente_id = a.cliente.cpf if a.cliente else None
    return {
        "id": a.id,
        "protocolo": a.protocolo,
        "clienteId": cliente_id,
        # Nome antigo, mantido enquanto o frontend usa solicitanteId
        "solicitanteId": cliente_id,
        "responsavelId": a.responsavel_id,
        "tipoSolicitacaoId": a.tipo_solicitacao_id,
        "status": a.status,
        "pedidoId": a.pedido_id,
        "lojaId": a.loja_id,
        "marca": a.marca,
        "canal": a.canal,
        "contato": a.contato,
        "contatoNome": a.contato_nome,
        "pedidoCitado": a.pedido_citado,
        "criadoEm": ms(a.criado_em),
        "atualizadoEm": ms(a.atualizado_em),
        "tipoSolicitacao": tipo_solicitacao_saida(a.tipo_solicitacao),
        "cliente": _cliente_resumo(a),
        "responsavel": usuario_resumo(a.responsavel),
        "loja": loja_saida(a.loja),
        "ultimaMensagem": (
            {"autorTipo": ultima.autor_tipo, "conteudo": ultima.conteudo, "enviadoEm": ms(ultima.enviado_em)} if ultima else None
        ),
        "aguardandoEquipeDesde": ms(espera) if espera else None,
        "atrasado": atrasado(espera, agora(), settings.ATENDIMENTO_ATRASO_MINUTOS),
    }


def anexo_saida(anexo: m.Anexo | None) -> dict | None:
    """url é um data URL (data:<tipo>;base64,...), pronto para <img src>."""
    if anexo is None:
        return None
    return {
        "id": anexo.id,
        "nome": anexo.nome,
        "tipo": anexo.tipo,
        "url": f"data:{anexo.tipo};base64,{base64.b64encode(anexo.dados).decode()}",
    }


def mensagem_saida(msg: m.Mensagem) -> dict:
    return {
        "id": msg.id,
        "atendimentoId": msg.atendimento_id,
        "autorId": msg.autor_id,
        "autorTipo": msg.autor_tipo,
        "conteudo": msg.conteudo,
        "enviadoEm": ms(msg.enviado_em),
        "autor": usuario_resumo(msg.autor),
        # Quem escreveu fora da plataforma (atendente da ferramenta da Vulto); nulo nas mensagens daqui
        "autorNome": msg.autor_nome,
        "anexo": anexo_saida(msg.anexo),
    }


def atendimento_detalhado_saida(
    a: m.Atendimento, total_pedidos: int, total_atendimentos: int, espera: datetime | None = None
) -> dict:
    mensagens = a.mensagens
    cliente = cliente_saida(a.cliente) or _cliente_resumo(a)
    return {
        **atendimento_saida(a, mensagens[-1] if mensagens else None, espera),
        "cliente": {**cliente, "totalPedidos": total_pedidos, "totalAtendimentos": total_atendimentos},
        "pedido": pedido_saida(a.pedido),
        "mensagens": [mensagem_saida(msg) for msg in mensagens],
    }
