"""Equipe de demonstração das lojas da Vulto: a Lojista da Vulto Pinheiros e o Operador do CD Cajamar.

As lojas da Vulto entram no banco pela carga (src/migracao_vulto), que roda depois do seed. Por isso essa
parte da equipe entra depois da carga:

    python -m src.database.seed.equipe_vulto

Só cria quem ainda não existe (pelo e-mail) e, sem as lojas da Vulto, não faz nada. A senha é a mesma das
outras contas de demonstração (SENHA_DEMO). A Administradora da Vulto não tem loja e já vem no seed.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import SessionLocal
from src.database.seed.dados import EQUIPE_DA_VULTO, SENHA_DEMO
from src.entities.marca import VULTO
from src.utils.seguranca import gerar_hash


def criar_equipe_da_vulto(db: Session) -> list[str]:
    """Cria quem falta da equipe das lojas da Vulto. Devolve "nome (loja)" de quem foi criado."""
    criados = []
    senha = None
    for nome, email, papel, nome_loja in EQUIPE_DA_VULTO:
        if db.scalar(select(m.Usuario.id).where(m.Usuario.email == email)):
            continue
        loja = db.scalar(select(m.Loja).where(m.Loja.nome == nome_loja, m.Loja.marca == VULTO))
        if loja is None:
            continue
        senha = senha or gerar_hash(SENHA_DEMO)
        db.add(m.Usuario(nome=nome, email=email, papel=papel, marca=VULTO, loja_id=loja.id, senha_hash=senha))
        criados.append(f"{nome} ({loja.nome})")
    db.flush()
    return criados


def main() -> None:
    with SessionLocal() as db:
        criados = criar_equipe_da_vulto(db)
        db.commit()
    if criados:
        print(f"Equipe da Vulto criada: {', '.join(criados)}.")
    else:
        print("Nada a criar: a equipe da Vulto já existe ou as lojas da Vulto ainda não foram carregadas.")


if __name__ == "__main__":
    main()
