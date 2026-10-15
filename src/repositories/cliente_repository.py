"""Clientes da loja e links de troca de senha."""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src import models as m
from src.entities.cliente import normalizar_email
from src.repositories import sessao


def por_id(db: Session, cliente_id: int) -> m.Cliente | None:
    return db.get(m.Cliente, cliente_id)


def por_email(db: Session, email: str) -> m.Cliente | None:
    return db.scalar(select(m.Cliente).where(m.Cliente.email == normalizar_email(email)))


def por_cpf(db: Session, cpf: str) -> m.Cliente | None:
    return db.scalar(select(m.Cliente).where(m.Cliente.cpf == cpf))


def por_telefone(db: Session, e164: str) -> list[m.Cliente]:
    """Clientes com esse telefone (E.164), qualquer que seja a máscara gravada: os da Casa Lorenzi vêm
    como "(11) 98422-1937"; os da Vulto, como "+5511984221937"."""
    nacional = e164.removeprefix("+55")
    digitos = func.regexp_replace(m.Cliente.telefone, r"\D", "", "g")
    return list(db.scalars(select(m.Cliente).where(digitos.in_((nacional, f"55{nacional}"))).order_by(m.Cliente.id)))


def conta_pontos(db: Session, cliente_id: int) -> m.ContaPontos | None:
    return db.scalar(select(m.ContaPontos).where(m.ContaPontos.cliente_id == cliente_id))


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
    loja_preferida_id: int | None = None,
    cpf: str | None = None,
    senha_hash: str | None = None,
) -> m.Cliente:
    """Adiciona o cliente à transação (sem confirmar). O e-mail é gravado normalizado."""
    cliente = m.Cliente(
        nome=nome.strip(),
        email=normalizar_email(email),
        telefone=(telefone or "").strip() or None,
        cpf=cpf,
        senha_hash=senha_hash,
        loja_preferida_id=loja_preferida_id,
    )
    sessao.adicionar(db, cliente)
    return cliente


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
