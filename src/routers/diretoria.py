"""Números da diretoria sobre a Vulto (faturamento, estoque e passivo de pontos), com explicação, decisões
e margem de erro. Só o administrador (módulo financeiro)."""

from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.use_cases import diretoria

router = APIRouter(prefix="/diretoria", tags=["Diretoria"])
acesso = exigir_modulo("financeiro")


@router.get("/numeros")
def obter_numeros(db: Session = Depends(get_db), _: m.Usuario = Depends(acesso)):
    """As três respostas para a diretoria:
    - `faturamento`: jan/2025 a set/2026, sem frete, por mês, loja e canal, e a `ponte` do relatório do sistema
      da Vulto até o nosso número, passo a passo (também mês a mês em `ponteMensal`);
    - `estoque`: em 01/10/2026, por loja/CD (com a composição: abertura, entradas, transferências, vendas,
      devoluções, ajuste da contagem) e por produto;
    - `passivo`: pontos do Vulto+ em 01/10/2026, em pontos e R$, com os cenários e a faixa.
    Cada uma traz `pergunta`, `resposta`, `decisoes` e `margem`."""
    return diretoria.numeros(db)


@router.get("/numeros/{secao}.csv")
def baixar_csv(
    secao: Literal["faturamento", "ponte", "estoque-lojas", "estoque-produtos", "passivo"],
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
):
    """Uma seção em CSV para o Excel em português: separador ";", vírgula decimal, UTF-8 com BOM."""
    conteudo = diretoria.csv_da_secao(diretoria.numeros(db), secao)
    return Response(
        conteudo.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="vulto_{secao}.csv"'},
    )
