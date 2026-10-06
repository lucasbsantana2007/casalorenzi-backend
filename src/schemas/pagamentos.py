from src import models as m
from src.utils.datas import ms


def pagamento_saida(p: m.Pagamento) -> dict:
    return {
        "id": p.id,
        "pedidoId": p.pedido_id,
        "metodo": p.metodo,
        "valor": float(p.valor),
        "parcelas": p.parcelas,
        "status": p.status,
        "criadoEm": ms(p.criado_em),
        "atualizadoEm": ms(p.atualizado_em),
    }
