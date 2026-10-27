"""Helo: saldo, extrato, vencimento, crédito das compras, estorno e resgate no checkout.
Regras em src/entities/fidelidade.py.

O saldo nunca é editado: cada mudança é um movimento com o saldo resultante. Quem lança precisa ter
travado o cliente antes (travar), para duas operações simultâneas não usarem o mesmo saldo.

Vencimento (decisão 22): cada entrada de pontos vence 12 meses depois de ganha (vence_em), e toda
saída (resgate, estorno, vencimento) gasta primeiro as entradas mais antigas. O que sobrou de uma
entrada vencida vira um movimento VENCIMENTO, lançado na primeira vez que o cliente é consultado ou
compra depois do vencimento. É a mesma conta da migração, que já trouxe vencido tudo até 01/10/2026.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src import models as m
from src.entities import fidelidade as regra
from src.repositories import fidelidade_repository, sessao
from src.utils.datas import agora
from src.utils.erros import DadosInvalidos


def _brl(valor: Decimal) -> str:
    return f"R$ {valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def vence_em(quando: datetime) -> date:
    """12 meses depois do dia em que os pontos foram ganhos (29/02 vira 28/02)."""
    dia = quando.date()
    try:
        return dia.replace(year=dia.year + regra.VALIDADE_MESES // 12)
    except ValueError:
        return dia.replace(year=dia.year + regra.VALIDADE_MESES // 12, day=28)


def travar(db: Session, cliente_id: int) -> None:
    fidelidade_repository.travar_cliente(db, cliente_id)


def lancar(
    db: Session,
    cliente_id: int,
    tipo: str,
    quantidade: int,
    quando: datetime,
    *,
    pedido: m.Pedido | None = None,
    valor_desconto: Decimal | None = None,
    obs: str = "",
) -> m.MovimentoPontos:
    """Grava o movimento com o novo saldo. Quem chama já travou o cliente."""
    novo_saldo = fidelidade_repository.saldo(db, cliente_id) + quantidade
    if novo_saldo < 0:
        raise DadosInvalidos("O saldo de pontos não pode ficar negativo.")
    movimento = m.MovimentoPontos(
        cliente_id=cliente_id,
        tipo=tipo,
        quantidade=quantidade,
        saldo_resultante=novo_saldo,
        vence_em=vence_em(quando) if quantidade > 0 else None,
        pedido=pedido,
        valor_desconto=valor_desconto,
        obs=obs,
        criado_em=quando,
    )
    sessao.adicionar(db, movimento)
    sessao.gerar_ids(db)  # o próximo lançamento na mesma transação já enxerga este saldo
    return movimento


@dataclass
class _Lote:
    vence_em: date
    restante: int


def _lotes_em_aberto(movimentos: list[m.MovimentoPontos]) -> list[_Lote]:
    """Entradas com o que ainda não foi gasto, gastando primeiro as mais antigas."""
    lotes: list[_Lote] = []
    for mov in movimentos:
        if mov.quantidade > 0:
            lotes.append(_Lote(mov.vence_em or vence_em(mov.criado_em), mov.quantidade))
            continue
        saida = -mov.quantidade
        for lote in sorted(lotes, key=lambda aberto: aberto.vence_em):
            if not saida:
                break
            usado = min(lote.restante, saida)
            lote.restante -= usado
            saida -= usado
        lotes = [lote for lote in lotes if lote.restante]
    return lotes


def lotes_em_aberto(movimentos) -> list[tuple[date, int]]:
    """(vencimento, pontos) do que ainda não foi gasto de cada entrada, pela regra acima. Só calcula: não
    lança nada. movimentos: do extrato de um cliente, em ordem (com quantidade, vence_em e criado_em)."""
    return [(lote.vence_em, lote.restante) for lote in _lotes_em_aberto(movimentos)]


def vencer(db: Session, cliente_id: int, hoje: date | None = None) -> int:
    """Lança como VENCIMENTO o que sobrou das entradas vencidas. Devolve quantos pontos venceram.
    Quem chama já travou o cliente."""
    hoje = hoje or agora().date()
    vencidos = [lote for lote in _lotes_em_aberto(fidelidade_repository.movimentos(db, cliente_id)) if lote.vence_em < hoje]
    total = sum(lote.restante for lote in vencidos)
    if total:
        datas = sorted({lote.vence_em for lote in vencidos})
        quando = f"em {datas[0]:%d/%m/%Y}" if len(datas) == 1 else f"de {datas[0]:%d/%m/%Y} a {datas[-1]:%d/%m/%Y}"
        lancar(db, cliente_id, "VENCIMENTO", -total, agora(), obs=f"Pontos ganhos há mais de 12 meses, vencidos {quando}")
    return total


@dataclass
class Resumo:
    saldo: int
    categoria: str | None
    valor_em_reais: Decimal
    a_vencer: list[tuple[date, int]]  # (data, pontos) dos próximos vencimentos
    movimentos: list[m.MovimentoPontos]


def resumo(db: Session, cliente: m.Cliente) -> Resumo:
    """Saldo, categoria, valor e extrato, já com o vencimento em dia (grava o vencimento, se houver)."""
    travar(db, cliente.id)
    if vencer(db, cliente.id):
        sessao.confirmar(db)
    saldo = fidelidade_repository.saldo(db, cliente.id)
    proximos: dict[date, int] = {}
    for lote in _lotes_em_aberto(fidelidade_repository.movimentos(db, cliente.id)):
        proximos[lote.vence_em] = proximos.get(lote.vence_em, 0) + lote.restante
    return Resumo(
        saldo=saldo,
        categoria=regra.categoria_pelo_saldo(saldo),
        valor_em_reais=regra.valor_em_reais(saldo),
        a_vencer=sorted(proximos.items())[:3],
        movimentos=fidelidade_repository.extrato(db, cliente.id),
    )


# ---------- Checkout ----------


def conferir_resgate(db: Session, cliente: m.Cliente, valor_produtos: Decimal, pontos: int) -> Decimal:
    """Desconto do resgate pedido no checkout (zero sem pontos). Trava o cliente até o fim da compra."""
    if not pontos:
        return Decimal("0")
    if pontos < 0 or pontos % regra.RESGATE_MULTIPLO:
        multiplo = regra.RESGATE_MULTIPLO
        raise DadosInvalidos(f"Use os pontos Helo a partir de {multiplo} e em múltiplos de {multiplo}.")
    if not regra.pode_resgatar(valor_produtos):
        minimo = _brl(regra.COMPRA_MINIMA_RESGATE)
        raise DadosInvalidos(f"Para usar pontos Helo, a compra precisa ter pelo menos {minimo} em produtos (sem o frete).")
    travar(db, cliente.id)
    vencer(db, cliente.id)
    saldo = fidelidade_repository.saldo(db, cliente.id)
    if pontos > saldo:
        raise DadosInvalidos(f"Saldo Helo insuficiente: você tem {saldo} pontos.")
    maximo = regra.maximo_resgatavel(saldo, valor_produtos)
    if pontos > maximo:
        raise DadosInvalidos(f"Nesta compra dá para usar no máximo {maximo} pontos (o desconto não passa do valor dos produtos).")
    return regra.desconto_do_resgate(pontos)


def registrar_resgate(db: Session, cliente: m.Cliente, pedido: m.Pedido, pontos: int, quando: datetime) -> None:
    desconto = regra.desconto_do_resgate(pontos)
    lancar(
        db,
        cliente.id,
        "RESGATE",
        -pontos,
        quando,
        pedido=pedido,
        valor_desconto=desconto,
        obs=f"Desconto de {_brl(desconto)} no pedido {pedido.numero}",
    )


def creditar_compra(db: Session, cliente: m.Cliente, pedido: m.Pedido, quando: datetime) -> int:
    """Pontos da compra com o pagamento aprovado: produtos × canal × bônus da categoria de antes da compra.
    Quem chama já travou o cliente. Devolve os pontos creditados."""
    vencer(db, cliente.id)
    categoria = regra.categoria_pelo_saldo(fidelidade_repository.saldo(db, cliente.id))
    pontos = regra.pontos_da_compra(pedido.subtotal, pedido.canal, categoria)
    if pontos <= 0:
        return 0
    bonus = regra.BONUS_CATEGORIA.get(categoria or "")
    detalhe = f" (bônus {categoria.title()} +{int(bonus * 100)}%)" if bonus else ""
    lancar(db, cliente.id, "CREDITO", pontos, quando, pedido=pedido, obs=f"Compra {pedido.numero}{detalhe}")
    return pontos


# ---------- Cancelamento e devolução ----------


def estornar_compra(db: Session, pedido: m.Pedido, quando: datetime, *, fracao: Decimal = Decimal("1"), motivo: str) -> int:
    """Tira os pontos ganhos na compra (toda ou a fração devolvida), sem deixar o saldo negativo:
    se o cliente já usou parte deles, sai o que der. Devolve quantos pontos saíram."""
    if pedido.cliente_id is None:
        return 0
    ganhos = fidelidade_repository.total_no_pedido(db, pedido.id, "CREDITO")
    ja_estornado = -fidelidade_repository.total_no_pedido(db, pedido.id, "ESTORNO")
    alvo = min(int((ganhos * fracao).quantize(Decimal("1"), rounding="ROUND_HALF_UP")), ganhos - ja_estornado)
    if alvo <= 0:
        return 0
    travar(db, pedido.cliente_id)
    pontos = min(alvo, fidelidade_repository.saldo(db, pedido.cliente_id))
    if pontos <= 0:
        return 0
    falta = f" ({alvo - pontos} já tinham sido usados)" if pontos < alvo else ""
    lancar(db, pedido.cliente_id, "ESTORNO", -pontos, quando, pedido=pedido, obs=f"{motivo}{falta}")
    return pontos


def devolver_resgate(db: Session, pedido: m.Pedido, quando: datetime) -> int:
    """Pedido cancelado: os pontos usados nele voltam (com 12 meses de validade a partir de hoje)."""
    pontos = -fidelidade_repository.total_no_pedido(db, pedido.id, "RESGATE")
    ja_devolvidos = sum(
        mov.quantidade
        for mov in fidelidade_repository.movimentos(db, pedido.cliente_id or 0)
        if mov.pedido_id == pedido.id and mov.tipo == "AJUSTE" and mov.quantidade > 0
    )
    pontos -= ja_devolvidos
    if pontos <= 0 or pedido.cliente_id is None:
        return 0
    travar(db, pedido.cliente_id)
    obs = f"Pedido {pedido.numero} cancelado: pontos do resgate devolvidos"
    lancar(db, pedido.cliente_id, "AJUSTE", pontos, quando, pedido=pedido, obs=obs)
    return pontos
