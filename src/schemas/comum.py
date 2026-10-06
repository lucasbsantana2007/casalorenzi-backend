from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from src import models as m


class Entrada(BaseModel):
    """Base dos corpos de requisição: aceita camelCase (frontend) e snake_case."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


def loja_saida(loja: m.Loja | None) -> dict | None:
    if loja is None:
        return None
    return {"id": loja.id, "nome": loja.nome, "cidade": loja.cidade, "uf": loja.uf}


def usuario_resumo(usuario: m.Usuario | None) -> dict | None:
    if usuario is None:
        return None
    return {"id": usuario.id, "nome": usuario.nome, "papel": usuario.papel}


def usuario_saida(usuario: m.Usuario) -> dict:
    """Nunca inclui o hash da senha."""
    return {"id": usuario.id, "nome": usuario.nome, "email": usuario.email, "papel": usuario.papel, "lojaId": usuario.loja_id}
