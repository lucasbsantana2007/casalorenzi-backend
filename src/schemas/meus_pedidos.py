"""Corpos e respostas da área "Meus pedidos" (cliente identificado por e-mail + PIN)."""

from src import models as m
from src.schemas.atendimentos import AnexoEntrada, anexo_saida
from src.schemas.comum import Entrada
from src.utils.datas import ms


class IdentificacaoEntrada(Entrada):
    """POST para o PIN não aparecer na URL (nem em logs de acesso e histórico do navegador)."""

    email: str = ""
    pin: str | int | None = None


class EsqueciPinEntrada(Entrada):
    email: str = ""


class RedefinirPinEntrada(Entrada):
    token: str = ""
    pin: str | int | None = None
    pin_confirmacao: str | int | None = None


class SolicitacaoClienteEntrada(IdentificacaoEntrada):
    numero: str = ""
    tipo_solicitacao_id: int | None = None
    descricao: str = ""
    anexo: AnexoEntrada | None = None


class RespostaClienteEntrada(IdentificacaoEntrada):
    conteudo: str = ""


def _autor(msg: m.Mensagem) -> dict | None:
    """Da equipe, o cliente vê só o primeiro nome."""
    if msg.autor_tipo != "ATENDENTE":
        return None
    return {"nome": msg.autor.nome.split()[0] if msg.autor else "Equipe"}


def solicitacao_publica_saida(a: m.Atendimento) -> dict:
    """Chamado visto pelo cliente: sem responsável nem loja."""
    return {
        "id": a.id,
        "protocolo": a.protocolo,
        "status": a.status,
        "tipo": a.tipo_solicitacao.titulo,
        "pedidoNumero": a.pedido.numero if a.pedido else None,
        "criadoEm": ms(a.criado_em),
        "atualizadoEm": ms(a.atualizado_em),
        "mensagens": [
            {
                "id": msg.id,
                "autorTipo": msg.autor_tipo,
                "conteudo": msg.conteudo,
                "anexo": anexo_saida(msg.anexo),
                "enviadoEm": ms(msg.enviado_em),
                "autor": _autor(msg),
            }
            for msg in a.mensagens
        ],
    }
