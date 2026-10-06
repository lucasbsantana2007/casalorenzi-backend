from typing import Literal

from src import models as m
from src.schemas.comum import Entrada, loja_saida, usuario_resumo
from src.schemas.produtos import produto_resumo, variacao_base
from src.utils.datas import ms


class TransferenciaEntrada(Entrada):
    variacao_id: int | None = None
    loja_origem_id: int
    loja_destino_id: int
    quantidade: int
    observacao: str = ""
    usuario_id: int | None = None


class TransferenciaStatusEntrada(Entrada):
    status: Literal["EM_TRANSITO", "CONCLUIDA", "CANCELADA"]
    usuario_id: int | None = None


def transferencia_saida(t: m.Transferencia) -> dict:
    return {
        "id": t.id,
        "codigo": t.codigo,
        "variacaoId": t.variacao_id,
        "lojaOrigemId": t.loja_origem_id,
        "lojaDestinoId": t.loja_destino_id,
        "quantidade": t.quantidade,
        "status": t.status,
        "solicitanteId": t.solicitante_id,
        "responsavelId": t.responsavel_id,
        "criadoEm": ms(t.criado_em),
        "enviadoEm": ms(t.enviado_em),
        "recebidoEm": ms(t.recebido_em),
        "observacao": t.observacao or "",
        "variacao": variacao_base(t.variacao),
        "produto": produto_resumo(t.variacao.produto),
        "lojaOrigem": loja_saida(t.loja_origem),
        "lojaDestino": loja_saida(t.loja_destino),
        "solicitante": usuario_resumo(t.solicitante),
        "responsavel": usuario_resumo(t.responsavel),
    }
