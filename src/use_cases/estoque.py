"""Estoque: todo saldo vem das movimentações e nunca fica negativo."""

from datetime import datetime

from sqlalchemy.orm import Session

from src import models as m
from src.entities.estoque import ORDEM_STATUS, SINAL_POR_TIPO_MANUAL, quantidade_valida_para_tipo, status_estoque
from src.repositories import cadastro_repository, estoque_repository, sessao
from src.utils.datas import agora, fim_do_dia, inicio_do_dia, ler_data
from src.utils.erros import DadosInvalidos, NaoEncontrado
from src.utils.texto import chave_texto, corresponde


def aplicar_movimentacao(
    db: Session,
    estoque: m.Estoque,
    *,
    tipo: str,
    quantidade: int,
    origem: str,
    usuario_id: int | None,
    transferencia_id: int | None = None,
    quando: datetime | None = None,
) -> m.Movimentacao:
    """Registra a movimentação e atualiza o saldo, sem confirmar a transação."""
    saldo = estoque.quantidade + quantidade
    if saldo < 0:
        raise DadosInvalidos(f"Saldo insuficiente: há {estoque.quantidade} unidade(s) disponível(is).")
    quando = quando or agora()
    mov = m.Movimentacao(
        estoque=estoque,
        tipo=tipo,
        quantidade=quantidade,
        origem=origem,
        usuario_id=usuario_id,
        transferencia_id=transferencia_id,
        saldo_resultante=saldo,
        criado_em=quando,
    )
    sessao.adicionar(db, mov)
    estoque.quantidade = saldo
    estoque.atualizado_em = quando
    return mov


def criar_estoques_zerados(db: Session, variacao: m.Variacao) -> None:
    """Toda variação nova passa a existir, com saldo zero, em todas as lojas."""
    for loja in cadastro_repository.lojas(db):
        sessao.adicionar(db, m.Estoque(loja_id=loja.id, variacao=variacao, quantidade=0, quantidade_min=2, atualizado_em=agora()))


def _filtrar(itens: list[m.Estoque], busca: str | None, status: str | None) -> list[m.Estoque]:
    resultado = []
    for e in itens:
        situacao = status_estoque(e.quantidade, e.quantidade_min)
        # ALERTA agrupa estoque baixo e sem estoque
        if status and (situacao == "NORMAL" if status == "ALERTA" else situacao != status):
            continue
        if not corresponde(busca, e.variacao.produto.nome, e.variacao.sku, e.variacao.cor):
            continue
        resultado.append(e)
    return resultado


def listar(
    db: Session,
    *,
    busca: str | None = None,
    loja_id: int | None = None,
    categoria: str | None = None,
    status: str | None = None,
    variacao_id: int | None = None,
) -> list[m.Estoque]:
    """Ordem: o que pede ação primeiro (sem estoque, baixo), depois por nome e loja."""
    itens = _filtrar(estoque_repository.listar(db, loja_id=loja_id, variacao_id=variacao_id, categoria=categoria), busca, status)
    itens.sort(
        key=lambda e: (
            ORDEM_STATUS[status_estoque(e.quantidade, e.quantidade_min)],
            chave_texto(e.variacao.produto.nome),
            e.loja_id,
        )
    )
    return itens


def obter(db: Session, estoque_id: int) -> m.Estoque:
    estoque = estoque_repository.obter(db, estoque_id)
    if estoque is None:
        raise NaoEncontrado("Item de estoque não encontrado.")
    return estoque


def posicao_em_data(
    db: Session, data: str | None, loja_id: int | None = None, busca: str | None = None
) -> list[tuple[m.Estoque, int]]:
    """Reconstrói o saldo de cada item ao final do dia informado, a partir do histórico."""
    dia = ler_data(data)
    if dia is None:
        raise DadosInvalidos("Informe a data de referência.")
    saldos = estoque_repository.saldos_ate(db, fim_do_dia(dia))
    itens = _filtrar(estoque_repository.listar(db, loja_id=loja_id), busca, None)
    itens.sort(key=lambda e: (not e.variacao.produto.ativo, chave_texto(e.variacao.produto.nome), e.loja_id))
    return [(e, int(saldos.get(e.id) or 0)) for e in itens]


def listar_movimentacoes(
    db: Session,
    *,
    estoque_id: int | None = None,
    loja_id: int | None = None,
    tipo: str | None = None,
    de: str | None = None,
    ate: str | None = None,
    busca: str | None = None,
) -> list[m.Movimentacao]:
    dia_inicial = ler_data(de, "de")
    dia_final = ler_data(ate, "ate")
    movimentacoes = estoque_repository.listar_movimentacoes(
        db,
        estoque_id=estoque_id,
        loja_id=loja_id,
        tipo=tipo,
        desde=inicio_do_dia(dia_inicial) if dia_inicial else None,
        ate=fim_do_dia(dia_final) if dia_final else None,
    )
    return [
        mov
        for mov in movimentacoes
        if corresponde(busca, mov.estoque.variacao.produto.nome, mov.estoque.variacao.sku, mov.origem)
    ]


def registrar_movimentacao(
    db: Session, *, estoque_id: int, tipo: str, quantidade: int, origem: str, usuario_id: int
) -> m.Movimentacao:
    """Lançamento manual (entrada, venda, devolução ou ajuste).
    Transferências geram suas movimentações pelo fluxo de transferências."""
    estoque = estoque_repository.obter(db, estoque_id, travar=True)
    if estoque is None:
        raise NaoEncontrado("Item de estoque não encontrado.")
    if tipo not in SINAL_POR_TIPO_MANUAL:
        raise DadosInvalidos("Movimentações de transferência são geradas pela tela de transferências.")
    if not quantidade_valida_para_tipo(tipo, quantidade):
        raise DadosInvalidos("Informe uma quantidade válida.")
    mov = aplicar_movimentacao(db, estoque, tipo=tipo, quantidade=quantidade, origem=origem.strip(), usuario_id=usuario_id)
    sessao.confirmar(db)
    return mov
