"""Devoluções de peças de pedidos (regras em src/entities/devolucao.py).

Uma devolução, numa única transação:
1. confere o pedido (não pode estar CANCELADO nem ainda PROCESSANDO) e o saldo devolvível do item;
2. devolve as peças ao estoque da loja escolhida com uma movimentação DEVOLUCAO (+quantidade);
3. grava a devolução com o valor reembolsado (preço pago × quantidade; frete não volta);
4. se o pedido inteiro foi devolvido, estorna os pagamentos APROVADOS (APROVADO → ESTORNADO).
   Devoluções parciais não mexem no pagamento: o reembolso fica registrado no valor_devolvido
   da própria devolução (é o que o financeiro soma em devolucoesValor).
"""

from sqlalchemy.orm import Session

from src import models as m
from src.entities.devolucao import (
    MOTIVO_MAX,
    aceita_devolucao,
    pedido_totalmente_devolvido,
    saldo_devolvivel,
    valor_devolvido,
)
from src.repositories import (
    atendimento_repository,
    cadastro_repository,
    devolucao_repository,
    estoque_repository,
    pedido_repository,
    sessao,
)
from src.use_cases.atendimentos import registrar_evento
from src.use_cases.estoque import aplicar_movimentacao
from src.use_cases.pagamentos import estornar_aprovados
from src.utils.datas import agora, fim_do_dia, inicio_do_dia, ler_data
from src.utils.erros import Conflito, DadosInvalidos, NaoEncontrado


def _item_do_pedido(
    pedido: m.Pedido, item_pedido_id: int | None, variacao_id: int | None, devolvido: dict[int, int]
) -> m.ItemPedido:
    if item_pedido_id is not None:
        item = next((i for i in pedido.itens if i.id == item_pedido_id), None)
        if item is None:
            raise DadosInvalidos("Este item não pertence ao pedido.")
        return item
    if variacao_id is not None:
        itens = [i for i in pedido.itens if i.variacao_id == variacao_id]
        if not itens:
            raise DadosInvalidos("Esta peça não faz parte do pedido.")
        # A mesma variação pode aparecer em mais de um item: usa o primeiro que ainda tem saldo
        return next((i for i in itens if saldo_devolvivel(i.quantidade, devolvido.get(i.id, 0)) > 0), itens[0])
    raise DadosInvalidos("Informe o item a devolver.")


def registrar(
    db: Session,
    pedido_id: int,
    usuario: m.Usuario,
    *,
    item_pedido_id: int | None,
    variacao_id: int | None,
    quantidade: int,
    motivo: str,
    atendimento_id: int | None = None,
    loja_id: int | None = None,
) -> m.Devolucao:
    # Trava o pedido: duas devoluções simultâneas do mesmo item não passam juntas pela conferência de saldo
    pedido = pedido_repository.obter(db, pedido_id, travar=True)
    if pedido is None:
        raise NaoEncontrado("Pedido não encontrado.")
    if pedido.status == "CANCELADO":
        raise Conflito("Pedido cancelado não aceita devolução: o pagamento já foi estornado.")
    if not aceita_devolucao(pedido.status):
        raise Conflito("O pedido ainda não foi enviado. Cancele o pedido em vez de registrar devolução.")

    devolvido = devolucao_repository.devolvido_por_item(db, pedido.id)
    item = _item_do_pedido(pedido, item_pedido_id, variacao_id, devolvido)
    if quantidade <= 0:
        raise DadosInvalidos("Informe uma quantidade válida.")
    saldo = saldo_devolvivel(item.quantidade, devolvido.get(item.id, 0))
    if quantidade > saldo:
        raise DadosInvalidos(
            f"Só é possível devolver {saldo} unidade(s) deste item "
            f"(comprado: {item.quantidade}, já devolvido: {devolvido.get(item.id, 0)})."
        )
    motivo = motivo.strip()
    if not motivo:
        raise DadosInvalidos("Informe o motivo da devolução.")
    if len(motivo) > MOTIVO_MAX:
        raise DadosInvalidos(f"O motivo deve ter no máximo {MOTIVO_MAX} caracteres.")

    atendimento = None
    if atendimento_id is not None:
        atendimento = atendimento_repository.obter(db, atendimento_id)
        if atendimento is None or atendimento.cliente_id != pedido.cliente_id:
            raise DadosInvalidos("Atendimento não encontrado entre os do cliente do pedido.")
        if atendimento.pedido_id is not None and atendimento.pedido_id != pedido.id:
            raise DadosInvalidos("Este atendimento é sobre outro pedido.")

    loja_id = loja_id or usuario.loja_id or pedido.loja_id
    if cadastro_repository.loja(db, loja_id) is None:
        raise DadosInvalidos("Loja inválida.")
    estoque = estoque_repository.por_loja_e_variacao(db, loja_id, item.variacao_id, travar=True)
    if estoque is None:
        raise NaoEncontrado("Item não encontrado no estoque da loja.")

    momento = agora()
    mov = aplicar_movimentacao(
        db,
        estoque,
        tipo="DEVOLUCAO",
        quantidade=quantidade,
        origem=f"Devolução do pedido {pedido.numero}",
        usuario_id=usuario.id,
        quando=momento,
    )
    sessao.gerar_ids(db)
    devolucao = m.Devolucao(
        item_pedido_id=item.id,
        pedido_id=pedido.id,
        atendimento_id=atendimento.id if atendimento else None,
        usuario_id=usuario.id,
        loja_id=loja_id,
        movimentacao_id=mov.id,
        quantidade=quantidade,
        valor_devolvido=valor_devolvido(item.preco_unitario, quantidade),
        motivo=motivo,
        criada_em=momento,
    )
    sessao.adicionar(db, devolucao)

    devolvido[item.id] = devolvido.get(item.id, 0) + quantidade
    if pedido_totalmente_devolvido({i.id: i.quantidade for i in pedido.itens}, devolvido):
        estornar_aprovados(db, pedido, momento)

    if atendimento is not None:
        registrar_evento(db, atendimento, f"Devolução registrada: {quantidade} un. de {item.variacao.sku} ({estoque.loja.nome}).")
        atendimento.atualizado_em = momento

    sessao.confirmar(db, devolucao)
    sessao.descartar_cache(db)  # o pedido volta com as devoluções e pagamentos atualizados
    return devolucao_repository.obter(db, devolucao.id)


def listar(db: Session, *, de: str | None = None, ate: str | None = None, loja_id: int | None = None) -> list[m.Devolucao]:
    """de/ate em aaaa-mm-dd (inclusive); loja_id = loja em que as peças voltaram."""
    dia_inicial = ler_data(de, "de")
    dia_final = ler_data(ate, "ate")
    if dia_inicial and dia_final and dia_final < dia_inicial:
        raise DadosInvalidos("A data final deve ser igual ou posterior à inicial.")
    return devolucao_repository.listar(
        db,
        desde=inicio_do_dia(dia_inicial) if dia_inicial else None,
        ate=fim_do_dia(dia_final) if dia_final else None,
        loja_id=loja_id,
    )
