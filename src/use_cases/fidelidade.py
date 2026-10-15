"""Vulto+: extrato de pontos do cliente e passivo de pontos consolidado.

O passivo recalcula a validade (FIFO) sobre os movimentos gravados em cada cenário de validade do Ouro (12
ou 18 meses) e valoriza os pontos pelo valor vigente (R$ 0,05) e pelo antigo (R$ 0,10, que o sistema da
Vulto seguiu dando nos resgates). A faixa vai do menor cenário, menos os resgates anotados sem CPF, ao maior,
mais o que o sistema nunca aplicou (dobro do online, bônus Ouro), registrado pela migração na data da virada.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from src import models as m
from src.entities import fidelidade as regra
from src.repositories import fidelidade_repository
from src.utils.datas import inicio_do_dia, ler_data
from src.utils.erros import NaoEncontrado


def extrato(db: Session, cliente: m.Cliente) -> tuple[m.ContaPontos, list[tuple[date, int]]]:
    """Conta com os movimentos e o saldo por data de vencimento (na data da virada)."""
    conta = fidelidade_repository.conta_do_cliente(db, cliente.id)
    if conta is None:
        raise NaoEncontrado("Cliente sem conta Vulto+.")
    movimentos = [(mv.data, mv.quantidade) for mv in conta.movimentos if mv.tipo != "VENCIMENTO"]
    ate = max([inicio_do_dia(regra.DATA_VIRADA), *(data for data, _ in movimentos)])
    return conta, regra.aplicar_validade(movimentos, regra.validade_meses(conta.categoria), ate).a_vencer


def _reais(pontos: int, valor_ponto: Decimal) -> float:
    return float((pontos * valor_ponto).quantize(Decimal("0.01")))


def passivo(db: Session, data: str | None) -> dict:
    dia = ler_data(data) or regra.DATA_VIRADA
    ate = inicio_do_dia(dia)
    contas = fidelidade_repository.movimentos_por_conta(db, ate)

    cenarios = []
    for ouro in regra.VALIDADE_MESES_OURO:
        por_categoria: dict[str, int] = {c: 0 for c in regra.CATEGORIAS_FIDELIDADE}
        com_saldo = 0
        for categoria, movimentos in contas.values():
            saldo = regra.aplicar_validade(movimentos, regra.validade_meses(categoria, ouro), ate).saldo
            por_categoria[categoria or "BRONZE"] += saldo
            com_saldo += saldo > 0
        pontos = sum(por_categoria.values())
        cenarios.append(
            {
                "validadeOuroMeses": ouro,
                "gravado": ouro == regra.VALIDADE_OURO_GRAVADA,
                "pontos": pontos,
                "contasComSaldo": com_saldo,
                "pontosPorCategoria": por_categoria,
                "valorVigente": _reais(pontos, regra.VALOR_PONTO_VIGENTE),
                "valorAntigo": _reais(pontos, regra.VALOR_PONTO_ANTIGO),
            }
        )

    na_virada = dia == regra.DATA_VIRADA
    nao_aplicados = (
        {
            "dobroOnline": fidelidade_repository.impacto_da_migracao(db, "ONLINE_SEM_DOBRO") or 0,
            "bonusOuro": fidelidade_repository.impacto_da_migracao(db, "BONUS_OURO_NUNCA_APLICADO") or 0,
        }
        if na_virada
        else None
    )
    # Resgates anotados na planilha só com o nome: se forem de quem tem saldo, o passivo é menor
    pendentes = -(fidelidade_repository.impacto_da_migracao(db, "RESGATE_SEM_CPF") or 0) if na_virada else 0
    menor = min(cenarios, key=lambda c: c["pontos"])
    gravado = next(c for c in cenarios if c["gravado"])
    maior = max(cenarios, key=lambda c: c["pontos"])
    minimo = max(menor["pontos"] - pendentes, 0)
    maximo = maior["pontos"] + sum((nao_aplicados or {}).values())
    return {
        "data": dia.isoformat(),
        "valorPontoVigente": float(regra.VALOR_PONTO_VIGENTE),
        "valorPontoAntigo": float(regra.VALOR_PONTO_ANTIGO),
        "cenarios": cenarios,
        "naoAplicados": nao_aplicados,
        "resgatesSemCpf": pendentes if na_virada else None,
        "faixa": {
            "minimo": {
                "pontos": minimo,
                "valor": _reais(minimo, regra.VALOR_PONTO_VIGENTE),
                "valorPonto": float(regra.VALOR_PONTO_VIGENTE),
                "criterio": f"Ouro {menor['validadeOuroMeses']} meses, menos os resgates anotados sem CPF, a R$ 0,05",
            },
            "vigente": {
                "pontos": gravado["pontos"],
                "valor": gravado["valorVigente"],
                "valorPonto": float(regra.VALOR_PONTO_VIGENTE),
                "criterio": f"Ouro {gravado['validadeOuroMeses']} meses (o combinado, gravado nas contas), a R$ 0,05",
            },
            "maximo": {
                "pontos": maximo,
                "valor": _reais(maximo, regra.VALOR_PONTO_ANTIGO),
                "valorPonto": float(regra.VALOR_PONTO_ANTIGO),
                "criterio": f"Ouro {maior['validadeOuroMeses']} meses"
                + (", mais o dobro do online e o bônus Ouro que o sistema nunca deu" if nao_aplicados else "")
                + ", a R$ 0,10 (o valor que o sistema da Vulto seguiu dando)",
            },
        },
    }
