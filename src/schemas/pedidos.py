from src import models as m
from src.schemas.comum import loja_saida
from src.schemas.produtos import variacao_saida
from src.utils.datas import ms


def _frete(pedido: m.Pedido) -> dict | None:
    if pedido.frete_tipo is None:
        return None
    return {
        "tipo": pedido.frete_tipo,
        "valor": float(pedido.frete_valor or 0),
        "prazoDias": pedido.frete_prazo_dias,
    }


def _endereco(pedido: m.Pedido) -> dict | None:
    if pedido.entrega_cep is None:
        return None
    return {
        "cep": pedido.entrega_cep,
        "rua": pedido.entrega_rua,
        "numero": pedido.entrega_numero,
        "complemento": pedido.entrega_complemento,
        "bairro": pedido.entrega_bairro,
        "cidade": pedido.entrega_cidade,
        "uf": pedido.entrega_uf,
    }


def _pagamento(pedido: m.Pedido) -> dict | None:
    """Resumo do pagamento mais recente, no formato do mock do frontend ({ metodo, parcelas, status })."""
    if not pedido.pagamentos:
        return None
    ultimo = pedido.pagamentos[-1]
    return {"metodo": ultimo.metodo, "parcelas": ultimo.parcelas, "status": ultimo.status}


def pedido_saida(pedido: m.Pedido | None) -> dict | None:
    if pedido is None:
        return None
    cliente = pedido.cliente
    return {
        "id": pedido.id,
        "numero": pedido.numero,
        "clienteId": pedido.cliente_id,
        "lojaId": pedido.loja_id,
        "canal": pedido.canal,
        "status": pedido.status,
        "criadoEm": ms(pedido.criado_em),
        "codigoRastreio": pedido.codigo_rastreio,
        "subtotal": float(pedido.subtotal),
        "total": float(pedido.total),
        "frete": _frete(pedido),
        "endereco": _endereco(pedido),
        "pagamento": _pagamento(pedido),
        "contato": {"nome": cliente.nome, "email": cliente.email, "telefone": cliente.telefone} if cliente else None,
        "loja": loja_saida(pedido.loja),
        "itens": [
            {
                "id": item.id,
                "variacaoId": item.variacao_id,
                "quantidade": item.quantidade,
                "quantidadeDevolvida": item.quantidade_devolvida,
                "precoUnitario": float(item.preco_unitario),
                "variacao": variacao_saida(item.variacao),
            }
            for item in pedido.itens
        ],
    }
