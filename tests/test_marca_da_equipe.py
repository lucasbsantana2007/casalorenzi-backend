"""Marca da equipe: quem trabalha com uma marca não vê nem altera nada da outra (a API bloqueia, não só a
tela). O Administrador do grupo vê as duas e pode filtrar uma pelo cabeçalho X-Marca do seletor do painel."""

from src import models as m
from src.database.connection import SessionLocal
from src.database.seed import SENHA_DEMO
from src.database.seed.equipe_vulto import criar_equipe_da_vulto
from src.utils.seguranca import gerar_hash
from tests.conftest import _entrar
from tests.test_api import _novo_produto
from tests.test_marca_no_site import _vulto_no_banco


def _equipe_da_vulto(client, loja_id):
    """Uma Administradora e um Lojista da Vulto, já com senha."""
    with SessionLocal() as db:
        senha = gerar_hash(SENHA_DEMO)
        db.add_all(
            [
                m.Usuario(nome="Paula Vulto", email="paula@vulto.com.br", papel="ADMINISTRADOR", marca="VULTO", senha_hash=senha),
                m.Usuario(
                    nome="Lia Pinheiros",
                    email="lia@vulto.com.br",
                    papel="LOJISTA",
                    marca="VULTO",
                    loja_id=loja_id,
                    senha_hash=senha,
                ),
            ]
        )
        db.commit()
    return _entrar(client, "paula@vulto.com.br"), _entrar(client, "lia@vulto.com.br")


def test_cada_marca_ve_so_os_proprios_produtos_e_estoque(client, admin, lojista):
    loja_id, _, produto_vulto, _ = _vulto_no_banco()
    admin_vulto, lojista_vulto = _equipe_da_vulto(client, loja_id)

    marcas = lambda headers, rota="/api/produtos": {p["marca"] for p in client.get(rota, headers=headers).json()}  # noqa: E731
    assert marcas(admin) == {"LORENZI", "VULTO"}
    assert marcas(admin_vulto) == {"VULTO"}
    assert marcas(lojista) == {"LORENZI"}
    # O seletor do painel do grupo
    assert marcas({**admin, "X-Marca": "VULTO"}) == {"VULTO"}

    assert client.get(f"/api/produtos/{produto_vulto}", headers=admin_vulto).status_code == 200
    estoque_vulto = client.get("/api/estoque", headers=lojista_vulto).json()
    assert estoque_vulto and {e["loja"]["marca"] for e in estoque_vulto} == {"VULTO"}
    assert {e["loja"]["marca"] for e in client.get("/api/estoque", headers=lojista).json()} == {"LORENZI"}

    # Item de estoque da outra marca: como se não existisse
    item_lorenzi = client.get("/api/estoque", headers=lojista).json()[0]["id"]
    assert client.get(f"/api/estoque/{item_lorenzi}", headers=lojista_vulto).status_code == 404
    r = client.post(
        "/api/movimentacoes", headers=lojista_vulto, json={"estoqueId": item_lorenzi, "tipo": "ENTRADA", "quantidade": 1}
    )
    assert r.status_code == 404


def test_admin_da_marca_nao_altera_a_outra_e_cadastra_so_na_dele(client, admin):
    loja_id, _, produto_vulto, _ = _vulto_no_banco()
    admin_vulto, _ = _equipe_da_vulto(client, loja_id)
    produto_lorenzi = next(p["id"] for p in client.get("/api/produtos", headers=admin).json() if p["marca"] == "LORENZI")

    assert client.put(f"/api/produtos/{produto_lorenzi}", headers=admin_vulto, json=_novo_produto()).status_code == 404
    assert client.delete(f"/api/produtos/{produto_lorenzi}", headers=admin_vulto).status_code == 404

    # Peça nova do admin da Vulto é da Vulto, mesmo pedindo outra marca, e não precisa de coleção (gênero)
    r = client.post("/api/produtos", headers=admin_vulto, json=_novo_produto(marca="LORENZI", genero=None))
    assert r.status_code == 201, r.text
    assert r.json()["marca"] == "VULTO"
    # O admin do grupo escolhe
    r = client.post("/api/produtos", headers=admin, json=_novo_produto(marca="VULTO", genero=None, variacoes=[]))
    assert r.status_code == 201, r.text
    assert r.json()["marca"] == "VULTO"
    assert client.get(f"/api/produtos/{produto_vulto}", headers=admin).status_code == 200


def test_funcionarios_lojas_e_frete_respeitam_a_marca(client, admin, lojista):
    loja_id, cd_id, _, _ = _vulto_no_banco()
    admin_vulto, _ = _equipe_da_vulto(client, loja_id)

    funcionarios = client.get("/api/admin/funcionarios", headers=admin_vulto).json()
    assert {f["marca"] for f in funcionarios} == {"VULTO"}
    assert {loja["marca"] for loja in client.get("/api/admin/lojas", headers=admin_vulto).json()} == {"VULTO"}
    assert {loja["marca"] for loja in client.get("/api/lojas", headers=admin_vulto).json()} == {"VULTO"}

    # Não cadastra ninguém do grupo nem em loja da outra marca
    r = client.post(
        "/api/admin/funcionarios",
        headers=admin_vulto,
        json={"nome": "Novo Admin", "email": "novo.admin@vulto.com.br", "papel": "ADMINISTRADOR", "marca": "GRUPO"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["funcionario"]["marca"] == "VULTO"
    r = client.post(
        "/api/admin/funcionarios",
        headers=admin_vulto,
        json={"nome": "Vendedor", "email": "vendedor@vulto.com.br", "papel": "LOJISTA", "lojaId": 1},
    )
    assert r.status_code == 422
    # Lojista Vulto: marca vem da loja
    r = client.post(
        "/api/admin/funcionarios",
        headers=admin,
        json={"nome": "Vendedora", "email": "vendedora@vulto.com.br", "papel": "LOJISTA", "lojaId": loja_id},
    )
    assert r.status_code == 201 and r.json()["funcionario"]["marca"] == "VULTO"

    # Funcionário da Casa Lorenzi (Helena, do grupo, e Rafael) fica fora do alcance do admin da Vulto
    assert (
        client.put(
            "/api/admin/funcionarios/2",
            headers=admin_vulto,
            json={"nome": "X", "email": "x@x.com", "papel": "LOJISTA", "lojaId": 1},
        ).status_code
        == 404
    )
    assert client.get("/api/frete/config", headers=admin_vulto).status_code == 200
    assert client.put("/api/frete/config", headers=admin_vulto, json={}).status_code == 403


def test_equipe_de_demonstracao_de_cada_marca(client):
    """Helena (grupo) vê as duas marcas; cada marca tem Administrador, Lojista e Operador que só veem a
    deles. A equipe das lojas da Vulto entra depois da carga, que é quando as lojas existem."""
    with SessionLocal() as db:
        assert criar_equipe_da_vulto(db) == []
    loja_id, cd_id, produto_vulto, _ = _vulto_no_banco()
    with SessionLocal() as db:
        assert criar_equipe_da_vulto(db) == ["Lia Okada (Vulto Pinheiros)", "Bruno Sales (CD Cajamar)"]
        db.commit()
    with SessionLocal() as db:
        assert criar_equipe_da_vulto(db) == []  # rodar de novo não cria ninguém em dobro

    equipe = {
        "otavio.vasconcelos@casalorenzi.com.br": ("ADMINISTRADOR", "LORENZI", None),
        "paula.ferraz@vulto.com.br": ("ADMINISTRADOR", "VULTO", None),
        "lia.okada@vulto.com.br": ("LOJISTA", "VULTO", loja_id),
        "bruno.sales@vulto.com.br": ("OPERADOR", "VULTO", cd_id),
    }
    for email, esperado in equipe.items():
        r = client.post("/api/auth/login", json={"email": email, "senha": SENHA_DEMO})
        assert r.status_code == 200, r.text
        usuario = r.json()["usuario"]
        assert (usuario["papel"], usuario["marca"], usuario["lojaId"]) == esperado

    # O Administrador da Casa Lorenzi não vê a Vulto, nem pedindo pelo seletor do painel (X-Marca)
    otavio = _entrar(client, "otavio.vasconcelos@casalorenzi.com.br")
    produtos = client.get("/api/produtos", headers={**otavio, "X-Marca": "VULTO"}).json()
    assert {p["marca"] for p in produtos} == {"LORENZI"}
    assert client.get(f"/api/produtos/{produto_vulto}", headers=otavio).status_code == 404
    assert {f["marca"] for f in client.get("/api/admin/funcionarios", headers=otavio).json()} == {"LORENZI"}
    assert {loja["marca"] for loja in client.get("/api/admin/lojas", headers=otavio).json()} == {"LORENZI"}
