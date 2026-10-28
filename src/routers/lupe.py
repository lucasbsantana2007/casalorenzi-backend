"""Aba Lupe+ do Atendimento (decisão 120): os clientes e quantos pontos cada um tem. Só a equipe que atende
(módulo atendimento: Administrador e Lojista). Regras em src/use_cases/lupe_clientes.py."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.use_cases import lupe_clientes

router = APIRouter(prefix="/lupe", tags=["Lupe+"])
acesso = exigir_modulo("atendimento")


@router.get("/clientes")
def clientes(
    busca: str | None = None,
    categoria: str | None = None,
    ordem: str = "saldo",
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
):
    """{ referencia, clientes, pontos, valorEmReais, itens: [{ id, nome, email, saldo, valorEmReais, categoria,
    proximoVencimento: { data, pontos } }] }. Só quem tem pontos válidos. ordem: saldo (padrão), nome ou vencimento."""
    r = lupe_clientes.listar(db, busca=busca, categoria=categoria, ordem=ordem)
    return {
        "referencia": r["referencia"].isoformat(),
        "clientes": r["clientes"],
        "pontos": r["pontos"],
        "valorEmReais": float(r["valorEmReais"]),
        "itens": [
            {
                "id": linha.cliente.cpf,
                "nome": linha.cliente.nome,
                "email": linha.cliente.email,
                "saldo": linha.saldo,
                "valorEmReais": float(lupe_clientes.regra.valor_em_reais(linha.saldo)),
                "categoria": linha.categoria,
                "proximoVencimento": (
                    {"data": linha.proximo_vencimento[0].isoformat(), "pontos": linha.proximo_vencimento[1]}
                    if linha.proximo_vencimento
                    else None
                ),
            }
            for linha in r["linhas"]
        ],
    }
