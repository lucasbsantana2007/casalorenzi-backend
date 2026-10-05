"""Corpos de requisição aceitos pela API (o frontend envia camelCase)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Entrada(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LoginEntrada(Entrada):
    email: str
    senha: str


class VariacaoEntrada(Entrada):
    id: int | None = None
    sku: str
    tamanho: str = ""
    cor: str = ""


class ProdutoEntrada(Entrada):
    nome: str = ""
    categoria: str = ""
    preco_base: float = 0
    ativo: bool = True
    genero: str | None = None
    estacao: str | None = None
    variacoes: list[VariacaoEntrada] = Field(default_factory=list)


TipoMovimentacao = Literal["ENTRADA", "VENDA", "DEVOLUCAO", "AJUSTE", "TRANSFERENCIA_SAIDA", "TRANSFERENCIA_ENTRADA"]


class MovimentacaoEntrada(Entrada):
    estoque_id: int
    tipo: TipoMovimentacao
    # Com sinal: positiva entra, negativa sai
    quantidade: int
    origem: str = ""
    # Ignorado: o autor é sempre o usuário do token. Mantido por compatibilidade com o frontend.
    usuario_id: int | None = None


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


StatusAtendimento = Literal["ABERTO", "EM_ANDAMENTO", "AGUARDANDO_CLIENTE", "CONCLUIDO"]


class AtendimentoAtualizacao(Entrada):
    status: StatusAtendimento | None = None
    # Enviar null remove o responsável; omitir o campo mantém o atual
    responsavel_id: int | None = None


class MensagemEntrada(Entrada):
    conteudo: str = ""
    autor_id: int | None = None
    autor_tipo: Literal["ATENDENTE", "CLIENTE"] | None = None


class SolicitacaoEntrada(Entrada):
    cliente_id: int | None = None
    tipo_solicitacao_id: int | None = None
    pedido_id: int | None = None
    descricao: str = ""
