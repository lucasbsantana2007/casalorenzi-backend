"""Ajudantes dos testes dos assistentes (conversa do site e do copiloto)."""

from src.database.connection import SessionLocal
from src.database.seed import SENHA_DEMO


def entrar(client, email: str) -> dict:
    resposta = client.post("/api/auth/login", json={"email": email, "senha": SENHA_DEMO})
    assert resposta.status_code == 200, resposta.text
    return {"Authorization": f"Bearer {resposta.json()['token']}"}


def abrir_site(client, marca: str | None = None, token: dict | None = None) -> tuple[str, dict]:
    """(id da conversa, cabeçalhos com a chave e o token, se houver)."""
    resposta = client.post("/api/assistente/conversas", json={"marca": marca} if marca else {}, headers=token or {})
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    return corpo["id"], {"X-Conversa-Chave": corpo["chave"], **(token or {})}


def diga(client, conversa_id: str, cabecalhos: dict, texto: str, status: int = 200, **extra) -> dict:
    resposta = client.post(
        f"/api/assistente/conversas/{conversa_id}/mensagens", json={"texto": texto, **extra}, headers=cabecalhos
    )
    assert resposta.status_code == status, resposta.text
    return resposta.json()["resposta"] if status == 200 else resposta.json()


def abrir_copiloto(client, token: dict) -> str:
    resposta = client.post("/api/copiloto/conversas", headers=token)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["id"]


def pergunte(client, conversa_id: str, token: dict, texto: str, status: int = 200) -> dict:
    resposta = client.post(f"/api/copiloto/conversas/{conversa_id}/mensagens", json={"texto": texto}, headers=token)
    assert resposta.status_code == status, resposta.text
    return resposta.json()["resposta"] if status == 200 else resposta.json()


def blocos(resposta: dict, tipo: str) -> list[dict]:
    return [b for b in resposta["blocos"] if b["tipo"] == tipo]


def indicador(resposta: dict, rotulo: str):
    for bloco in blocos(resposta, "indicadores"):
        for item in bloco["itens"]:
            if item["rotulo"] == rotulo:
                return item["valor"]
    raise AssertionError(f"Indicador {rotulo!r} não está na resposta: {resposta['blocos']}")


def sql(comando: str, **parametros):
    """Executa SQL no banco de testes (para montar cenários e conferir resultados)."""
    from sqlalchemy import text

    with SessionLocal() as db:
        resultado = db.execute(text(comando), parametros)
        linhas = resultado.all() if resultado.returns_rows else None
        db.commit()
        return linhas
