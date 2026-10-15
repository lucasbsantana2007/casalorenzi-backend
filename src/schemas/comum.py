from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from src import models as m


class Entrada(BaseModel):
    """Base dos corpos de requisição: aceita camelCase (frontend) e snake_case."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AnexoEntrada(Entrada):
    """Imagem JPG/PNG/WEBP de até 2 MB. conteudoBase64 aceita o base64 puro ou um data URL."""

    nome: str = ""
    tipo: str = ""
    conteudo_base64: str = ""


def loja_saida(loja: m.Loja | None) -> dict | None:
    if loja is None:
        return None
    return {
        "id": loja.id,
        "nome": loja.nome,
        "cidade": loja.cidade,
        "uf": loja.uf,
        "endereco": loja.endereco,
        "telefone": loja.telefone,
        "horarios": list(loja.horarios or []),
        "ativa": loja.ativa,
    }


def usuario_resumo(usuario: m.Usuario | None) -> dict | None:
    if usuario is None:
        return None
    return {"id": usuario.id, "nome": usuario.nome, "papel": usuario.papel}


def usuario_saida(usuario: m.Usuario) -> dict:
    """Nunca inclui o hash da senha."""
    return {"id": usuario.id, "nome": usuario.nome, "email": usuario.email, "papel": usuario.papel, "lojaId": usuario.loja_id}
