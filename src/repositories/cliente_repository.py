"""Clientes da loja, links de troca de PIN (legado) e de troca de senha."""

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


def por_cpf(db: Session, cpf: str) -> m.Cliente | None:
    return db.scalar(select(m.Cliente).where(m.Cliente.cpf == cpf))


def listar(db: Session, busca: str | None = None, limite: int = 50) -> list[m.Cliente]:
    consulta = select(m.Cliente).where(m.Cliente.excluido_em.is_(None)).order_by(m.Cliente.nome, m.Cliente.id).limit(limite)
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
    cpf: str | None = None,
    senha_hash: str | None = None,
) -> m.Cliente:
    """Adiciona o cliente à transação (sem confirmar). O e-mail é gravado normalizado."""
    cliente = m.Cliente(
        nome=nome.strip(),
        email=normalizar_email(email),
        telefone=(telefone or "").strip() or None,
        pin_hash=pin_hash,
        tentativas_pin=0,
        cpf=cpf,
        senha_hash=senha_hash,
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


def token_senha(db: Session, token: str, travar: bool = False) -> m.TokenSenha | None:
    consulta = select(m.TokenSenha).where(m.TokenSenha.token == token)
    if travar:
        consulta = consulta.with_for_update(of=m.TokenSenha)
    return db.scalar(consulta)


def criar_token_senha(
    db: Session, token: str, expira_em: datetime, *, usuario: m.Usuario | None = None, cliente: m.Cliente | None = None
) -> m.TokenSenha:
    registro = m.TokenSenha(token=token, usuario=usuario, cliente=cliente, expira_em=expira_em)
    sessao.adicionar(db, registro)
    return registro


def tokens_senha_pendentes(db: Session, *, usuario_id: int | None = None, cliente_id: int | None = None) -> list[m.TokenSenha]:
    """Links ainda não usados da mesma conta (um link usado invalida os outros)."""
    consulta = select(m.TokenSenha).where(m.TokenSenha.usado_em.is_(None))
    if usuario_id is not None:
        consulta = consulta.where(m.TokenSenha.usuario_id == usuario_id)
    else:
        consulta = consulta.where(m.TokenSenha.cliente_id == cliente_id)
    return list(db.scalars(consulta))


def tokens_pin_pendentes(db: Session, cliente_id: int) -> list[m.TokenPin]:
    return list(db.scalars(select(m.TokenPin).where(m.TokenPin.cliente_id == cliente_id, m.TokenPin.usado_em.is_(None))))
