"""Os testes rodam num banco PostgreSQL separado, definido em TEST_DATABASE_URL.

    createdb casalorenzi_test
    TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/casalorenzi_test pytest

Cada teste começa com o banco recriado a partir do seed de demonstração.
"""

import os

import pytest

URL_TESTE = os.getenv("TEST_DATABASE_URL")
if not URL_TESTE:
    pytest.skip("Defina TEST_DATABASE_URL para rodar os testes.", allow_module_level=True)
os.environ["DATABASE_URL"] = URL_TESTE  # precisa vir antes de importar o app

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from alembic import command  # noqa: E402
from src.app import app  # noqa: E402
from src.database.connection import SessionLocal  # noqa: E402
from src.database.seed import SENHA_DEMO, apagar_tudo, popular  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrar():
    command.upgrade(Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini")), "head")


@pytest.fixture(autouse=True)
def banco_limpo(migrar):
    with SessionLocal() as db:
        apagar_tudo(db)
        popular(db)
        db.commit()


@pytest.fixture
def client():
    return TestClient(app)


def _entrar(client, email):
    resposta = client.post("/api/auth/login", json={"email": email, "senha": SENHA_DEMO})
    assert resposta.status_code == 200, resposta.text
    return {"Authorization": f"Bearer {resposta.json()['token']}"}


@pytest.fixture
def admin(client):
    return _entrar(client, "helena@casalorenzi.com.br")


@pytest.fixture
def lojista(client):
    return _entrar(client, "rafael.monteiro@casalorenzi.com.br")  # loja 1


@pytest.fixture
def operador(client):
    return _entrar(client, "diego.almeida@casalorenzi.com.br")


# Clientes de demonstração: ids 101 a 108 (tabela clientes), com conta (CPF, e-mail e a senha de demonstração)
CLIENTE_DEMO_ID = 101  # Mariana Costa
CPF_NOVO = "52998224725"  # CPF válido que não está no seed


@pytest.fixture
def mariana(client):
    return _entrar(client, "mariana.costa@gmail.com")


@pytest.fixture
def novo_cliente(client):
    """Cria uma conta de cliente pelo cadastro do checkout: (headers, id)."""
    r = client.post(
        "/api/auth/cadastro",
        json={
            "nome": "Cliente Novo",
            "cpf": "529.982.247-25",
            "email": "novo.cliente@exemplo.com",
            "telefone": "(11) 99999-0000",
            "senha": "senha-forte",
            "senhaConfirmacao": "senha-forte",
        },
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["usuario"]["id"]
