"""Frete: condições públicas para o site e configuração do Administrador (Administração > Frete)."""

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.schemas.comum import Entrada
from src.use_cases import frete

router = APIRouter(prefix="/frete", tags=["Frete"])
acesso_admin = exigir_modulo("administracao")


class SimulacaoEntrada(Entrada):
    cep: str = ""
    subtotal: float = 0


@router.get("/condicoes")
def condicoes(db: Session = Depends(get_db)):
    """Público, sem custo: { gratisMinimo, expressoAtivo, regioes: [{ regiao, nome, padrao, expresso }] }."""
    return frete.condicoes(db)


@router.get("/config")
def obter_config(db: Session = Depends(get_db), _: m.Usuario = Depends(acesso_admin)):
    """Administrador: a mesma estrutura das condições, com `custo` em cada faixa."""
    return frete.config_completa(db)


@router.put("/config")
def salvar_config(dados: dict = Body(...), db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso_admin)):
    """Administrador. Valida tudo antes de gravar; cada valor alterado vai para o log."""
    return frete.salvar(db, usuario, dados)


@router.post("/simulacao")
def simular(dados: SimulacaoEntrada, db: Session = Depends(get_db), _: m.Usuario = Depends(acesso_admin)):
    """Administrador. { cep, subtotal } → [{ tipo, label, valor, custo, prazoDias, resultado }]."""
    return frete.simular(db, dados.cep, dados.subtotal)
