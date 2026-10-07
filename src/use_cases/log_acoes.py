"""Log de ações da equipe (central administrativa): quem fez o quê, quando e o que mudou.

`registrar` só adiciona a linha na sessão: ela é gravada junto com a própria ação, na mesma
transação (se a ação falhar, o log também não fica). Quem fez vem sempre do token.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from src import models as m
from src.entities.log import AREAS_LOG
from src.repositories import log_repository, sessao
from src.utils.datas import agora
from src.utils.erros import DadosInvalidos
from src.utils.texto import corresponde

LIMITE = 500


def registrar(
    db: Session,
    usuario: m.Usuario | int | None,
    area: str,
    acao: str,
    descricao: str,
    alteracoes: list[dict] | None = None,
    referencia: tuple[str, int] | None = None,
) -> None:
    usuario_id = usuario.id if isinstance(usuario, m.Usuario) else usuario
    tipo, ref_id = referencia or (None, None)
    sessao.adicionar(
        db,
        m.LogAcao(
            usuario_id=usuario_id,
            area=area,
            acao=acao,
            descricao=descricao,
            alteracoes=alteracoes or [],
            referencia_tipo=tipo,
            referencia_id=ref_id,
            criado_em=agora(),
        ),
    )


def _texto(valor: Any) -> str:
    if valor is None or valor == "":
        return "—"
    if isinstance(valor, (list, tuple)):
        return "; ".join(str(v) for v in valor) or "—"
    return str(valor)


def mudancas(
    antes: dict, depois: dict, rotulos: dict[str, str], formatos: dict[str, Callable[[Any], str]] | None = None
) -> list[dict]:
    """O que mudou entre dois dicionários, com rótulos legíveis: [{ campo, de, para }]."""
    formatos = formatos or {}
    return [
        {
            "campo": rotulo,
            "de": formatos.get(campo, _texto)(antes.get(campo)),
            "para": formatos.get(campo, _texto)(depois.get(campo)),
        }
        for campo, rotulo in rotulos.items()
        if antes.get(campo) != depois.get(campo)
    ]


def listar(db: Session, *, area: str | None = None, usuario_id: int | None = None, busca: str | None = None) -> list[m.LogAcao]:
    """Mais recentes primeiro; no máximo 500 registros."""
    if area and area not in AREAS_LOG:
        raise DadosInvalidos("Área do log inválida.")
    registros = log_repository.listar(db, area=area, usuario_id=usuario_id)
    if busca:
        registros = [
            r
            for r in registros
            if corresponde(busca, r.descricao, r.usuario.nome if r.usuario else "", *(a.get("campo", "") for a in r.alteracoes))
        ]
    return registros[:LIMITE]
