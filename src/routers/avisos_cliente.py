"""Avisos do cliente logado: "Avise-me quando chegar", a cópia da sacola e a preferência de e-mails de
novidades. Regras em src/use_cases/avisos_cliente.py (decisões 99 e 100)."""

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import cliente_atual
from src.schemas.comum import Entrada
from src.use_cases import avisos_cliente

router = APIRouter(prefix="/conta", tags=["Conta do cliente"])


class AvisoEntrada(Entrada):
    variacao_id: int


class ItemSacola(Entrada):
    variacao_id: int
    quantidade: int = Field(ge=1, le=99)


class SacolaEntrada(Entrada):
    itens: list[ItemSacola] = Field(default_factory=list, max_length=100)


class PreferenciasEntrada(Entrada):
    aceita_marketing: bool


@router.get("/avisos-estoque")
def avisos(db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """{ variacaoIds }: as peças com "Avise-me" pendente."""
    return {"variacaoIds": avisos_cliente.pendentes_do_cliente(db, cliente.id)}


@router.post("/avisos-estoque", status_code=201)
def pedir_aviso(dados: AvisoEntrada, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """{ variacaoId }. Pedir de novo não duplica. Peça disponível: 409; inexistente ou fora do site: 404."""
    avisos_cliente.pedir_aviso(db, cliente.id, dados.variacao_id)
    return {"variacaoIds": avisos_cliente.pendentes_do_cliente(db, cliente.id)}


@router.delete("/avisos-estoque/{variacao_id}", status_code=204, response_class=Response)
def cancelar_aviso(variacao_id: int, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    avisos_cliente.cancelar_aviso(db, cliente.id, variacao_id)


@router.get("/sacola")
def sacola(db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """{ itens }: a sacola guardada, no formato da sacola do site (só peças à venda)."""
    return {"itens": avisos_cliente.sacola_do_cliente(db, cliente.id)}


@router.put("/sacola", status_code=204, response_class=Response)
def salvar_sacola(dados: SacolaEntrada, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """{ itens: [{ variacaoId, quantidade }] }. Vazia apaga a cópia."""
    avisos_cliente.salvar_sacola(db, cliente.id, [(i.variacao_id, i.quantidade) for i in dados.itens])


@router.get("/preferencias")
def preferencias(cliente: m.Cliente = Depends(cliente_atual)):
    """{ aceitaMarketing }: e-mails de novidades e lembretes (LGPD: só com o "sim" do cliente)."""
    return {"aceitaMarketing": bool(cliente.aceita_marketing)}


@router.put("/preferencias")
def salvar_preferencias(dados: PreferenciasEntrada, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    registro = db.get(m.Cliente, cliente.id)
    registro.aceita_marketing = dados.aceita_marketing
    db.commit()
    return {"aceitaMarketing": registro.aceita_marketing}
