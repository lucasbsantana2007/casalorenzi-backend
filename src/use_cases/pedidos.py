"""Pedidos do e-commerce no painel (módulo pedidos) e regras usadas também pelo checkout.

Expedição: cada pedido sai de uma loja. Quando falta peça nela, o sistema cria transferências
automáticas (SOLICITADA) das lojas que têm a peça. O envio só é liberado com todas as peças na
loja de expedição; aí elas saem do estoque (movimentação VENDA).

Mudanças de status (src/entities/pedido.py):
    PROCESSANDO → ENVIADO (código de rastreio) → ENTREGUE
    PROCESSANDO → CANCELADO (estorna o pagamento e cancela as transferências ainda não enviadas)
"""

from datetime import datetime

from sqlalchemy.orm import Session

from src import models as m
from src.entities.frete import uf_do_cep
from src.entities.papeis import ADMINISTRADOR, loja_do_escopo, ve_pedido_da_loja
from src.entities.pedido import STATUS_PEDIDO, pode_mudar, pontuar_loja
from src.entities.transferencia import pode_mudar as transferencia_pode_mudar
from src.repositories import cadastro_repository, estoque_repository, pedido_repository, sessao
from src.use_cases import log_acoes, transferencias
from src.use_cases.estoque import aplicar_movimentacao
from src.use_cases.pagamentos import estornar_aprovados
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos, NaoEncontrado, SemPermissao
from src.utils.texto import corresponde

RASTREIO_MAX = 40


# ---------- Regras compartilhadas com o checkout ----------


def registrar_evento(
    db: Session,
    pedido: m.Pedido,
    status: str,
    *,
    usuario_id: int | None = None,
    observacao: str = "",
    quando: datetime | None = None,
) -> m.EventoPedido:
    """Entrada no histórico do pedido (sem confirmar)."""
    evento = m.EventoPedido(
        pedido=pedido, status=status, usuario_id=usuario_id, observacao=observacao, criado_em=quando or agora()
    )
    sessao.adicionar(db, evento)
    return evento


def saldo_na_loja(db: Session, loja_id: int, variacao_id: int) -> int:
    estoque = estoque_repository.por_loja_e_variacao(db, loja_id, variacao_id)
    return estoque.quantidade if estoque else 0


def escolher_loja_expedicao(db: Session, itens: list[tuple[int, int]], cep: str) -> m.Loja:
    """Loja que tem mais itens da sacola em estoque; empate → mesma UF do CEP; depois, a de menor id.
    itens: (variacao_id, quantidade)."""
    uf = uf_do_cep(cep)

    def pontos(loja: m.Loja) -> int:
        cobertos = sum(1 for variacao_id, quantidade in itens if saldo_na_loja(db, loja.id, variacao_id) >= quantidade)
        return pontuar_loja(cobertos, loja.uf == uf)

    lojas = cadastro_repository.lojas(db, somente_ativas=True)  # loja desativada não despacha
    if not lojas:
        raise Conflito("Nenhuma loja disponível para expedir o pedido.")
    return max(lojas, key=lambda loja: (pontos(loja), -loja.id))


def planejar_transferencias(db: Session, pedido: m.Pedido) -> list[m.Transferencia]:
    """Transferências das outras lojas para a de expedição, para cada peça que falta nela (sem confirmar).
    Pega primeiro das lojas com mais saldo."""
    criadas = []
    for item in pedido.itens:
        falta = item.quantidade - saldo_na_loja(db, pedido.loja_id, item.variacao_id)
        doadoras = sorted(
            (
                e
                for e in estoque_repository.da_variacao(db, item.variacao_id)
                if e.loja_id != pedido.loja_id and e.quantidade > 0 and e.loja.ativa
            ),
            key=lambda e: (-e.quantidade, e.loja_id),
        )
        for estoque in doadoras:
            if falta <= 0:
                break
            quantidade = min(falta, estoque.quantidade)
            t = transferencias.nova(
                db,
                variacao_id=item.variacao_id,
                loja_origem_id=estoque.loja_id,
                loja_destino_id=pedido.loja_id,
                quantidade=quantidade,
                solicitante_id=None,
                observacao=f"Automática para o pedido {pedido.numero}",
            )
            t.pedido_id = pedido.id
            criadas.append(t)
            falta -= quantidade
    return criadas


def _cancelar_transferencias_pendentes(pedido: m.Pedido) -> None:
    """Só as que ainda não saíram da loja de origem (SOLICITADA); as em trânsito seguem o fluxo normal."""
    for t in pedido.transferencias:
        if t.status == "SOLICITADA" and transferencia_pode_mudar(t.status, "CANCELADA"):
            t.status = "CANCELADA"


# ---------- Painel ----------


def conferir_acesso(usuario: m.Usuario, pedido: m.Pedido | None) -> m.Pedido:
    """Pedido de outra loja aparece como inexistente para Lojista e Operador (404)."""
    if pedido is None or not ve_pedido_da_loja(usuario.papel, usuario.loja_id, pedido.loja_id):
        raise NaoEncontrado("Pedido não encontrado.")
    return pedido


def listar(
    db: Session,
    usuario: m.Usuario,
    *,
    status: str | None = None,
    loja_id: int | None = None,
    canal: str | None = None,
    busca: str | None = None,
) -> list[m.Pedido]:
    """Lojista e Operador recebem só os pedidos da própria loja, qualquer que seja o lojaId pedido."""
    if status and status not in STATUS_PEDIDO:
        raise DadosInvalidos("Status de pedido inválido.")
    escopo = loja_do_escopo(usuario.papel, usuario.loja_id)
    if escopo is not None:
        loja_id = escopo
    pedidos = pedido_repository.listar(db, status=status, loja_id=loja_id, canal=canal)
    return [p for p in pedidos if corresponde(busca, p.numero, p.cliente.nome, p.cliente.email)]


def obter(db: Session, pedido_id: int, usuario: m.Usuario) -> m.Pedido:
    return conferir_acesso(usuario, pedido_repository.obter(db, pedido_id))


def saldos_na_loja(db: Session, pedido: m.Pedido) -> dict[int, int]:
    """Saldo de cada peça do pedido na loja de expedição (o painel mostra o que ainda falta)."""
    return {item.variacao_id: saldo_na_loja(db, pedido.loja_id, item.variacao_id) for item in pedido.itens}


def _log(db: Session, usuario: m.Usuario, pedido: m.Pedido, descricao: str) -> None:
    log_acoes.registrar(db, usuario, "PEDIDOS", "ATUALIZOU", descricao, referencia=("pedido", pedido.id))


def _trocar_loja(db: Session, pedido: m.Pedido, loja_id: int, usuario: m.Usuario, momento: datetime) -> None:
    if pedido.status != "PROCESSANDO":
        raise Conflito("A loja só pode ser trocada antes do envio.")
    loja = cadastro_repository.loja(db, loja_id)
    if loja is None:
        raise DadosInvalidos("Loja inválida.")
    if loja.id == pedido.loja_id:
        return
    if not loja.ativa:
        raise DadosInvalidos("Esta loja está desativada e não expede pedidos.")
    anterior = pedido.loja.nome
    _cancelar_transferencias_pendentes(pedido)
    pedido.loja_id = loja.id
    sessao.gerar_ids(db)
    planejar_transferencias(db, pedido)
    registrar_evento(
        db, pedido, pedido.status, usuario_id=usuario.id, observacao=f"Expedição transferida para {loja.nome}", quando=momento
    )
    _log(db, usuario, pedido, f"Mudou a expedição do pedido {pedido.numero} de {anterior} para {loja.nome}")


def _enviar(db: Session, pedido: m.Pedido, codigo_rastreio: str | None, usuario: m.Usuario, momento: datetime) -> None:
    codigo = (codigo_rastreio or "").strip().upper()
    if not codigo:
        raise DadosInvalidos("Informe o código de rastreio.")
    if len(codigo) > RASTREIO_MAX:
        raise DadosInvalidos(f"O código de rastreio deve ter no máximo {RASTREIO_MAX} caracteres.")
    estoques = [
        (item, estoque_repository.por_loja_e_variacao(db, pedido.loja_id, item.variacao_id, travar=True)) for item in pedido.itens
    ]
    if any(estoque is None or estoque.quantidade < item.quantidade for item, estoque in estoques):
        raise Conflito("Ainda faltam peças na loja de expedição. Conclua as transferências antes de enviar.")
    for item, estoque in estoques:
        aplicar_movimentacao(
            db,
            estoque,
            tipo="VENDA",
            quantidade=-item.quantidade,
            origem=f"Pedido {pedido.numero} (e-commerce)",
            usuario_id=usuario.id,
            quando=momento,
        )
    pedido.status = "ENVIADO"
    pedido.codigo_rastreio = codigo
    registrar_evento(db, pedido, "ENVIADO", usuario_id=usuario.id, observacao=f"Rastreio {codigo}", quando=momento)
    _log(db, usuario, pedido, f"Marcou o pedido {pedido.numero} como enviado (rastreio {codigo})")


def atualizar(
    db: Session,
    pedido_id: int,
    usuario: m.Usuario,
    *,
    loja_id: int | None = None,
    status: str | None = None,
    codigo_rastreio: str | None = None,
) -> m.Pedido:
    """Troca a loja de expedição (loja_id) ou muda o status. Mudança fora do fluxo: 409."""
    pedido = conferir_acesso(usuario, pedido_repository.obter(db, pedido_id, travar=True))
    momento = agora()

    if loja_id is not None:
        if usuario.papel != ADMINISTRADOR:
            raise SemPermissao("Só o administrador troca a loja de expedição.")
        _trocar_loja(db, pedido, loja_id, usuario, momento)
    elif status is None:
        raise DadosInvalidos("Informe a loja de expedição ou o novo status.")
    elif not pode_mudar(pedido.status, status):
        raise Conflito("Mudança de status não permitida.")
    elif status == "ENVIADO":
        _enviar(db, pedido, codigo_rastreio, usuario, momento)
    elif status == "ENTREGUE":
        pedido.status = status
        registrar_evento(db, pedido, status, usuario_id=usuario.id, quando=momento)
        _log(db, usuario, pedido, f"Marcou o pedido {pedido.numero} como entregue")
    else:  # CANCELADO
        _cancelar_transferencias_pendentes(pedido)
        estornar_aprovados(db, pedido, momento)
        pedido.status = status
        registrar_evento(db, pedido, status, usuario_id=usuario.id, observacao="Pagamento estornado", quando=momento)
        _log(db, usuario, pedido, f"Cancelou o pedido {pedido.numero} e estornou o pagamento")

    sessao.confirmar(db)
    sessao.descartar_cache(db)  # volta com eventos, transferências e pagamentos atualizados
    return obter(db, pedido_id, usuario)
