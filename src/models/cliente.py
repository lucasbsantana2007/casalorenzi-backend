from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.loja import Loja


class Cliente(Base):
    """Cliente da loja. Não é usuário da equipe: entra com a própria conta (CPF, e-mail, senha). Ver src/entities/cliente.py."""

    __tablename__ = "clientes"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_clientes_email_minusculo"),
        CheckConstraint("tentativas_pin >= 0", name="ck_clientes_tentativas_pin"),
        CheckConstraint("cpf IS NULL OR cpf ~ '^[0-9]{11}$'", name="ck_clientes_cpf"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    telefone: Mapped[str | None] = mapped_column(String(30))
    # Conta do cliente: CPF (só dígitos) e hash da senha. Nulos nos clientes antigos, sem conta.
    cpf: Mapped[str | None] = mapped_column(String(11), unique=True)
    senha_hash: Mapped[str | None] = mapped_column(String(255))
    # Só o hash do PIN de 4 dígitos (bcrypt). Nulo até o cliente criar um PIN.
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    tentativas_pin: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cliente_desde: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    loja_preferida_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Conta excluída pelo próprio cliente: os dados pessoais são apagados e o histórico de
    # pedidos e chamados fica anônimo (necessário para o financeiro e o fiscal)
    excluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    loja_preferida: Mapped[Loja | None] = relationship(lazy="joined")
