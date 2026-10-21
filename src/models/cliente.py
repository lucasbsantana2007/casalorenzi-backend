from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.cliente import problemas_do_cadastro
from src.entities.pedido import CANAIS
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.loja import Loja


class Cliente(Base):
    """Cliente das duas marcas: a mesma pessoa é um registro só, e a chave é o CPF. Não é usuário da
    equipe: entra com a própria conta (CPF, e-mail, senha). Ver src/entities/cliente.py.

    O e-mail não é único: na Vulto há e-mails usados por duas pessoas da mesma família (decisão 53 do
    registro da Vulto). E-mail repetido não serve para entrar; quem tem um entra pelo CPF.
    Clientes que vieram só do sistema de pontos da Vulto não têm e-mail: só o CPF."""

    __tablename__ = "clientes"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_clientes_email_minusculo"),
        CheckConstraint("cpf IS NULL OR cpf ~ '^[0-9]{11}$'", name="ck_clientes_cpf"),
        # Todo cliente precisa de um jeito de ser identificado (a conta excluída tem os dados apagados)
        CheckConstraint("excluido_em IS NOT NULL OR cpf IS NOT NULL OR email IS NOT NULL", name="ck_clientes_identificacao"),
        # Nulo quando não se sabe (os clientes da Casa Lorenzi de antes da união); o IN do SQL aceita NULL
        CheckConstraint(valor_em("canal_cadastro", CANAIS), name="ck_clientes_canal_cadastro"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    telefone: Mapped[str | None] = mapped_column(String(30))
    # Conta do cliente: CPF (só dígitos) e hash da senha. Nulos nos clientes antigos, sem conta.
    # CPF com dígito verificador inválido é guardado (a empresa deve os pontos dele) e marcado em atualizar_cadastro
    cpf: Mapped[str | None] = mapped_column(String(11), unique=True)
    senha_hash: Mapped[str | None] = mapped_column(String(255))
    cliente_desde: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    loja_preferida_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"))
    # Onde o cliente se cadastrou: Loja física (a loja fica em loja_preferida_id), E-commerce ou App
    canal_cadastro: Mapped[str | None] = mapped_column(String(20))
    # Consentimento para mensagens de marketing (LGPD): só true com um "sim" registrado
    aceita_marketing: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # No próximo login, o cliente precisa corrigir o cadastro antes de usar os benefícios
    # (ex.: CPF inválido, decisão 52 do registro da Vulto)
    atualizar_cadastro: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Anotações da equipe (ex.: "estava bloqueado no programa antigo", "não ligar")
    observacao: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Conta excluída pelo próprio cliente: os dados pessoais são apagados e o histórico de
    # pedidos e chamados fica anônimo (necessário para o financeiro e o fiscal)
    excluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    loja_preferida: Mapped[Loja | None] = relationship(lazy="joined")

    @property
    def problemas_cadastro(self) -> list[str]:
        """O que o cliente precisa corrigir no cadastro (src/entities/cliente.py). A conta excluída não tem dados."""
        if self.excluido_em is not None:
            return []
        return problemas_do_cadastro(self.cpf, self.email, self.telefone)

    @property
    def dados_validos(self) -> bool:
        return not self.problemas_cadastro
