"""O que o próprio cliente faz nos pedidos dele, pelo chat da Lúcia ou pela conta (decisões 93, 96 e 97).

- cancelar: só pedido ainda em separação (PROCESSANDO), pelo mesmo cancelamento do painel: estorna o pagamento,
  devolve os pontos usados, tira os pontos ganhos e cancela as transferências que não saíram;
- pedir devolução: pedido enviado ou entregue, até 30 dias do recebimento. Abre a solicitação "Devolução e
  reembolso" no Atendimento, ligada ao pedido, com as peças e o motivo. A equipe confere a peça, registra a
  devolução e faz o estorno: dinheiro de volta sempre passa por uma pessoa.

Sempre os pedidos do cliente da sessão; pedido de outra pessoa responde como se não existisse.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src import models as m
from src.config.settings import FUSO
from src.entities import devolucao as regra
from src.entities.atendimento import EM_ABERTO
from src.repositories import atendimento_repository, cadastro_repository, pedido_repository, sessao
from src.use_cases import atendimentos, pedidos
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos, NaoEncontrado

CONTA_DEVOLUCAO = "DEVOLUCAO"  # tipo de solicitação "Devolução e reembolso" (conta_pos_venda)


def recebido_em(pedido: m.Pedido) -> datetime | None:
    """Quando o cliente recebeu: o evento de entrega; sem ele, a data do pedido para pedido entregue (compra na loja)."""
    entrega = next((e for e in reversed(pedido.eventos) if e.status == "ENTREGUE"), None)
    if entrega is not None:
        return entrega.criado_em
    return pedido.criado_em if pedido.status == "ENTREGUE" else None


def prazo_devolucao(pedido: m.Pedido) -> datetime | None:
    """Último momento para pedir a devolução (30 dias do recebimento); None se ainda não foi entregue."""
    recebido = recebido_em(pedido)
    return recebido + timedelta(days=regra.PRAZO_DEVOLUCAO_DIAS) if recebido else None


def devolvivel(item: m.ItemPedido) -> int:
    return regra.saldo_devolvivel(item.quantidade, sum(d.quantidade for d in item.devolucoes))


def pode_pedir_devolucao(pedido: m.Pedido) -> bool:
    prazo = prazo_devolucao(pedido)
    return regra.aceita_devolucao(pedido.status) and prazo is not None and agora() <= prazo


def _do_cliente(db: Session, cliente: m.Cliente, numero: str, travar: bool = False) -> m.Pedido:
    pedido = pedido_repository.do_cliente_por_numero(db, cliente.id, numero)
    if pedido is None:
        raise NaoEncontrado("Pedido não encontrado na sua conta.")
    return pedido_repository.obter(db, pedido.id, travar=True) if travar else pedido


def cancelar(db: Session, cliente: m.Cliente, numero: str) -> m.Pedido:
    pedido = _do_cliente(db, cliente, numero, travar=True)
    if pedido.status == "CANCELADO":
        raise Conflito("Este pedido já está cancelado.")
    if pedido.status != "PROCESSANDO":
        raise Conflito("Este pedido já saiu para entrega e não pode mais ser cancelado. Você pode pedir a devolução.")
    pedidos.cancelar(db, pedido, agora(), usuario_id=None, observacao="Cancelado pelo cliente; pagamento estornado")
    sessao.confirmar(db)
    sessao.descartar_cache(db)
    return pedido_repository.do_cliente_por_numero(db, cliente.id, pedido.numero)


@dataclass
class PecaDevolvida:
    item_pedido_id: int
    quantidade: int


def _tipo_devolucao(db: Session) -> m.TipoSolicitacao:
    tipo = next((t for t in cadastro_repository.tipos_solicitacao(db, ativo=True) if t.conta_pos_venda == CONTA_DEVOLUCAO), None)
    if tipo is None:
        raise Conflito("A devolução pelo site não está disponível agora. Fale com a equipe.")
    return tipo


def pedir_devolucao(db: Session, cliente: m.Cliente, numero: str, pecas: list[PecaDevolvida], motivo: str) -> m.Atendimento:
    """Abre a solicitação de devolução. Pedir de novo, com uma aberta para o mesmo pedido, devolve a mesma."""
    pedido = _do_cliente(db, cliente, numero)
    if not regra.aceita_devolucao(pedido.status):
        raise Conflito(
            "Este pedido ainda não saiu para entrega: dá para cancelar em vez de devolver."
            if pedido.status == "PROCESSANDO"
            else "Este pedido não aceita devolução."
        )
    prazo = prazo_devolucao(pedido)
    if prazo is None or agora() > prazo:
        raise Conflito(f"O prazo de devolução ({regra.PRAZO_DEVOLUCAO_DIAS} dias do recebimento) deste pedido já passou.")
    motivo = (motivo or "").strip()
    if len(motivo) < 3:
        raise DadosInvalidos("Conte o motivo da devolução.")
    itens = {item.id: item for item in pedido.itens}
    escolhidas = []
    for peca in pecas:
        item = itens.get(peca.item_pedido_id)
        if item is None:
            raise DadosInvalidos("Peça não encontrada neste pedido.")
        if not 1 <= peca.quantidade <= devolvivel(item):
            raise DadosInvalidos(f"Quantidade inválida para {item.variacao.produto.nome}.")
        escolhidas.append((item, peca.quantidade))
    if not escolhidas:
        raise DadosInvalidos("Escolha ao menos uma peça para devolver.")
    tipo = _tipo_devolucao(db)
    aberta = next(
        (
            a
            for a in atendimento_repository.do_cliente(db, cliente.id)
            if a.pedido_id == pedido.id and a.tipo_solicitacao_id == tipo.id and a.status in EM_ABERTO
        ),
        None,
    )
    if aberta is not None:
        return aberta
    linhas = [
        "Pedido de devolução feito pela Lúcia, a assistente virtual do site, com a confirmação do cliente.",
        "Peças:",
        *(f"- {i.variacao.produto.nome} ({i.variacao.cor}, {i.variacao.tamanho}) x{q}" for i, q in escolhidas),
        f"Motivo: {motivo[: regra.MOTIVO_MAX]}",
        f"Recebido em {recebido_em(pedido).astimezone(FUSO):%d/%m/%Y}; prazo de devolução até {prazo.astimezone(FUSO):%d/%m/%Y}.",
    ]
    return atendimentos.abrir_para_cliente(
        db, cliente, tipo_solicitacao_id=tipo.id, pedido_id=pedido.id, descricao="\n".join(linhas)
    )
