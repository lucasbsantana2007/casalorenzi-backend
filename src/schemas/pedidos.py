from typing import Literal

from src import models as m
from src.entities.frete import ROTULOS
from src.schemas.comum import Entrada, loja_saida, usuario_resumo
from src.schemas.produtos import variacao_saida
from src.schemas.transferencias import transferencia_saida
from src.utils.datas import ms

# ---------- Entradas ----------
# Campos com valor padrão: o use case devolve a mensagem certa em português em vez do 422 genérico.


class EnderecoEntrada(Entrada):
    cep: str = ""
    rua: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""
    cidade: str = ""
    uf: str = ""


class PagamentoCheckoutEntrada(Entrada):
    metodo: str = ""
    parcelas: int = 1


class ItemCheckoutEntrada(Entrada):
    variacao_id: int
    quantidade: int = 1


class CheckoutEntrada(Entrada):
    """O cliente vem do token (conta criada no próprio checkout): nada de identificação no corpo."""

    endereco: EnderecoEntrada = EnderecoEntrada()
    frete_tipo: Literal["PADRAO", "EXPRESSO"] = "PADRAO"
    pagamento: PagamentoCheckoutEntrada = PagamentoCheckoutEntrada()
    itens: list[ItemCheckoutEntrada] = []


class PedidoAtualizacao(Entrada):
    """{ lojaId } troca a loja de expedição | { status: 'ENVIADO', codigoRastreio } | { status: 'ENTREGUE' | 'CANCELADO' }."""

    loja_id: int | None = None
    status: Literal["ENVIADO", "ENTREGUE", "CANCELADO"] | None = None
    codigo_rastreio: str | None = None
    # Ignorado: quem fez a mudança vem do token
    usuario_id: int | None = None


# ---------- Saídas ----------


def _frete(pedido: m.Pedido) -> dict | None:
    if pedido.frete_tipo is None:
        return None
    return {
        "tipo": pedido.frete_tipo,
        "label": ROTULOS.get(pedido.frete_tipo, pedido.frete_tipo),
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


def _eventos(pedido: m.Pedido, completo: bool) -> list[dict]:
    """Pedidos anteriores ao histórico (sem eventos): o status atual na data de criação."""
    if not pedido.eventos:
        base = {"status": pedido.status, "em": ms(pedido.criado_em)}
        return [{**base, "usuario": None, "observacao": ""} if completo else base]
    if completo:
        return [
            {"status": e.status, "em": ms(e.criado_em), "usuario": usuario_resumo(e.usuario), "observacao": e.observacao}
            for e in pedido.eventos
        ]
    return [{"status": e.status, "em": ms(e.criado_em)} for e in pedido.eventos]


def pedido_admin_saida(pedido: m.Pedido, saldos_na_loja: dict[int, int]) -> dict:
    """Painel: pedido completo, com o saldo de cada peça na loja de expedição, as transferências
    automáticas e o histórico com quem fez cada mudança."""
    base = pedido_saida(pedido)
    for item in base["itens"]:
        item["saldoNaLoja"] = saldos_na_loja.get(item["variacaoId"], 0)
    return {
        **base,
        "transferencias": [{**transferencia_saida(t), "sku": t.variacao.sku} for t in pedido.transferencias],
        "historico": _eventos(pedido, completo=True),
    }


def pedido_publico_saida(pedido: m.Pedido) -> dict:
    """Loja ("Meus pedidos" e confirmação da compra): sem loja de expedição, estoque, transferências
    nem quem da equipe mexeu no pedido."""
    cliente = pedido.cliente
    return {
        "numero": pedido.numero,
        "status": pedido.status,
        "criadoEm": ms(pedido.criado_em),
        "codigoRastreio": pedido.codigo_rastreio,
        "contato": {"nome": cliente.nome, "email": cliente.email} if cliente else None,
        "endereco": _endereco(pedido),
        "frete": _frete(pedido),
        "pagamento": _pagamento(pedido),
        "subtotal": float(pedido.subtotal),
        "total": float(pedido.total),
        "itens": [
            {
                "variacaoId": item.variacao_id,
                "quantidade": item.quantidade,
                "precoUnitario": float(item.preco_unitario),
                "variacao": variacao_saida(item.variacao),
            }
            for item in pedido.itens
        ],
        "historico": _eventos(pedido, completo=False),
    }
