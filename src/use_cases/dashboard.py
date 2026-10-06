"""Indicadores da tela inicial do painel."""

from datetime import timedelta

from sqlalchemy.orm import Session

from src import models as m
from src.entities.estoque import status_estoque
from src.entities.papeis import LOJISTA
from src.repositories import (
    atendimento_repository,
    cadastro_repository,
    estoque_repository,
    produto_repository,
    transferencia_repository,
)
from src.schemas.atendimentos import atendimento_saida
from src.schemas.comum import loja_saida
from src.schemas.estoque import movimentacao_saida
from src.utils.datas import agora

ALERTAS_DE_RUPTURA = 4
MOVIMENTACOES_RECENTES = 8
ATENDIMENTOS_RECENTES = 5


def resumo(db: Session, usuario: m.Usuario, loja_id: int | None) -> dict:
    """Lojistas veem sempre a própria loja, qualquer que seja o filtro pedido."""
    if usuario.papel == LOJISTA and usuario.loja_id:
        loja_id = usuario.loja_id

    estoques = estoque_repository.listar(db, loja_id=loja_id)
    ativos = [e for e in estoques if e.variacao.produto.ativo]
    status = {e.id: status_estoque(e.quantidade, e.quantidade_min) for e in ativos}
    abertos = atendimento_repository.em_aberto(db, loja_id)
    em_transito = sorted(transferencia_repository.listar(db, status="EM_TRANSITO", loja_id=loja_id), key=lambda t: t.id)
    pendentes = transferencia_repository.listar(db, status="SOLICITADA", loja_id=loja_id)
    momento = agora()

    indicadores = {
        "estoqueTotal": sum(e.quantidade for e in ativos),
        "produtosAtivos": len(produto_repository.listar(db, ativo=True)),
        "variacoesAtivas": len({e.variacao_id for e in ativos}),
        "itensEstoqueBaixo": sum(1 for e in ativos if status[e.id] == "BAIXO"),
        "itensSemEstoque": sum(1 for e in ativos if status[e.id] == "SEM_ESTOQUE"),
        "atendimentosAbertos": len(abertos),
        "atendimentosSemResponsavel": sum(1 for a in abertos if a.responsavel_id is None),
        "transferenciasEmTransito": len(em_transito),
        "transferenciasPendentes": len(pendentes),
        "vendas7d": estoque_repository.pecas_vendidas_desde(db, momento - timedelta(days=7), loja_id),
    }

    lojas = [loja for loja in cadastro_repository.lojas(db) if not loja_id or loja.id == loja_id]
    resumo_por_loja = []
    for loja in lojas:
        itens = [e for e in ativos if e.loja_id == loja.id]
        resumo_por_loja.append(
            {
                "loja": loja_saida(loja),
                "pecas": sum(e.quantidade for e in itens),
                "valorEstoque": sum(e.quantidade * float(e.variacao.produto.preco_base) for e in itens),
                "itensBaixos": sum(1 for e in itens if status[e.id] != "NORMAL"),
                "atendimentosAbertos": sum(1 for a in abertos if a.loja_id == loja.id),
            }
        )

    alertas = []
    for e in [e for e in ativos if status[e.id] == "SEM_ESTOQUE"][:ALERTAS_DE_RUPTURA]:
        v = e.variacao
        alertas.append(
            {
                "nivel": "danger",
                "titulo": f"Ruptura: {v.produto.nome}",
                "descricao": f"{v.sku} · {v.cor} {v.tamanho} zerado em {e.loja.nome}",
                "link": f"/estoque/{e.id}",
            }
        )
    for a in abertos:
        if a.responsavel_id is None:
            alertas.append(
                {
                    "nivel": "warning",
                    "titulo": f"Atendimento sem responsável · {a.protocolo}",
                    "descricao": f"{a.cliente.nome} aguarda retorno",
                    "link": f"/atendimento/{a.id}",
                }
            )
    for t in em_transito:
        if t.enviado_em and momento - t.enviado_em > timedelta(days=2):
            alertas.append(
                {
                    "nivel": "info",
                    "titulo": f"Transferência {t.codigo} em trânsito há mais de 2 dias",
                    "descricao": "Confirme o recebimento na loja de destino",
                    "link": "/transferencias",
                }
            )

    recentes = sorted(abertos, key=lambda a: a.atualizado_em, reverse=True)[:ATENDIMENTOS_RECENTES]
    ultimas = atendimento_repository.ultimas_mensagens(db, [a.id for a in recentes])
    return {
        "indicadores": indicadores,
        "resumoPorLoja": resumo_por_loja,
        "alertas": alertas,
        "movimentacoesRecentes": [
            movimentacao_saida(mov)
            for mov in estoque_repository.listar_movimentacoes(db, loja_id=loja_id, limite=MOVIMENTACOES_RECENTES)
        ],
        "atendimentosRecentes": [atendimento_saida(a, ultimas.get(a.id)) for a in recentes],
    }
