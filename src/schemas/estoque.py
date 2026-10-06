from typing import Literal

from src import models as m
from src.entities.estoque import status_estoque
from src.schemas.comum import Entrada, loja_saida, usuario_resumo
from src.schemas.produtos import produto_resumo, variacao_base
from src.utils.datas import ms

TipoMovimentacao = Literal["ENTRADA", "VENDA", "DEVOLUCAO", "AJUSTE", "TRANSFERENCIA_SAIDA", "TRANSFERENCIA_ENTRADA"]


class MovimentacaoEntrada(Entrada):
    estoque_id: int
    tipo: TipoMovimentacao
    # Com sinal: positiva entra, negativa sai
    quantidade: int
    origem: str = ""
    # Ignorado: o autor é sempre o usuário do token. Mantido por compatibilidade com o frontend.
    usuario_id: int | None = None


def estoque_saida(estoque: m.Estoque) -> dict:
    return {
        "id": estoque.id,
        "lojaId": estoque.loja_id,
        "variacaoId": estoque.variacao_id,
        "quantidade": estoque.quantidade,
        "quantidadeMin": estoque.quantidade_min,
        "atualizadoEm": ms(estoque.atualizado_em),
        "status": status_estoque(estoque.quantidade, estoque.quantidade_min),
        "loja": loja_saida(estoque.loja),
        "variacao": variacao_base(estoque.variacao),
        "produto": produto_resumo(estoque.variacao.produto),
    }


def movimentacao_saida(mov: m.Movimentacao) -> dict:
    estoque = mov.estoque
    return {
        "id": mov.id,
        "estoqueId": mov.estoque_id,
        "tipo": mov.tipo,
        "quantidade": mov.quantidade,
        "origem": mov.origem,
        "usuarioId": mov.usuario_id,
        "transferenciaId": mov.transferencia_id,
        "criadoEm": ms(mov.criado_em),
        "saldoResultante": mov.saldo_resultante,
        "loja": loja_saida(estoque.loja),
        "variacao": variacao_base(estoque.variacao),
        "produto": produto_resumo(estoque.variacao.produto),
        "usuario": usuario_resumo(mov.usuario),
    }
