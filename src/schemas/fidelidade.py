"""Vulto+: o que a área do cliente e o painel mostram do saldo e do extrato."""

from src.entities import fidelidade as regra
from src.use_cases.fidelidade import Resumo
from src.utils.datas import ms

ROTULOS_CATEGORIA = {"BRONZE": "Bronze", "PRATA": "Prata", "OURO": "Ouro", "VIP": "Vip"}


def pontos_saida(resumo: Resumo) -> dict:
    """{ saldo, valorEmReais, categoria, bonus, aVencer, extrato, regras }."""
    bonus = regra.BONUS_CATEGORIA.get(resumo.categoria or "")
    return {
        "saldo": resumo.saldo,
        "valorEmReais": float(resumo.valor_em_reais),
        "categoria": ROTULOS_CATEGORIA.get(resumo.categoria or ""),
        # Bônus de pontos da categoria em porcentagem (Ouro 25, Vip 50); 0 nas outras
        "bonus": int(bonus * 100) if bonus else 0,
        "aVencer": [{"data": data.isoformat(), "pontos": pontos} for data, pontos in resumo.a_vencer],
        "extrato": [
            {
                "id": mov.id,
                "tipo": mov.tipo,
                "quantidade": mov.quantidade,
                "saldo": mov.saldo_resultante,
                "venceEm": mov.vence_em.isoformat() if mov.vence_em else None,
                "pedidoNumero": mov.pedido.numero if mov.pedido else None,
                "valorDesconto": float(mov.valor_desconto) if mov.valor_desconto is not None else None,
                "obs": mov.obs,
                "criadoEm": ms(mov.criado_em),
            }
            for mov in resumo.movimentos
        ],
        "regras": {
            "valorPonto": float(regra.VALOR_PONTO),
            "resgateMultiplo": regra.RESGATE_MULTIPLO,
            "compraMinimaResgate": float(regra.COMPRA_MINIMA_RESGATE),
            "validadeMeses": regra.VALIDADE_MESES,
            "pontosPorReal": regra.PONTOS_POR_REAL,
            "bonusCategoria": {ROTULOS_CATEGORIA[c]: int(b * 100) for c, b in regra.BONUS_CATEGORIA.items()},
        },
    }
