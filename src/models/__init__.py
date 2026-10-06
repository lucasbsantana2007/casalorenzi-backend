"""Tabelas do banco, um arquivo por tabela. Importar este pacote registra todas no metadata
(o Alembic depende disso). Toda mudança aqui precisa de uma migration:

    alembic revision --autogenerate -m "descreva a mudança"
    alembic upgrade head
"""

from src.models.anexo import Anexo
from src.models.atendimento import Atendimento
from src.models.categoria import Categoria
from src.models.cliente import Cliente
from src.models.devolucao import Devolucao
from src.models.estoque import Estoque
from src.models.evento_pedido import EventoPedido
from src.models.item_pedido import ItemPedido
from src.models.loja import Loja
from src.models.mensagem import Mensagem
from src.models.movimentacao import Movimentacao
from src.models.pagamento import Pagamento
from src.models.pedido import Pedido
from src.models.produto import Produto
from src.models.tipo_solicitacao import TipoSolicitacao
from src.models.token_pin import TokenPin
from src.models.transferencia import Transferencia
from src.models.usuario import Usuario
from src.models.variacao import Variacao

__all__ = [
    "Loja",
    "Categoria",
    "Usuario",
    "Cliente",
    "TokenPin",
    "Produto",
    "Variacao",
    "Estoque",
    "Transferencia",
    "Movimentacao",
    "Pedido",
    "ItemPedido",
    "Pagamento",
    "EventoPedido",
    "Devolucao",
    "TipoSolicitacao",
    "Atendimento",
    "Mensagem",
    "Anexo",
]
