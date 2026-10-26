"""Abre e fecha a conexão com o banco."""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config.settings import CONSULTA_TIMEOUT_MS, DATABASE_URL, DATABASE_URL_LEITURA

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# Consultas dos assistentes de IA e das análises das automações: só leitura. Com DATABASE_URL_LEITURA,
# entram com um usuário do Postgres que só tem SELECT; sem ela, usam o mesmo banco, mas cada transação
# é READ ONLY (o Postgres recusa qualquer INSERT, UPDATE ou DELETE) e tem tempo máximo por consulta.
engine_leitura = engine if DATABASE_URL_LEITURA == DATABASE_URL else create_engine(DATABASE_URL_LEITURA, pool_pre_ping=True)
SessionLeitura = sessionmaker(bind=engine_leitura, autoflush=False, expire_on_commit=False)


@event.listens_for(SessionLeitura, "after_begin")
def _somente_leitura(session, transaction, connection) -> None:
    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    connection.exec_driver_sql(f"SET LOCAL statement_timeout = {int(CONSULTA_TIMEOUT_MS)}")


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """Uma sessão por requisição. Se a rota falhar antes do commit, nada é gravado (rollback)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
