"""Tabelas do banco, um arquivo por tabela. Importar este pacote registra todas no metadata
(o Alembic depende disso). Toda mudança aqui precisa de uma migration:

    alembic revision --autogenerate -m "descreva a mudança"
    alembic upgrade head
"""

from src.models.alerta import Alerta
from src.models.anexo import Anexo
from src.models.atendimento import Atendimento
from src.models.aviso_estoque import AvisoEstoque
from src.models.aviso_pontos import AvisoPontos
from src.models.categoria import Categoria
from src.models.chamada_ferramenta import ChamadaFerramenta
from src.models.cliente import Cliente
from src.models.consumo_ia import ConsumoIA
from src.models.conversa_assistente import ConversaAssistente
from src.models.de_para import DePara
from src.models.decisao_migracao import DecisaoMigracao
from src.models.devolucao import Devolucao
from src.models.estoque import Estoque
from src.models.evento_pedido import EventoPedido
from src.models.execucao_automacao import ExecucaoAutomacao
from src.models.fornecedor import Fornecedor
from src.models.frete import ConfigFrete, FreteRegiao
from src.models.imagem_produto import ImagemProduto
from src.models.item_pedido import ItemPedido
from src.models.log_acao import LogAcao
from src.models.loja import Loja
from src.models.mensagem import Mensagem
from src.models.mensagem_assistente import MensagemAssistente
from src.models.movimentacao import Movimentacao
from src.models.movimento_pontos import MovimentoPontos
from src.models.pagamento import Pagamento
from src.models.pedido import Pedido
from src.models.produto import Produto
from src.models.sacola import Sacola
from src.models.tipo_solicitacao import TipoSolicitacao
from src.models.token_mcp import ChamadaMcp, TokenMcp
from src.models.token_senha import TokenSenha
from src.models.transferencia import Transferencia
from src.models.usuario import Usuario
from src.models.variacao import Variacao

__all__ = [
    "AvisoEstoque",
    "Sacola",
    "Loja",
    "Categoria",
    "Fornecedor",
    "Usuario",
    "Cliente",
    "TokenSenha",
    "Produto",
    "Variacao",
    "ImagemProduto",
    "Estoque",
    "Transferencia",
    "Movimentacao",
    "Pedido",
    "ItemPedido",
    "Pagamento",
    "EventoPedido",
    "Devolucao",
    "MovimentoPontos",
    "TipoSolicitacao",
    "Atendimento",
    "Mensagem",
    "Anexo",
    "ConfigFrete",
    "FreteRegiao",
    "LogAcao",
    "DecisaoMigracao",
    "DePara",
    "ConversaAssistente",
    "MensagemAssistente",
    "ChamadaFerramenta",
    "ConsumoIA",
    "Alerta",
    "ExecucaoAutomacao",
    "AvisoPontos",
    "TokenMcp",
    "ChamadaMcp",
]
