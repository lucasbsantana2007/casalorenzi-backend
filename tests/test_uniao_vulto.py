"""União com a Vulto (etapa 1): marca como dimensão, canal App, apoio da migração e Vulto+,
e a prova de que a Casa Lorenzi continua igual (site, checkout, expedição e transferências)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src import models as m
from src.database.connection import SessionLocal
from src.migracao_vulto import lojas as lojas_vulto
from src.migracao_vulto.__main__ import rodar

ENDERECO_SP = {
    "cep": "01310-100",
    "rua": "Av. Paulista",
    "numero": "1",
    "bairro": "Bela Vista",
    "cidade": "São Paulo",
    "uf": "SP",
}
PECA = {
    "nome": "Camisa Teste União",
    "categoria": "Camisaria",
    "precoBase": 200,
    "ativo": True,
    "genero": "Masculino",
    "variacoes": [{"sku": "CL-UNI-AZU-M", "tamanho": "M", "cor": "Azul", "precoCusto": 80}],
}


@pytest.fixture
def lojas_da_vulto():
    """Roda o domínio lojas da migração e devolve {id no legado: id na plataforma}."""
    rodar(["lojas"])
    with SessionLocal() as db:
        return {i: lojas_vulto.loja_da_vulto(db, i).id for i in lojas_vulto.LOJAS}


def _contar(db, modelo, *condicoes):
    return db.scalar(select(func.count()).select_from(modelo).where(*condicoes))


def _gravar_e_esperar_erro(*objetos):
    with SessionLocal() as db:
        db.add_all(objetos)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


# ---------- Casa Lorenzi continua igual ----------


def test_lojas_e_produtos_existentes_ficam_lorenzi(client, admin):
    lojas = client.get("/api/lojas").json()
    assert len(lojas) == 5 and {(loja["marca"], loja["tipo"]) for loja in lojas} == {("LORENZI", "FISICA")}
    produtos = client.get("/api/produtos").json()
    assert produtos and {p["marca"] for p in produtos} == {"LORENZI"} and {p["colecao"] for p in produtos} == {None}
    assert all("ean" in v for p in produtos for v in p["variacoes"])
    clientes = client.get("/api/clientes", headers=admin).json()
    assert clientes and all(c["aceitaMarketing"] is False for c in clientes)


def test_site_mostra_so_as_lojas_da_lorenzi(client, admin, mariana, lojas_da_vulto):
    assert {loja["marca"] for loja in client.get("/api/lojas").json()} == {"LORENZI"}
    assert {loja["marca"] for loja in client.get("/api/lojas?marca=VULTO").json()} == {"LORENZI"}
    assert {loja["marca"] for loja in client.get("/api/lojas", headers=mariana).json()} == {"LORENZI"}
    # A equipe vê as duas marcas (filtros do painel) e pode separar uma da outra
    assert len(client.get("/api/lojas", headers=admin).json()) == 10
    vulto = client.get("/api/lojas?marca=VULTO", headers=admin).json()
    assert {(loja["nome"], loja["tipo"]) for loja in vulto} == {
        ("Vulto Pinheiros", "FISICA"),
        ("Vulto Shopping Eldorado", "FISICA"),
        ("Vulto Savassi", "FISICA"),
        ("Vulto Batel", "FISICA"),
        ("CD Cajamar", "CD"),
    }


def test_checkout_da_lorenzi_nunca_expede_nem_puxa_peca_de_loja_vulto(client, admin, mariana, lojas_da_vulto):
    variacao_id = client.post("/api/produtos", headers=admin, json=PECA).json()["variacoes"][0]["id"]
    # A peça só tem saldo na Lorenzi de Brasília (loja 2)...
    estoque = client.get(f"/api/estoque?variacaoId={variacao_id}&lojaId=2", headers=admin).json()[0]
    mov = {"estoqueId": estoque["id"], "tipo": "ENTRADA", "quantidade": 1, "origem": "NF"}
    assert client.post("/api/movimentacoes", headers=admin, json=mov).status_code == 201
    # ...e, à força, muito saldo numa loja Vulto do mesmo estado do CEP: sem a regra de marca, ela ganharia
    with SessionLocal() as db:
        db.add(m.Estoque(loja_id=lojas_da_vulto[1], variacao_id=variacao_id, quantidade=5, quantidade_min=2))
        db.commit()

    compra = {
        "endereco": ENDERECO_SP,
        "freteTipo": "PADRAO",
        "pagamento": {"metodo": "PIX"},
        "itens": [{"variacaoId": variacao_id, "quantidade": 1}],
    }
    r = client.post("/api/checkout", headers=mariana, json=compra)
    assert r.status_code == 201, r.text
    pedido = next(p for p in client.get("/api/pedidos", headers=admin).json() if p["numero"] == r.json()["numero"])
    detalhe = client.get(f"/api/pedidos/{pedido['id']}", headers=admin).json()
    assert detalhe["loja"]["marca"] == "LORENZI"
    assert all(t["lojaOrigem"]["marca"] == "LORENZI" for t in detalhe["transferencias"])

    # A expedição também não pode ser trocada para uma loja de outra marca
    r = client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"lojaId": lojas_da_vulto[1]})
    assert r.status_code == 422 and "mesma marca" in r.json()["detail"]


def test_checkout_recusa_produto_que_nao_e_da_marca_do_site(client, mariana):
    with SessionLocal() as db:
        db.execute(m.Produto.__table__.update().values(marca="VULTO"))
        variacao_id = db.scalar(select(m.Variacao.id).order_by(m.Variacao.id))
        db.commit()
    compra = {
        "endereco": ENDERECO_SP,
        "freteTipo": "PADRAO",
        "pagamento": {"metodo": "PIX"},
        "itens": [{"variacaoId": variacao_id, "quantidade": 1}],
    }
    r = client.post("/api/checkout", headers=mariana, json=compra)
    assert r.status_code == 422 and "não está mais disponível" in r.json()["detail"]


def test_transferencia_so_entre_lojas_da_marca_do_produto(client, operador, lojas_da_vulto):
    origem = client.get("/api/estoque?lojaId=1&status=NORMAL", headers=operador).json()[0]
    with SessionLocal() as db:  # destino com a linha de estoque (à força), para a regra de marca ser a única barreira
        db.add(m.Estoque(loja_id=lojas_da_vulto[7], variacao_id=origem["variacaoId"], quantidade=0, quantidade_min=2))
        db.commit()
    transferencia = {"variacaoId": origem["variacaoId"], "lojaOrigemId": 1, "lojaDestinoId": lojas_da_vulto[7], "quantidade": 1}
    r = client.post("/api/transferencias", headers=operador, json=transferencia)
    assert r.status_code == 422 and "mesma marca" in r.json()["detail"]


def test_loja_nova_recebe_estoque_so_dos_produtos_da_marca(client, admin):
    dados = {"nome": "Vulto Moema", "cidade": "São Paulo", "uf": "SP", "marca": "VULTO", "tipo": "FISICA"}
    r = client.post("/api/admin/lojas", headers=admin, json=dados)
    assert r.status_code == 201, r.text
    loja = r.json()
    assert (loja["marca"], loja["tipo"]) == ("VULTO", "FISICA")
    assert client.get(f"/api/estoque?lojaId={loja['id']}", headers=admin).json() == []  # nenhum produto Vulto ainda

    # Produto novo da Lorenzi não abre estoque na loja Vulto
    client.post("/api/produtos", headers=admin, json=PECA)
    assert client.get(f"/api/estoque?lojaId={loja['id']}", headers=admin).json() == []

    # Editar pelo painel atual (sem mandar marca) mantém a marca; trocar a marca é recusado
    r = client.put(
        f"/api/admin/lojas/{loja['id']}", headers=admin, json={**dados, "marca": None, "tipo": None, "telefone": "11 3333-4444"}
    )
    assert r.status_code == 200 and r.json()["marca"] == "VULTO" and r.json()["telefone"] == "11 3333-4444"
    r = client.put(f"/api/admin/lojas/{loja['id']}", headers=admin, json={**dados, "marca": "LORENZI"})
    assert r.status_code == 422
    assert client.post("/api/admin/lojas", headers=admin, json={**dados, "nome": "X", "tipo": "QUIOSQUE"}).status_code == 422

    # Sem marca e tipo, a loja nova é da Lorenzi e física (o painel atual não manda esses campos)
    r = client.post("/api/admin/lojas", headers=admin, json={"nome": "Moinhos", "cidade": "Porto Alegre", "uf": "RS"})
    assert (r.json()["marca"], r.json()["tipo"]) == ("LORENZI", "FISICA")


# ---------- Financeiro e dashboard: as duas marcas, com filtro ----------


def _pedido_vulto(loja_id: int, valor: str) -> None:
    """Uma venda do App da Vulto, gravada direto no banco (a carga de verdade vem na etapa de vendas)."""
    with SessionLocal() as db:
        categoria = db.scalar(select(m.Categoria).order_by(m.Categoria.id))
        produto = m.Produto(nome="Short Vulto", categoria=categoria, preco_base=Decimal(valor), marca="VULTO", colecao="Verão 26")
        variacao = m.Variacao(produto=produto, sku="VLT-BER-001-BRA-38", tamanho="38", cor="BRANCO", ean="7899753385082")
        cliente = db.scalar(select(m.Cliente).order_by(m.Cliente.id))
        pedido = m.Pedido(
            numero="VLT-TESTE-1",
            cliente=cliente,
            loja_id=loja_id,
            canal="App",
            status="ENTREGUE",
            subtotal=Decimal(valor),
            total=Decimal(valor),
            criado_em=datetime.now(UTC),
            itens=[m.ItemPedido(variacao=variacao, quantidade=1, preco_unitario=Decimal(valor))],
        )
        db.add_all([produto, variacao, pedido])
        db.commit()


def test_financeiro_soma_as_duas_marcas_e_separa_pelo_filtro(client, admin, lojas_da_vulto):
    antes = client.get("/api/financeiro/resumo", headers=admin).json()["receita"]
    _pedido_vulto(lojas_da_vulto[7], "189.90")

    todas = client.get("/api/financeiro/resumo", headers=admin).json()
    lorenzi = client.get("/api/financeiro/resumo?marcas=LORENZI", headers=admin).json()
    vulto = client.get("/api/financeiro/resumo?marcas=VULTO", headers=admin).json()
    assert todas["receita"] == pytest.approx(antes + 189.90)
    assert lorenzi["receita"] == pytest.approx(antes)
    assert vulto["receita"] == pytest.approx(189.90) and vulto["pedidos"] == 1
    assert {item["loja"]["marca"] for item in vulto["porLoja"]} == {"VULTO"}
    assert client.get("/api/financeiro/resumo?canais=App", headers=admin).json()["receita"] == pytest.approx(189.90)
    assert client.get("/api/financeiro/resumo?marcas=OUTRA", headers=admin).status_code == 422


def test_dashboard_filtra_por_marca(client, admin, lojas_da_vulto):
    todas = client.get("/api/dashboard/resumo", headers=admin).json()
    assert len(todas["resumoPorLoja"]) == 10
    vulto = client.get("/api/dashboard/resumo?marca=VULTO", headers=admin).json()
    assert {item["loja"]["marca"] for item in vulto["resumoPorLoja"]} == {"VULTO"}
    assert vulto["indicadores"]["estoqueTotal"] == 0 and vulto["indicadores"]["produtosAtivos"] == 0
    lorenzi = client.get("/api/dashboard/resumo?marca=LORENZI", headers=admin).json()
    assert lorenzi["indicadores"]["estoqueTotal"] == todas["indicadores"]["estoqueTotal"]
    assert client.get("/api/dashboard/resumo?marca=OUTRA", headers=admin).status_code == 422


# ---------- Migração: lojas da Vulto ----------


def test_migracao_das_lojas_e_idempotente(lojas_da_vulto):
    rodar(["lojas"])  # segunda vez: atualiza, não duplica
    with SessionLocal() as db:
        assert _contar(db, m.Loja, m.Loja.marca == "VULTO") == 5
        assert _contar(db, m.Loja, m.Loja.marca == "LORENZI") == 5
        assert _contar(db, m.DePara, m.DePara.origem == "vulto.db:lojas") == 5
        # 5 lojas sem endereço no legado (PENDENTE) + site e app que viram canal (CORRIGIDO)
        ocorrencias = db.scalars(select(m.MigracaoOcorrencia).where(m.MigracaoOcorrencia.dominio == "lojas")).all()
        assert sorted((o.codigo_problema, o.id_origem) for o in ocorrencias if o.acao_tomada == "CORRIGIDO") == [
            ("LOJA_VIRTUAL_VIRA_CANAL", "5"),
            ("LOJA_VIRTUAL_VIRA_CANAL", "6"),
        ]
        assert sum(1 for o in ocorrencias if o.acao_tomada == "PENDENTE") == 5
        cd = db.get(m.Loja, lojas_da_vulto[7])
        assert (cd.nome, cd.tipo, cd.uf) == ("CD Cajamar", "CD", "SP")


def test_migracao_nao_mexe_em_loja_da_lorenzi_com_o_mesmo_nome():
    with SessionLocal() as db:
        db.add(m.Loja(nome="CD Cajamar", cidade="Cajamar", uf="SP"))
        db.commit()
    with pytest.raises(RuntimeError, match="não mexe"):
        rodar(["lojas"])


# ---------- Restrições novas no banco ----------


def test_canal_app_e_aceito_e_canal_desconhecido_nao():
    with SessionLocal() as db:
        pedido = db.scalar(select(m.Pedido).order_by(m.Pedido.id))
        pedido.canal = "App"
        db.commit()
        pedido.canal = "WhatsApp"
        with pytest.raises(IntegrityError):
            db.commit()


def test_cliente_da_vulto_pode_nao_ter_email_mas_precisa_de_um_identificador(client, admin):
    with SessionLocal() as db:
        db.add_all([m.Cliente(nome="Só CPF", cpf="52998224725"), m.Cliente(nome="Só Telefone", telefone="+5511948854328")])
        db.commit()
    _gravar_e_esperar_erro(m.Cliente(nome="Ninguém"))
    # Busca e listagem do painel convivem com e-mail vazio
    r = client.get("/api/clientes?busca=Só", headers=admin)
    assert r.status_code == 200 and {c["nome"]: c["email"] for c in r.json()} == {"Só CPF": None, "Só Telefone": None}


def test_ean_tem_13_digitos_e_e_unico():
    with SessionLocal() as db:
        variacoes = db.scalars(select(m.Variacao).order_by(m.Variacao.id).limit(2)).all()
        variacoes[0].ean = "7899753385082"
        db.commit()
        variacoes[1].ean = "7899753385082"
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        variacoes[1].ean = "123"
        with pytest.raises(IntegrityError):
            db.commit()


def test_sku_alias_nao_repete_a_mesma_grafia_na_mesma_vigencia():
    with SessionLocal() as db:
        variacao_id = db.scalar(select(m.Variacao.id).order_by(m.Variacao.id))
        db.add(m.SkuAlias(variacao_id=variacao_id, alias="cam016gp", alias_normalizado="CAM016GP"))
        # Código reaproveitado por outra coleção: mesma grafia, outra vigência
        db.add(
            m.SkuAlias(
                variacao_id=variacao_id, alias="CAM016GP", alias_normalizado="CAM016GP", valido_de=datetime(2025, 10, 24).date()
            )
        )
        db.commit()
    _gravar_e_esperar_erro(m.SkuAlias(variacao_id=variacao_id, alias="CAM 016 GP", alias_normalizado="CAM016GP"))


def test_pontos_respeitam_o_sinal_de_cada_tipo_e_o_saldo_nunca_fica_negativo():
    agora = datetime.now(UTC)
    with SessionLocal() as db:
        cliente_id = db.scalar(select(m.Cliente.id).order_by(m.Cliente.id))
        conta = m.ContaPontos(cliente_id=cliente_id, saldo=150, categoria="BRONZE", categoria_declarada="brz")
        db.add(conta)
        db.flush()
        db.add_all(
            [
                m.MovimentoPontos(conta_id=conta.id, tipo="SALDO_INICIAL", quantidade=200, data=agora),
                m.MovimentoPontos(conta_id=conta.id, tipo="RESGATE", quantidade=-100, data=agora),
                m.MovimentoPontos(conta_id=conta.id, tipo="AJUSTE", quantidade=50, data=agora),
            ]
        )
        db.commit()
        conta_id = conta.id
    _gravar_e_esperar_erro(m.MovimentoPontos(conta_id=conta_id, tipo="CREDITO", quantidade=-10, data=agora))
    _gravar_e_esperar_erro(m.MovimentoPontos(conta_id=conta_id, tipo="RESGATE", quantidade=100, data=agora))
    _gravar_e_esperar_erro(m.MovimentoPontos(conta_id=conta_id, tipo="AJUSTE", quantidade=0, data=agora))
    with SessionLocal() as db:
        db.get(m.ContaPontos, conta_id).saldo = -1
        with pytest.raises(IntegrityError):
            db.commit()


def test_ocorrencia_so_aceita_acoes_e_dominios_conhecidos():
    base = {"codigo_problema": "TESTE", "origem": "vulto.db:vendas.total", "descricao": "teste"}
    with SessionLocal() as db:
        db.add(
            m.MigracaoOcorrencia(
                **base, dominio="vendas", acao_tomada="CORRIGIDO", impacto=Decimal("10.5"), impacto_unidade="REAIS"
            )
        )
        db.commit()
    _gravar_e_esperar_erro(m.MigracaoOcorrencia(**base, dominio="vendas", acao_tomada="IGNORADO"))
    _gravar_e_esperar_erro(m.MigracaoOcorrencia(**base, dominio="marketing", acao_tomada="PENDENTE"))
