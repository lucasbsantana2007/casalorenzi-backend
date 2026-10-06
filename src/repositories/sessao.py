"""Operações de escrita comuns a todos os repositórios (uma transação por requisição).

Tudo que um use case adiciona só vai para o banco no `confirmar`. Se algo falhar antes,
nada é gravado: ou a operação inteira acontece, ou nenhuma parte dela (atomicidade).
"""

from sqlalchemy.orm import Session


def adicionar(db: Session, *objetos) -> None:
    db.add_all(objetos)


def gerar_ids(db: Session) -> None:
    """Envia o que está pendente para o banco gerar os ids, sem confirmar a transação."""
    db.flush()


def confirmar(db: Session, *atualizar) -> None:
    db.commit()
    for objeto in atualizar:
        db.refresh(objeto)


def descartar_cache(db: Session) -> None:
    db.expire_all()
