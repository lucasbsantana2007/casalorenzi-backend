"""Conversão dos modelos para o formato JSON que o frontend espera.

Os formatos seguem exatamente as "projeções" de src/services/mock/*.js do
frontend (camelCase, datas em milissegundos, objetos relacionados embutidos).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.utils import ms, status_estoque


def loja_view(loja: m.Loja | None) -> dict | None:
    if loja is None:
        return None
    return {"id": loja.id, "nome": loja.nome, "cidade": loja.cidade, "uf": loja.uf}


def usuario_resumo(usuario: m.Usuario | None) -> dict | None:
    if usuario is None:
        return None
    return {"id": usuario.id, "nome": usuario.nome, "papel": usuario.papel}


def usuario_view(usuario: m.Usuario) -> dict:
    return {
        "id": usuario.id,
        "nome": usuario.nome,
        "email": usuario.email,
        "papel": usuario.papel,
        "lojaId": usuario.loja_id,
    }


def produto_resumo(produto: m.Produto) -> dict:
    return {
        "id": produto.id,
        "nome": produto.nome,
        "categoria": produto.categoria.nome,
        "precoBase": float(produto.preco_base),
        "ativo": produto.ativo,
    }


def variacao_base(variacao: m.Variacao) -> dict:
    return {
        "id": variacao.id,
        "produtoId": variacao.produto_id,
        "sku": variacao.sku,
        "tamanho": variacao.tamanho,
        "cor": variacao.cor,
    }


def variacao_view(variacao: m.Variacao) -> dict:
    """Variação com o resumo do produto embutido."""
    return {**variacao_base(variacao), "produto": produto_resumo(variacao.produto)}


def estoque_view(estoque: m.Estoque) -> dict:
    return {
        "id": estoque.id,
        "lojaId": estoque.loja_id,
        "variacaoId": estoque.variacao_id,
        "quantidade": estoque.quantidade,
        "quantidadeMin": estoque.quantidade_min,
        "atualizadoEm": ms(estoque.atualizado_em),
        "status": status_estoque(estoque.quantidade, estoque.quantidade_min),
        "loja": loja_view(estoque.loja),
        "variacao": variacao_base(estoque.variacao),
        "produto": produto_resumo(estoque.variacao.produto),
    }


def movimentacao_view(mov: m.Movimentacao) -> dict:
    estoque = mov.estoque
    return {
        "id": mov.id,
        "estoqueId": mov.estoque_id,
        "tipo": mov.tipo,
        "quantidade": mov.quantidade,
        "origem": mov.origem,
        "usuarioId": mov.usuario_id,
        "transferenciaId": mov.transferencia_id,
        "criadoEm": ms(mov.criado_em),
        "saldoResultante": mov.saldo_resultante,
        "loja": loja_view(estoque.loja),
        "variacao": variacao_base(estoque.variacao),
        "produto": produto_resumo(estoque.variacao.produto),
        "usuario": usuario_resumo(mov.usuario),
    }


def estoque_por_variacao(db: Session, variacao_ids: list[int]) -> dict[int, int]:
    if not variacao_ids:
        return {}
    linhas = db.execute(
        select(m.Estoque.variacao_id, func.coalesce(func.sum(m.Estoque.quantidade), 0))
        .where(m.Estoque.variacao_id.in_(variacao_ids))
        .group_by(m.Estoque.variacao_id)
    )
    return {variacao_id: int(total) for variacao_id, total in linhas}


def produto_view(produto: m.Produto, totais: dict[int, int]) -> dict:
    variacoes = [{**variacao_base(v), "estoqueTotal": totais.get(v.id, 0)} for v in produto.variacoes]
    return {
        "id": produto.id,
        "nome": produto.nome,
        "categoria": produto.categoria.nome,
        "precoBase": float(produto.preco_base),
        "genero": produto.genero,
        "estacao": produto.estacao,
        "ativo": produto.ativo,
        "variacoes": variacoes,
        "estoqueTotal": sum(v["estoqueTotal"] for v in variacoes),
    }


def transferencia_view(t: m.Transferencia) -> dict:
    return {
        "id": t.id,
        "codigo": t.codigo,
        "variacaoId": t.variacao_id,
        "lojaOrigemId": t.loja_origem_id,
        "lojaDestinoId": t.loja_destino_id,
        "quantidade": t.quantidade,
        "status": t.status,
        "solicitanteId": t.solicitante_id,
        "responsavelId": t.responsavel_id,
        "criadoEm": ms(t.criado_em),
        "enviadoEm": ms(t.enviado_em),
        "recebidoEm": ms(t.recebido_em),
        "observacao": t.observacao or "",
        "variacao": variacao_base(t.variacao),
        "produto": produto_resumo(t.variacao.produto),
        "lojaOrigem": loja_view(t.loja_origem),
        "lojaDestino": loja_view(t.loja_destino),
        "solicitante": usuario_resumo(t.solicitante),
        "responsavel": usuario_resumo(t.responsavel),
    }


def pedido_view(pedido: m.Pedido | None) -> dict | None:
    if pedido is None:
        return None
    return {
        "id": pedido.id,
        "numero": pedido.numero,
        "clienteId": pedido.cliente_id,
        "lojaId": pedido.loja_id,
        "canal": pedido.canal,
        "status": pedido.status,
        "criadoEm": ms(pedido.criado_em),
        "codigoRastreio": pedido.codigo_rastreio,
        "total": float(pedido.total),
        "loja": loja_view(pedido.loja),
        "itens": [
            {
                "variacaoId": item.variacao_id,
                "quantidade": item.quantidade,
                "precoUnitario": float(item.preco_unitario),
                "variacao": variacao_view(item.variacao),
            }
            for item in pedido.itens
        ],
    }


def tipo_solicitacao_view(tipo: m.TipoSolicitacao) -> dict:
    return {
        "id": tipo.id,
        "titulo": tipo.titulo,
        "categoria": tipo.categoria,
        "descricao": tipo.descricao,
        "exigeVenda": tipo.exige_venda,
        "ordemExibicao": tipo.ordem_exibicao,
        "ativo": tipo.ativo,
    }


def ultimas_mensagens(db: Session, atendimento_ids: list[int]) -> dict[int, m.Mensagem]:
    """Última mensagem de cada atendimento, numa única consulta."""
    if not atendimento_ids:
        return {}
    ordem = (
        func.row_number()
        .over(partition_by=m.Mensagem.atendimento_id, order_by=(m.Mensagem.enviado_em.desc(), m.Mensagem.id.desc()))
        .label("ordem")
    )
    sub = (
        select(m.Mensagem.id, ordem).where(m.Mensagem.atendimento_id.in_(atendimento_ids)).subquery()
    )
    mensagens = db.scalars(select(m.Mensagem).join(sub, sub.c.id == m.Mensagem.id).where(sub.c.ordem == 1))
    return {msg.atendimento_id: msg for msg in mensagens}


def atendimento_view(a: m.Atendimento, ultima: m.Mensagem | None) -> dict:
    return {
        "id": a.id,
        "protocolo": a.protocolo,
        "solicitanteId": a.solicitante_id,
        "responsavelId": a.responsavel_id,
        "tipoSolicitacaoId": a.tipo_solicitacao_id,
        "status": a.status,
        "pedidoId": a.pedido_id,
        "lojaId": a.loja_id,
        "criadoEm": ms(a.criado_em),
        "atualizadoEm": ms(a.atualizado_em),
        "tipoSolicitacao": tipo_solicitacao_view(a.tipo_solicitacao),
        "cliente": {"id": a.solicitante_id, "nome": a.solicitante.nome},
        "responsavel": usuario_resumo(a.responsavel),
        "loja": loja_view(a.loja),
        "ultimaMensagem": (
            {"autorTipo": ultima.autor_tipo, "conteudo": ultima.conteudo, "enviadoEm": ms(ultima.enviado_em)}
            if ultima
            else None
        ),
    }


def atendimentos_view(db: Session, atendimentos: list[m.Atendimento]) -> list[dict]:
    ultimas = ultimas_mensagens(db, [a.id for a in atendimentos])
    return [atendimento_view(a, ultimas.get(a.id)) for a in atendimentos]


def atendimento_detalhado(db: Session, a: m.Atendimento) -> dict:
    mensagens = a.mensagens
    cliente = a.solicitante
    total_pedidos = db.scalar(select(func.count()).where(m.Pedido.cliente_id == cliente.id))
    total_atendimentos = db.scalar(select(func.count()).where(m.Atendimento.solicitante_id == cliente.id))
    return {
        **atendimento_view(a, mensagens[-1] if mensagens else None),
        "cliente": {
            "id": cliente.id,
            "nome": cliente.nome,
            "email": cliente.email,
            "telefone": cliente.telefone,
            "clienteDesde": cliente.cliente_desde.isoformat() if cliente.cliente_desde else None,
            "totalPedidos": total_pedidos,
            "totalAtendimentos": total_atendimentos,
        },
        "pedido": pedido_view(a.pedido),
        "mensagens": [
            {
                "id": msg.id,
                "atendimentoId": msg.atendimento_id,
                "autorId": msg.autor_id,
                "autorTipo": msg.autor_tipo,
                "conteudo": msg.conteudo,
                "enviadoEm": ms(msg.enviado_em),
                "autor": usuario_resumo(msg.autor),
            }
            for msg in mensagens
        ],
    }
