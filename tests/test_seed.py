"""Carga dos dados de demonstração num banco recém-criado, como no primeiro deploy."""

from sqlalchemy import func, select

from src import models as m
from src.database.connection import SessionLocal
from src.database.seed import apagar_tudo, popular


def _contar(db, modelo):
    return db.scalar(select(func.count()).select_from(modelo))


def test_seed_funciona_logo_depois_das_migracoes():
    """`alembic upgrade head` já grava a configuração de frete padrão; o seed vem depois e não pode falhar."""
    with SessionLocal() as db:
        apagar_tudo(db)
        # O que a migração da central administrativa deixa num banco novo
        db.add(m.ConfigFrete(id=1, gratis_minimo=1000, expresso_ativo=True))
        db.add(
            m.FreteRegiao(
                id=1,
                regiao="SP",
                nome="Estado de São Paulo",
                ordem=1,
                padrao_valor=19.9,
                padrao_custo=16.5,
                padrao_prazo_dias=3,
                expresso_valor=39.9,
                expresso_custo=31,
                expresso_prazo_dias=1,
            )
        )
        db.commit()

        popular(db)
        db.commit()

        assert _contar(db, m.ConfigFrete) == 1
        assert _contar(db, m.FreteRegiao) == 6
        assert _contar(db, m.Usuario) == 8 and _contar(db, m.Produto) == 13
