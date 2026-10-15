import base64
from typing import Literal

from src import models as m
from src.schemas.clientes import cliente_saida, pedido_resumo
from src.schemas.comum import AnexoEntrada, Entrada, loja_saida, usuario_resumo  # noqa: F401 (AnexoEntrada é reexportada)
from src.schemas.pedidos import pedido_saida
from src.utils.datas import ms

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


def _nome_do_cliente(a: m.Atendimento) -> str | None:
    """Sem cliente identificado (atendimento da Vulto), vale o nome que a pessoa deu no canal, ou o contato."""
    return a.cliente.nome if a.cliente else a.contato_nome or a.contato


def atendimento_saida(a: m.Atendimento, ultima: m.Mensagem | None) -> dict:
    cpf = a.cliente.cpf if a.cliente else None
    return {
        "id": a.id,
        "protocolo": a.protocolo,
        "clienteId": cpf,
        # Nome antigo, mantido enquanto o frontend usa solicitanteId
        "solicitanteId": cpf,
        "responsavelId": a.responsavel_id,
        "tipoSolicitacaoId": a.tipo_solicitacao_id,
        "status": a.status,
        "pedidoId": a.pedido_id,
        "lojaId": a.loja_id,
        "marca": a.loja.marca,
        "canal": a.canal,
        "contato": a.contato,
        "contatoNome": a.contato_nome,
        "criadoEm": ms(a.criado_em),
        "atualizadoEm": ms(a.atualizado_em),
        "tipoSolicitacao": tipo_solicitacao_saida(a.tipo_solicitacao),
        "cliente": {"id": cpf, "nome": _nome_do_cliente(a)},
        "responsavel": usuario_resumo(a.responsavel),
        "loja": loja_saida(a.loja),
        "ultimaMensagem": (
            {"autorTipo": ultima.autor_tipo, "conteudo": ultima.conteudo, "enviadoEm": ms(ultima.enviado_em)} if ultima else None
        ),
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
        "anexo": anexo_saida(msg.anexo),
    }


def _cliente_detalhado(a: m.Atendimento) -> dict:
    """Os campos do cliente; sem cliente identificado, os do contato (e-mail ou telefone, quando é um deles)."""
    if a.cliente is not None:
        return cliente_saida(a.cliente)
    contato = a.contato or ""
    return {
        **dict.fromkeys(("id", "email", "telefone", "clienteDesde", "lojaPreferidaId", "cpf", "aceitaMarketing")),
        "nome": _nome_do_cliente(a),
        "email": contato if "@" in contato and not contato.startswith("@") else None,
        "telefone": contato if contato.startswith("+") else None,
        "temConta": False,
        "excluido": False,
        "identificado": False,
    }


def historico_resumo(a: m.Atendimento) -> dict:
    return {
        "id": a.id,
        "protocolo": a.protocolo,
        "status": a.status,
        "canal": a.canal,
        "tipoSolicitacao": a.tipo_solicitacao.titulo,
        "pedido": a.pedido.numero if a.pedido else None,
        "criadoEm": ms(a.criado_em),
    }


def atendimento_detalhado_saida(
    a: m.Atendimento,
    total_pedidos: int,
    total_atendimentos: int,
    outros: list[m.Atendimento] = (),
    pedidos: list[m.Pedido] = (),
) -> dict:
    """outrosAtendimentos: os outros chamados da mesma pessoa (pelo cliente ou pelo contato);
    pedidosDoCliente: os pedidos dela nas duas marcas, mais recentes primeiro."""
    mensagens = a.mensagens
    return {
        **atendimento_saida(a, mensagens[-1] if mensagens else None),
        "cliente": {**_cliente_detalhado(a), "totalPedidos": total_pedidos, "totalAtendimentos": total_atendimentos},
        "pedido": pedido_saida(a.pedido),
        "mensagens": [mensagem_saida(msg) for msg in mensagens],
        "outrosAtendimentos": [historico_resumo(o) for o in outros],
        "pedidosDoCliente": [pedido_resumo(p) for p in pedidos],
    }
