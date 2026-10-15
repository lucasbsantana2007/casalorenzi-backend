from datetime import date

from src import models as m
from src.entities import fidelidade as regra
from src.utils.datas import ms


def movimento_saida(movimento: m.MovimentoPontos) -> dict:
    return {
        "id": movimento.id,
        "tipo": movimento.tipo,
        "quantidade": movimento.quantidade,
        "data": ms(movimento.data),
        "venceEm": movimento.vence_em.isoformat() if movimento.vence_em else None,
        "pedido": movimento.pedido.numero if movimento.pedido else None,
        "origem": movimento.origem,
        "obs": movimento.obs,
    }


def extrato_saida(conta: m.ContaPontos, a_vencer: list[tuple[date, int]]) -> dict:
    return {
        "saldo": conta.saldo,
        "saldoEmReais": float(conta.saldo * regra.VALOR_PONTO_VIGENTE),
        "categoria": conta.categoria,
        "categoriaDeclarada": conta.categoria_declarada,
        "validadeMeses": regra.validade_meses(conta.categoria),
        "aVencer": [{"venceEm": dia.isoformat(), "pontos": pontos} for dia, pontos in a_vencer],
        # Mais recente primeiro
        "movimentos": [movimento_saida(mv) for mv in sorted(conta.movimentos, key=lambda mv: (mv.data, mv.id), reverse=True)],
    }
