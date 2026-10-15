from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.use_cases import faturamento, fidelidade, financeiro

router = APIRouter(prefix="/financeiro", tags=["Financeiro"])


@router.get("/resumo")
def obter_resumo(
    de: str | None = None,
    ate: str | None = None,
    comparar: Literal["anterior", "ano", "nenhum"] = "anterior",
    agrupar: Literal["dia", "semana", "mes"] = "dia",
    lojas: str | None = None,
    canais: str | None = None,
    categorias: str | None = None,
    generos: str | None = None,
    marcas: str | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(exigir_modulo("financeiro")),
):
    """Filtros em listas separadas por vírgula (ex.: lojas=1,3&canais=E-commerce&marcas=VULTO).
    Sem `marcas`, soma a Casa Lorenzi e a Vulto; `marcas=LORENZI` ou `marcas=VULTO` separa uma da outra."""
    return financeiro.resumo(
        db,
        de=de,
        ate=ate,
        comparar=comparar,
        agrupar=agrupar,
        lojas=lojas,
        canais=canais,
        categorias=categorias,
        generos=generos,
        marcas=marcas,
    )


@router.get("/faturamento")
def obter_faturamento(
    de: str | None = None,
    ate: str | None = None,
    marca: Literal["LORENZI", "VULTO"] | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(exigir_modulo("financeiro")),
):
    """Faturamento por mês × loja × canal (padrão: jan/2025 a set/2026), com e sem frete. Receita = vendas
    não canceladas e com pagamento que não está só pendente; trocas não são receita; devoluções saem na
    data em que aconteceram (líquido). Devolução da Vulto sem venda de origem: canal "Sem origem"."""
    return faturamento.faturamento(db, de, ate, marca)


@router.get("/faturamento/comparativo-vulto")
def obter_comparativo_vulto(
    de: str | None = None,
    ate: str | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(exigir_modulo("financeiro")),
):
    """ "Sistema da Vulto × nosso número", mês a mês: o /relatorio/faturamento do sistema antigo refeito
    sobre os dados originais, os ajustes que explicam a diferença (centavos, cancelados, aguardando,
    trocas, devoluções, testes, duplicatas, Batel, fuso, outros) e o nosso faturamento líquido com e sem
    frete. sistemaVulto + soma dos ajustes = nossoComFrete."""
    return faturamento.comparativo_vulto(db, de, ate)


@router.get("/vulto-mais/passivo")
def obter_passivo_vulto_mais(
    data: str | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(exigir_modulo("financeiro")),
):
    """Passivo de pontos do Vulto+ na data (padrão: 01/10/2026, a virada): pontos válidos com a validade
    FIFO (Ouro 12 e Ouro 18 meses), em reais pelo valor vigente (R$ 0,05) e pelo antigo (R$ 0,10), e a faixa
    mínima/vigente/máxima com o critério de cada uma. Na data da virada, o máximo soma o que o sistema da
    Vulto nunca aplicou (dobro do online, bônus Ouro) e o mínimo tira os resgates anotados sem CPF."""
    return fidelidade.passivo(db, data)
