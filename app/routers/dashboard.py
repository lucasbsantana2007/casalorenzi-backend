from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select, true
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ATENDIMENTO_ABERTO, Atendimento, Estoque, Loja, Movimentacao, Produto, Transferencia, Usuario
from app.security import exigir_modulo
from app.utils import agora, status_estoque
from app.views import atendimentos_view, loja_view, movimentacao_view

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/resumo")
def obter_resumo(
    lojaId: int | None = None,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_modulo("dashboard")),
):
    """Indicadores da tela inicial do painel. Lojistas veem sempre a própria loja."""
    if usuario.papel == "LOJISTA" and usuario.loja_id:
        lojaId = usuario.loja_id

    def da_loja(coluna):
        return coluna == lojaId if lojaId else true()

    estoques = db.scalars(select(Estoque).where(da_loja(Estoque.loja_id)).order_by(Estoque.id)).all()
    ativos = [e for e in estoques if e.variacao.produto.ativo]
    status = {e.id: status_estoque(e.quantidade, e.quantidade_min) for e in ativos}

    atendimentos_abertos = db.scalars(
        select(Atendimento)
        .where(Atendimento.status.in_(ATENDIMENTO_ABERTO), da_loja(Atendimento.loja_id))
        .order_by(Atendimento.id)
    ).all()

    def transferencias(status_transf: str):
        filtro_loja = (
            or_(Transferencia.loja_origem_id == lojaId, Transferencia.loja_destino_id == lojaId) if lojaId else true()
        )
        return db.scalars(
            select(Transferencia).where(Transferencia.status == status_transf, filtro_loja).order_by(Transferencia.id)
        ).all()

    em_transito = transferencias("EM_TRANSITO")
    pendentes = transferencias("SOLICITADA")

    momento = agora()
    vendas_7d = db.scalar(
        select(func.coalesce(func.sum(-Movimentacao.quantidade), 0))
        .join(Movimentacao.estoque)
        .where(
            Movimentacao.tipo == "VENDA",
            Movimentacao.criado_em >= momento - timedelta(days=7),
            da_loja(Estoque.loja_id),
        )
    )

    indicadores = {
        "estoqueTotal": sum(e.quantidade for e in ativos),
        "produtosAtivos": db.scalar(select(func.count()).where(Produto.ativo.is_(True))),
        "variacoesAtivas": len({e.variacao_id for e in ativos}),
        "itensEstoqueBaixo": sum(1 for e in ativos if status[e.id] == "BAIXO"),
        "itensSemEstoque": sum(1 for e in ativos if status[e.id] == "SEM_ESTOQUE"),
        "atendimentosAbertos": len(atendimentos_abertos),
        "atendimentosSemResponsavel": sum(1 for a in atendimentos_abertos if a.responsavel_id is None),
        "transferenciasEmTransito": len(em_transito),
        "transferenciasPendentes": len(pendentes),
        "vendas7d": int(vendas_7d),
    }

    lojas = db.scalars(select(Loja).where(da_loja(Loja.id)).order_by(Loja.id)).all()
    resumo_por_loja = []
    for loja in lojas:
        itens = [e for e in ativos if e.loja_id == loja.id]
        resumo_por_loja.append(
            {
                "loja": loja_view(loja),
                "pecas": sum(e.quantidade for e in itens),
                "valorEstoque": sum(e.quantidade * float(e.variacao.produto.preco_base) for e in itens),
                "itensBaixos": sum(1 for e in itens if status[e.id] != "NORMAL"),
                "atendimentosAbertos": sum(1 for a in atendimentos_abertos if a.loja_id == loja.id),
            }
        )

    alertas = []
    for e in [e for e in ativos if status[e.id] == "SEM_ESTOQUE"][:4]:
        v = e.variacao
        alertas.append(
            {
                "nivel": "danger",
                "titulo": f"Ruptura: {v.produto.nome}",
                "descricao": f"{v.sku} · {v.cor} {v.tamanho} zerado em {e.loja.nome}",
                "link": f"/estoque/{e.id}",
            }
        )
    for a in atendimentos_abertos:
        if a.responsavel_id is None:
            alertas.append(
                {
                    "nivel": "warning",
                    "titulo": f"Atendimento sem responsável · {a.protocolo}",
                    "descricao": f"{a.solicitante.nome} aguarda retorno",
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

    movimentacoes_recentes = db.scalars(
        select(Movimentacao)
        .join(Movimentacao.estoque)
        .where(da_loja(Estoque.loja_id))
        .order_by(Movimentacao.criado_em.desc(), Movimentacao.id)
        .limit(8)
    ).all()

    recentes = sorted(atendimentos_abertos, key=lambda a: a.atualizado_em, reverse=True)[:5]

    return {
        "indicadores": indicadores,
        "resumoPorLoja": resumo_por_loja,
        "alertas": alertas,
        "movimentacoesRecentes": [movimentacao_view(mov) for mov in movimentacoes_recentes],
        "atendimentosRecentes": atendimentos_view(db, recentes),
    }

