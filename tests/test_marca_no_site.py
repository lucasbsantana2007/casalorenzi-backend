"""O site é um só para as duas marcas, cada uma com a sua vitrine: a vitrine e a página Lojas pedem a marca
(sem ela, o visitante recebe a Casa Lorenzi), o checkout vende as duas e a peça sai de uma loja da marca
dela. A equipe vê as duas marcas no painel. E o estoque zerado automático fica dentro da mesma marca."""

from decimal import Decimal

from sqlalchemy import select

from src import models as m
from src.database.connection import SessionLocal
from tests.test_loja_pedidos import _compra


def _vulto_no_banco():
    """Uma loja, um CD e uma peça da Vulto com estoque, como depois da carga."""
    with SessionLocal() as db:
        loja = m.Loja(nome="Vulto Pinheiros", cidade="São Paulo", uf="SP", marca="VULTO", tipo="LOJA")
        cd = m.Loja(nome="CD Cajamar", cidade="Cajamar", uf="SP", marca="VULTO", tipo="CD")
        produto = m.Produto(nome="Calça Cargo Ripstop", categoria_id=1, preco_base=Decimal("199.90"), marca="VULTO")
        variacao = m.Variacao(produto=produto, sku="VLT-CAL-001-OLI-38", tamanho="38", cor="Verde Oliva")
        db.add_all([loja, cd, variacao])
        db.flush()
        db.add_all([m.Estoque(loja_id=x.id, variacao_id=variacao.id, quantidade=10, quantidade_min=2) for x in (loja, cd)])
        db.commit()
        return loja.id, cd.id, produto.id, variacao.id


def test_cada_marca_tem_a_sua_vitrine_e_as_suas_lojas(client, admin):
    loja_id, cd_id, produto_id, _ = _vulto_no_banco()
    # Sem marca: o início do site (Casa Lorenzi), como antes
    publicas = client.get("/api/lojas").json()
    assert {loja["marca"] for loja in publicas} == {"LORENZI"} and {loja["tipo"] for loja in publicas} == {"LOJA"}
    assert all(p["marca"] == "LORENZI" for p in client.get("/api/produtos").json())

    # /vulto: só a Vulto, e só as lojas físicas (o CD não aparece no site)
    assert [loja["id"] for loja in client.get("/api/lojas?marca=VULTO").json()] == [loja_id]
    vitrine = client.get("/api/produtos?marca=VULTO").json()
    assert [p["id"] for p in vitrine] == [produto_id] and vitrine[0]["marca"] == "VULTO"
    assert client.get(f"/api/produtos/{produto_id}").json()["marca"] == "VULTO"
    assert client.get("/api/produtos?marca=OUTRA").status_code == 422

    # A equipe continua vendo as duas marcas e o CD
    assert {loja_id, cd_id} <= {loja["id"] for loja in client.get("/api/lojas", headers=admin).json()}
    assert produto_id in {p["id"] for p in client.get("/api/produtos", headers=admin).json()}
    assert {loja["marca"] for loja in client.get("/api/lojas?marca=VULTO", headers=admin).json()} == {"VULTO"}


def test_checkout_vende_a_vulto_e_cada_peca_sai_de_uma_loja_da_marca_dela(client, novo_cliente):
    from tests.test_loja_pedidos import _variacao_com_estoque

    loja_id, cd_id, _, variacao_vulto = _vulto_no_banco()
    headers, _ = novo_cliente
    r = client.post("/api/checkout", json=_compra(variacao_vulto), headers=headers)
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        pedido = db.scalar(select(m.Pedido).where(m.Pedido.numero == r.json()["numero"]))
        assert pedido.loja_id in {loja_id, cd_id} and pedido.loja.marca == "VULTO"

    # Peça da Lorenzi para CEP de SP: a Vulto Pinheiros e o CD (SP) nunca expedem
    variacao_lorenzi, _ = _variacao_com_estoque(client)
    r = client.post("/api/checkout", json=_compra(variacao_lorenzi), headers=headers)
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        pedido = db.scalar(select(m.Pedido).where(m.Pedido.numero == r.json()["numero"]))
        assert pedido.loja.marca == "LORENZI" and pedido.loja.tipo == "LOJA"


def test_estoque_zerado_so_nas_lojas_da_mesma_marca(client, admin):
    from tests.test_api import _novo_produto

    loja_id, cd_id, _, variacao_vulto = _vulto_no_banco()
    r = client.post("/api/produtos", headers=admin, json=_novo_produto())
    assert r.status_code == 201, r.text
    nova = r.json()["variacoes"][0]["id"]
    with SessionLocal() as db:
        lojas = set(db.scalars(select(m.Estoque.loja_id).where(m.Estoque.variacao_id == nova)))
        lorenzi = set(db.scalars(select(m.Loja.id).where(m.Loja.marca == "LORENZI")))
        assert lojas == lorenzi
    dados = {
        "nome": "Moinhos",
        "cidade": "Porto Alegre",
        "uf": "RS",
        "endereco": "",
        "telefone": "",
        "horarios": [],
        "ativa": True,
    }
    loja_nova = client.post("/api/admin/lojas", headers=admin, json=dados).json()["id"]
    with SessionLocal() as db:
        variacoes = set(db.scalars(select(m.Estoque.variacao_id).where(m.Estoque.loja_id == loja_nova)))
        assert variacao_vulto not in variacoes and nova in variacoes
