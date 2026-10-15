from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.loja import Loja


class Cliente(Base):
    """Cliente da loja (das duas marcas: a mesma pessoa é um registro só). Não é usuário da equipe:
    entra com a própria conta (CPF, e-mail, senha). Ver src/entities/cliente.py.
    Clientes que vieram da Vulto podem não ter e-mail (só CPF ou telefone): sem e-mail não há login,
    mas o cliente precisa de pelo menos um jeito de ser identificado."""

    __tablename__ = "clientes"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_clientes_email_minusculo"),
        CheckConstraint("cpf IS NULL OR cpf ~ '^[0-9]{11}$'", name="ck_clientes_cpf"),
        CheckConstraint("cpf IS NOT NULL OR email IS NOT NULL OR telefone IS NOT NULL", name="ck_clientes_identificador"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    telefone: Mapped[str | None] = mapped_column(String(30))
    # Conta do cliente: CPF (só dígitos) e hash da senha. Nulos nos clientes antigos, sem conta.
    cpf: Mapped[str | None] = mapped_column(String(11), unique=True)
    senha_hash: Mapped[str | None] = mapped_column(String(255))
    cliente_desde: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    loja_preferida_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Conta excluída pelo próprio cliente: os dados pessoais são apagados e o histórico de
    # pedidos e chamados fica anônimo (necessário para o financeiro e o fiscal)
    excluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Consentimento para mensagens de marketing (LGPD). Na dúvida, sem consentimento: só vira true
    # com um aceite registrado, guardando quando e de onde veio (ex.: "vulto:aceita_msg")
    aceita_marketing: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    aceita_marketing_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aceita_marketing_origem: Mapped[str | None] = mapped_column(String(60))

    loja_preferida: Mapped[Loja | None] = relationship(lazy="joined")
