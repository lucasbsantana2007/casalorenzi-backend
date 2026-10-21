"""Login com e-mail ou CPF (decisão 53 da Vulto) e o primeiro acesso de quem não tem e-mail, liberado
pelo atendimento."""

from sqlalchemy import select

from src import models as m
from src.database.connection import SessionLocal
from src.database.seed import SENHA_DEMO
from src.use_cases import autenticacao, clientes
from src.utils.seguranca import gerar_hash
from tests.conftest import CLIENTE_DEMO_ID

ERRO = {"detail": "E-mail, CPF ou senha incorretos."}


def _entrar(client, login, senha=SENHA_DEMO):
    return client.post("/api/auth/login", json={"email": login, "senha": senha})


def test_cliente_entra_pelo_cpf_com_ou_sem_mascara(client):
    for login in (CLIENTE_DEMO_ID, "158.813.998-03"):
        r = _entrar(client, login)
        assert r.status_code == 200, r.text
        assert r.json()["usuario"]["id"] == CLIENTE_DEMO_ID and r.json()["usuario"]["papel"] == "CLIENTE"
    assert _entrar(client, CLIENTE_DEMO_ID, "senha-errada").json() == ERRO
    assert _entrar(client, "52998224725").json() == ERRO  # CPF sem conta: a mesma mensagem


def test_quem_divide_o_email_com_a_familia_entra_pelo_cpf(client):
    with SessionLocal() as db:
        mariana = db.scalar(select(m.Cliente).where(m.Cliente.cpf == CLIENTE_DEMO_ID))
        db.add(m.Cliente(nome="Irmã da Mariana", cpf="11144477735", email=mariana.email, senha_hash=gerar_hash("senha-da-irma")))
        db.commit()
        email = mariana.email
    assert _entrar(client, email).json() == ERRO  # o e-mail não identifica nenhuma das duas
    assert _entrar(client, "111.444.777-35", "senha-da-irma").json()["usuario"]["nome"] == "Irmã da Mariana"
    assert _entrar(client, CLIENTE_DEMO_ID).status_code == 200


def test_esqueci_a_senha_pelo_cpf(client, monkeypatch):
    monkeypatch.setattr(autenticacao, "LINK_SENHA_NA_RESPOSTA", True)
    link = client.post("/api/auth/esqueci-senha", json={"email": "158.813.998-03"}).json()["linkDemo"]
    assert link.startswith("/login/nova-senha?token=")
    assert client.post("/api/auth/esqueci-senha", json={"email": "abc"}).status_code == 422


def test_cliente_sem_email_ganha_acesso_pelo_atendimento(client, admin, lojista, monkeypatch):
    monkeypatch.setattr(autenticacao, "LINK_SENHA_NA_RESPOSTA", True)
    monkeypatch.setattr(clientes, "LINK_SENHA_NA_RESPOSTA", True)
    with SessionLocal() as db:
        db.add(m.Cliente(nome="Cliente Vulto+ sem cadastro", cpf="00009297197", atualizar_cadastro=True))
        db.commit()
    # Sem e-mail, o "esqueci a senha" não tem para onde mandar o link (a resposta é a mesma)
    assert client.post("/api/auth/esqueci-senha", json={"email": "00009297197"}).json() == {"enviado": True, "linkDemo": None}

    # E-mail de outra conta: 409; o cliente não libera o próprio acesso por aqui
    em_uso = client.post("/api/clientes/00009297197/acesso", headers=admin, json={"email": "mariana.costa@gmail.com"})
    assert em_uso.status_code == 409
    mariana = client.post("/api/auth/login", json={"email": "mariana.costa@gmail.com", "senha": SENHA_DEMO}).json()["token"]
    proibido = client.post(
        "/api/clientes/00009297197/acesso", headers={"Authorization": f"Bearer {mariana}"}, json={"email": "x@y.com"}
    )
    assert proibido.status_code in (401, 403)  # conta de cliente não entra nas rotas da equipe

    r = client.post("/api/clientes/00009297197/acesso", headers=lojista, json={"email": "Novo.Cliente@Gmail.com"})
    assert r.status_code == 200, r.text
    token = r.json()["linkDemo"].split("token=")[1]
    senha = {"token": token, "senha": "senha-nova-1", "senhaConfirmacao": "senha-nova-1"}
    assert client.post("/api/auth/redefinir-senha", json=senha).json() == {"email": "novo.cliente@gmail.com"}
    assert _entrar(client, "000.092.971-97", "senha-nova-1").status_code == 200
    assert _entrar(client, "novo.cliente@gmail.com", "senha-nova-1").status_code == 200
