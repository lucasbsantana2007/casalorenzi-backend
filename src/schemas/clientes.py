from src import models as m
from src.utils.datas import ms


def cliente_saida(cliente: m.Cliente | None) -> dict | None:
    """Nunca inclui o hash da senha: só se o cliente já tem conta."""
    if cliente is None:
        return None
    return {
        # id público = CPF (nulo na conta excluída, que tem os dados pessoais apagados)
        "id": cliente.cpf,
        "nome": cliente.nome,
        "email": cliente.email,
        "telefone": cliente.telefone,
        "clienteDesde": cliente.cliente_desde.isoformat() if cliente.cliente_desde else None,
        "lojaPreferidaId": cliente.loja_preferida_id,
        "cpf": cliente.cpf,
        "temConta": cliente.senha_hash is not None,
        "excluido": cliente.excluido_em is not None,
        "aceitaMarketing": cliente.aceita_marketing,
    }


def pedido_resumo(pedido: m.Pedido) -> dict:
    """Pedido de qualquer das marcas na visão unificada do cliente."""
    return {
        "id": pedido.id,
        "numero": pedido.numero,
        "marca": pedido.loja.marca,
        "canal": pedido.canal,
        "loja": pedido.loja.nome,
        "status": pedido.status,
        "total": float(pedido.total),
        "criadoEm": ms(pedido.criado_em),
    }


def cliente_unificado_saida(cliente: m.Cliente, pedidos: list[m.Pedido], conta: m.ContaPontos | None) -> dict:
    por_marca: dict[str, dict] = {}
    for p in pedidos:
        totais = por_marca.setdefault(p.loja.marca, {"pedidos": 0, "valor": 0.0})
        totais["pedidos"] += 1
        totais["valor"] += float(p.total) if p.status != "CANCELADO" else 0.0
    return {
        **cliente_saida(cliente),
        "vultoMais": (
            {
                "saldo": conta.saldo,
                "categoria": conta.categoria,
                "categoriaDeclarada": conta.categoria_declarada,
            }
            if conta
            else None
        ),
        "totaisPorMarca": por_marca,
        "pedidos": [pedido_resumo(p) for p in sorted(pedidos, key=lambda p: p.criado_em, reverse=True)],
    }
