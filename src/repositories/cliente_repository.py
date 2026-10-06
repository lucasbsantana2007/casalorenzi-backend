"""Clientes da loja (sem login) e links de troca de PIN."""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src import models as m
from src.entities.cliente import normalizar_email
from src.repositories import sessao


def por_id(db: Session, cliente_id: int) -> m.Cliente | None:
    return db.get(m.Cliente, cliente_id)


def por_email(db: Session, email: str, travar: bool = False) -> m.Cliente | None:
    """travar=True bloqueia a linha (conferência de PIN: o contador de tentativas não pode se perder)."""
    consulta = select(m.Cliente).where(m.Cliente.email == normalizar_email(email))
    if travar:
        consulta = consulta.with_for_update(of=m.Cliente)
    return db.scalar(consulta)


def listar(db: Session, busca: str | None = None, limite: int = 50) -> list[m.Cliente]:
    consulta = select(m.Cliente).order_by(m.Cliente.nome, m.Cliente.id).limit(limite)
    if busca and busca.strip():
        termo = f"%{busca.strip().lower()}%"
        consulta = consulta.where(or_(m.Cliente.nome.ilike(termo), m.Cliente.email.like(termo), m.Cliente.telefone.like(termo)))
    return list(db.scalars(consulta))


def criar(
    db: Session,
    *,
    nome: str,
    email: str,
    telefone: str | None = None,
    pin_hash: str | None = None,
    loja_preferida_id: int | None = None,
) -> m.Cliente:
    """Adiciona o cliente à transação (sem confirmar). O e-mail é gravado normalizado."""
    cliente = m.Cliente(
        nome=nome.strip(),
        email=normalizar_email(email),
        telefone=(telefone or "").strip() or None,
        pin_hash=pin_hash,
        tentativas_pin=0,
        loja_preferida_id=loja_preferida_id,
    )
    sessao.adicionar(db, cliente)
    return cliente


def token_pin(db: Session, token: str, travar: bool = False) -> m.TokenPin | None:
    consulta = select(m.TokenPin).where(m.TokenPin.token == token)
    if travar:
        consulta = consulta.with_for_update(of=m.TokenPin)
    return db.scalar(consulta)


def criar_token_pin(db: Session, cliente: m.Cliente, token: str, expira_em: datetime) -> m.TokenPin:
    registro = m.TokenPin(cliente=cliente, token=token, expira_em=expira_em)
    sessao.adicionar(db, registro)
    return registro
