from src import models as m
from src.schemas.comum import Entrada, loja_saida, usuario_resumo
from src.schemas.produtos import variacao_saida
from src.utils.datas import ms


class DevolucaoEntrada(Entrada):
    """Informe o item pelo id do item do pedido (itemPedidoId) ou pela variação comprada (itemVariacaoId)."""

    item_pedido_id: int | None = None
    item_variacao_id: int | None = None
    quantidade: int = 0
    motivo: str = ""
    atendimento_id: int | None = None
    # Loja em que a peça volta para o estoque. Omitida: a loja do usuário ou, se ele não tiver, a do pedido.
    loja_id: int | None = None


def devolucao_saida(d: m.Devolucao) -> dict:
    return {
        "id": d.id,
        "pedidoId": d.pedido_id,
        "pedidoNumero": d.pedido.numero,
        "itemPedidoId": d.item_pedido_id,
        "variacaoId": d.item.variacao_id,
        "atendimentoId": d.atendimento_id,
        "usuarioId": d.usuario_id,
        "lojaId": d.loja_id,
        "movimentacaoId": d.movimentacao_id,
        "quantidade": d.quantidade,
        "valorDevolvido": float(d.valor_devolvido),
        "motivo": d.motivo,
        "criadaEm": ms(d.criada_em),
        "loja": loja_saida(d.loja),
        "usuario": usuario_resumo(d.usuario),
        "variacao": variacao_saida(d.item.variacao),
    }
