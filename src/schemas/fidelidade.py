from src import models as m
from src.entities import fidelidade as regra
from src.utils.datas import ms


def extrato_saida(saldo: int, movimentos: list[m.MovimentoPontos]) -> dict:
    return {
        "saldo": saldo,
        "saldoEmReais": float(regra.desconto_do_resgate(saldo)),
        "resgate": {
            "compraMinima": float(regra.COMPRA_MINIMA_RESGATE),
            "multiplo": regra.RESGATE_MULTIPLO,
            "valorPonto": float(regra.VALOR_PONTO),
        },
        "movimentos": [
            {
                "id": mv.id,
                "tipo": mv.tipo,
                "quantidade": mv.quantidade,
                "saldo": mv.saldo_resultante,
                "pedido": mv.pedido.numero if mv.pedido else None,
                "obs": mv.obs,
                "em": ms(mv.criado_em),
            }
            for mv in movimentos
        ],
    }
