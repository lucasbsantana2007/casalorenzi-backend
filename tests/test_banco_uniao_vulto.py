"""Banco pronto para a união com a Vulto: as regras novas do banco e a plataforma funcionando com
registros no formato dos dados da Vulto (pedido sem cliente, atendimento de WhatsApp, e-mail repetido...).
Nenhum dado real da Vulto é carregado aqui: os registros são montados no próprio teste."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from src import models as m
from src.database.connection import SessionLocal, engine
from src.entities.cliente import problemas_do_cadastro
from src.entities.fidelidade import categoria_pelo_saldo, valor_em_reais
from src.entities.pedido import proximo_numero
from src.entities.produto import ean_interno
from tests.conftest import CLIENTE_DEMO_ID

AGORA = datetime(2026, 9, 15, 15, 0, tzinfo=UTC)


def _gravar(*registros):
    with SessionLocal() as db:
        db.add_all(registros)
        db.commit()
        return [r.id for r in registros]


def _recusado(restricao: str, *registros):
    """O banco recusa o registro pela restrição com esse nome (check, unique ou chave estrangeira)."""
    with SessionLocal() as db, pytest.raises(IntegrityError, match=restricao):
        db.add_all(registros)
        db.commit()


def _loja_vulto(db, **campos) -> m.Loja:
    loja = m.Loja(nome="Vulto Pinheiros", cidade="São Paulo", uf="SP", marca="VULTO", **campos)
    db.add(loja)
    db.flush()
    return loja


def _variacao_do_seed(db) -> m.Variacao:
    return db.scalar(select(m.Variacao).order_by(m.Variacao.id).limit(1))


def _venda_vulto(db, loja: m.Loja, variacao: m.Variacao, **campos) -> m.Pedido:
    """Venda de balcão sem cliente cadastrado, com desconto, como as da Vulto."""
    dados = dict(
        numero="VLT-1343",
        cliente_id=None,
        cliente_contato="consumidor",
        loja_id=loja.id,
        canal="Loja física",
        status="ENTREGUE",
        status_origem="Sem status",
        subtotal=Decimal("279.80"),
        desconto=Decimal("27.98"),
        total=Decimal("251.82"),
        vendedor_nome="Rafael Lima ou Rafaela Couto",
        criado_em=AGORA,
        itens=[m.ItemPedido(variacao_id=variacao.id, quantidade=2, preco_unitario=Decimal("139.90"))],
    )
    dados.update(campos)
    pedido = m.Pedido(**dados)
    db.add(pedido)
    db.flush()
    return pedido


# ---------- Estrutura ----------


def test_tabelas_novas_e_existentes():
    tabelas = set(inspect(engine).get_table_names())
    novas = {"fornecedores", "movimentos_pontos", "decisoes_migracao", "de_para"}
    assert novas <= tabelas
    # Nenhuma tabela da Casa Lorenzi foi apagada: 23 + 4 novas (+ alembic_version). Sem lista de
    # pendências: as pendências das planilhas da Vulto viraram decisões (docs/registro_decisoes_uniao.md)
    assert len(tabelas - {"alembic_version"}) == 27 and "pendencias" not in tabelas


def test_o_que_ja_existia_e_da_casa_lorenzi():
    with SessionLocal() as db:
        assert set(db.scalars(select(m.Loja.marca))) == {"LORENZI"}
        assert set(db.scalars(select(m.Loja.tipo))) == {"LOJA"}
        assert set(db.scalars(select(m.Produto.marca))) == {"LORENZI"}
        assert set(db.scalars(select(m.Variacao.status))) == {"ATIVO"}
        assert set(db.scalars(select(m.Atendimento.marca))) == {"LORENZI"}
        assert set(db.scalars(select(m.Atendimento.canal))) == {"SITE"}
        assert set(db.scalars(select(m.Pedido.tipo))) == {"VENDA"}
        assert db.scalar(select(func.sum(m.Pedido.desconto))) == 0
        assert not any(db.scalars(select(m.Cliente.aceita_marketing)))


def test_lojas_saem_com_marca_e_tipo(client):
    loja = client.get("/api/lojas").json()[0]
    assert loja["marca"] == "LORENZI" and loja["tipo"] == "LOJA"


# ---------- Regras do banco ----------


def test_total_do_pedido_fecha_com_itens_desconto_e_frete():
    with SessionLocal() as db:
        loja = _loja_vulto(db)
        variacao = _variacao_do_seed(db)
        pedido = _venda_vulto(db, loja, variacao)
        db.commit()
        assert pedido.total == pedido.subtotal - pedido.desconto

    with SessionLocal() as db, pytest.raises(IntegrityError, match="ck_pedidos_total"):
        _venda_vulto(db, db.get(m.Loja, 1), _variacao_do_seed(db), numero="VLT-1", total=Decimal("279.80"))
    with SessionLocal() as db, pytest.raises(IntegrityError, match="ck_pedidos_desconto"):  # desconto maior que os itens
        _venda_vulto(
            db, db.get(m.Loja, 1), _variacao_do_seed(db), numero="VLT-2", desconto=Decimal("300"), total=Decimal("-20.20")
        )


def test_venda_online_do_app_com_frete_e_troca_sem_receita(client, admin):
    with SessionLocal() as db:
        cd = _loja_vulto(db, tipo="CD")
        variacao = _variacao_do_seed(db)
        app = _venda_vulto(
            db, cd, variacao, numero="APP-7001205", canal="App", frete_valor=Decimal("14.90"), total=Decimal("266.72")
        )
        troca = _venda_vulto(db, cd, variacao, numero="VLT-9", tipo="TROCA", desconto=0, total=Decimal("279.80"))
        db.add(m.Pagamento(pedido=app, metodo="NAO_INFORMADO", valor=app.total, status="CHARGEBACK"))
        db.commit()
        assert (app.canal, troca.tipo) == ("App", "TROCA")
    pedido = client.get("/api/pedidos?busca=APP-7001205", headers=admin).json()[0]
    # A Vulto guarda o valor do frete, mas não o tipo (Padrão ou Expresso)
    assert pedido["frete"] == {"tipo": None, "label": "Frete", "valor": 14.9, "prazoDias": None}
    assert pedido["pagamento"] == {"metodo": "NAO_INFORMADO", "parcelas": 1, "status": "CHARGEBACK"}
    assert pedido["loja"]["tipo"] == "CD" and pedido["loja"]["marca"] == "VULTO"


def test_item_com_quantidade_zero_ou_negativa_e_recusado():
    with SessionLocal() as db:
        pedido_id = db.scalar(select(m.Pedido.id).limit(1))
        variacao_id = _variacao_do_seed(db).id
    _recusado(
        "ck_itens_pedido_quantidade", m.ItemPedido(pedido_id=pedido_id, variacao_id=variacao_id, quantidade=-1, preco_unitario=10)
    )


def test_estoque_nunca_fica_negativo():
    with SessionLocal() as db:
        estoque = db.scalar(select(m.Estoque).limit(1))
        estoque.quantidade = -1
        with pytest.raises(IntegrityError, match="ck_estoques_quantidade"):
            db.commit()


def test_movimentacao_de_avaria_estimada_com_pedido_e_nota():
    with SessionLocal() as db:
        estoque = db.scalar(select(m.Estoque).where(m.Estoque.quantidade > 0).limit(1))
        pedido_id = db.scalar(select(m.Pedido.id).limit(1))
        db.add_all(
            [
                m.Movimentacao(
                    estoque=estoque,
                    tipo="AVARIA",
                    quantidade=-1,
                    estimado=True,
                    origem="Avaria estimada (decisão 54)",
                    saldo_resultante=estoque.quantidade - 1,
                ),
                m.Movimentacao(
                    estoque=estoque,
                    tipo="ENTRADA",
                    quantidade=2,
                    nota_fiscal="32197",
                    custo_unitario=Decimal("87.34"),
                    origem="Compra (NF)",
                    saldo_resultante=estoque.quantidade + 1,
                ),
                m.Movimentacao(estoque=estoque, tipo="VENDA", quantidade=-1, pedido_id=pedido_id, saldo_resultante=0),
            ]
        )
        db.commit()
    with SessionLocal() as db:
        estoque_id = db.scalar(select(m.Estoque.id).limit(1))
    _recusado(
        "ck_movimentacoes_saldo", m.Movimentacao(estoque_id=estoque_id, tipo="SALDO_INICIAL", quantidade=1, saldo_resultante=-1)
    )
    _recusado("ck_movimentacoes_tipo", m.Movimentacao(estoque_id=estoque_id, tipo="PERDA", quantidade=1, saldo_resultante=1))


def test_cliente_da_vulto_sem_email_e_familia_com_o_mesmo_email():
    _gravar(
        m.Cliente(nome="(sem cadastro na planilha)", cpf="00009297197", atualizar_cadastro=True),
        m.Cliente(nome="Bernardo Andrade", cpf="11144477735", email="familia@gmail.com", canal_cadastro="App"),
        m.Cliente(nome="Bia Andrade", cpf="52998224725", email="familia@gmail.com", aceita_marketing=True),
    )
    _recusado("ck_clientes_identificacao", m.Cliente(nome="Sem identificação"))  # nem CPF nem e-mail
    _recusado("ck_clientes_canal_cadastro", m.Cliente(nome="Canal errado", cpf="39053344705", canal_cadastro="Site"))


def test_variacao_com_ean_codigo_do_cd_e_preco_proprio():
    with SessionLocal() as db:
        fornecedor = m.Fornecedor(nome="Malharia Serra Azul")
        produto = m.Produto(
            nome="Moletom Careca Básico",
            categoria_id=1,
            preco_base=Decimal("229.90"),
            marca="VULTO",
            codigo_modelo="MOL-002",
            colecao="Inverno 26",
            fornecedor=fornecedor,
        )
        variacao = m.Variacao(
            produto=produto,
            sku="VLT-MOL-002-BRA-P",
            tamanho="P",
            cor="Branco",
            preco_custo=Decimal("85.70"),
            ean="2000000000015",
            codigo_cd="MOL002BP",
            status="DESCONTINUADO",
        )
        db.add(variacao)
        db.commit()
        assert variacao.preco_vigente == Decimal("229.90") and variacao.ean_provisorio
        variacao.preco = Decimal("99.95")
        db.commit()
        assert variacao.preco_vigente == Decimal("99.95")
        produto_id = produto.id

    with SessionLocal() as db:  # o mesmo código de modelo pode voltar em outro produto (Vulto reaproveitou)
        db.add(
            m.Produto(nome="Hoodie Oversized Básico", categoria_id=1, preco_base=249.9, marca="VULTO", codigo_modelo="MOL-002")
        )
        db.commit()
    _recusado("ck_variacoes_ean", m.Variacao(produto_id=produto_id, sku="VLT-X-1", tamanho="P", cor="Preto", ean="789123"))
    _recusado(
        "variacoes_ean_key", m.Variacao(produto_id=produto_id, sku="VLT-X-2", tamanho="P", cor="Preto", ean="2000000000015")
    )
    _recusado("ck_variacoes_status", m.Variacao(produto_id=produto_id, sku="VLT-X-3", tamanho="P", cor="Preto", status="Ativo"))


def test_extrato_de_pontos_respeita_sinal_e_saldo():
    with SessionLocal() as db:
        cliente_id = db.scalar(select(m.Cliente.id).where(m.Cliente.cpf == CLIENTE_DEMO_ID))
    _gravar(
        m.MovimentoPontos(cliente_id=cliente_id, tipo="SALDO_INICIAL", quantidade=3638, saldo_resultante=3638),
        m.MovimentoPontos(
            cliente_id=cliente_id, tipo="RESGATE", quantidade=-1000, saldo_resultante=2638, valor_desconto=Decimal("100")
        ),
        m.MovimentoPontos(cliente_id=cliente_id, tipo="VENCIMENTO", quantidade=-1638, saldo_resultante=1000),
    )
    _recusado(
        "ck_movimentos_pontos_sinal",
        m.MovimentoPontos(cliente_id=cliente_id, tipo="RESGATE", quantidade=500, saldo_resultante=1500),
    )
    _recusado(
        "ck_movimentos_pontos_sinal",
        m.MovimentoPontos(cliente_id=cliente_id, tipo="CREDITO", quantidade=-5, saldo_resultante=995),
    )
    _recusado(
        "ck_movimentos_pontos_saldo",
        m.MovimentoPontos(cliente_id=cliente_id, tipo="AJUSTE", quantidade=-2000, saldo_resultante=-1000),
    )
    _recusado(
        "ck_movimentos_pontos_sinal", m.MovimentoPontos(cliente_id=cliente_id, tipo="AJUSTE", quantidade=0, saldo_resultante=1000)
    )


@pytest.mark.parametrize(
    ("saldo", "categoria"),
    [
        (0, None),
        (1, "BRONZE"),
        (1500, "BRONZE"),
        (1501, "PRATA"),
        (5000, "PRATA"),
        (5001, "OURO"),
        (9999, "OURO"),
        (10000, "VIP"),
    ],
)
def test_categoria_do_vulto_mais_pelo_saldo(saldo, categoria):
    assert categoria_pelo_saldo(saldo) == categoria


def test_valor_dos_pontos_e_ean_interno():
    assert valor_em_reais(3_373_251) == Decimal("168662.55")  # passivo oficial da Vulto em 01/10/2026
    assert ean_interno("2000000000015") and not ean_interno("7896293000000") and not ean_interno(None)


def test_registro_de_decisoes_e_de_para():
    _gravar(
        m.DecisaoMigracao(
            numero=25,
            area="FIDELIDADE",
            o_que_encontramos="Resgates anotados pelas lojas, muitos fora do sistema",
            onde="planilha de fidelidade, aba Resgates",
            quantos_registros="596 linhas",
            o_que_decidimos="Debitar o que está só na planilha; sem CPF fica pendente",
            por_que="Debitar os que já estão no sistema cobraria duas vezes",
            impacto="−83.900 pontos; 1.000 pontos pendentes",
            tipo="PADRAO_ASSUMIDO",
        ),
        m.DecisaoMigracao(
            numero=40,
            area="FIDELIDADE",
            o_que_encontramos="Compra online creditada com pontos simples",
            onde="pontos_mov × compras.origem",
            quantos_registros="2.891 créditos",
            o_que_decidimos="A decidir",
            por_que="A regra é dobro no site e no app",
            impacto="+R$ 31.581,85 se aplicado",
            tipo="NEGOCIO",
            situacao="A_DECIDIR",
        ),
    )
    _gravar(m.DePara(origem="vulto_corrigido.db:vendas", id_origem="1343", tabela_destino="pedidos", id_destino=1))
    decisao = dict(
        area="FIDELIDADE",
        o_que_encontramos="x",
        onde="x",
        quantos_registros="x",
        o_que_decidimos="x",
        por_que="x",
        impacto="x",
    )
    _recusado("decisoes_migracao_numero_key", m.DecisaoMigracao(numero=25, tipo="NEGOCIO", **decisao))
    _recusado("ck_decisoes_migracao_tipo", m.DecisaoMigracao(numero=55, tipo="negócio", **decisao))
    _recusado(
        "uq_de_para_origem",
        m.DePara(origem="vulto_corrigido.db:vendas", id_origem="1343", tabela_destino="pedidos", id_destino=2),
    )


# ---------- A plataforma com registros no formato da Vulto ----------


def test_numero_do_proximo_pedido_ignora_a_numeracao_da_vulto():
    assert proximo_numero(["CL-104827", "APP-7001205", "S100234", "VLT-18527", "BATEL-71"]) == "CL-104834"
    assert proximo_numero(["APP-7001205"]) == "CL-104827"


def test_checkout_continua_na_sequencia_cl_com_pedidos_da_vulto_no_banco(client, admin, novo_cliente):
    from tests.test_loja_pedidos import _compra, _variacao_com_estoque

    with SessionLocal() as db:
        maior = max(int(n[3:]) for n in db.scalars(select(m.Pedido.numero)))
        _venda_vulto(db, db.get(m.Loja, 1), _variacao_do_seed(db), numero="APP-7001205", canal="App")
        db.commit()
    headers, _ = novo_cliente
    variacao_id, _ = _variacao_com_estoque(client)
    r = client.post("/api/checkout", json=_compra(variacao_id), headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == f"CL-{maior + 7}"


def test_checkout_cobra_o_preco_proprio_do_sku(client, novo_cliente):
    from tests.test_loja_pedidos import _compra, _variacao_com_estoque

    variacao_id, preco_produto = _variacao_com_estoque(client)
    with SessionLocal() as db:
        db.get(m.Variacao, variacao_id).preco = Decimal("99.95")
        db.commit()
    produto = next(p for p in client.get("/api/produtos").json() if any(v["id"] == variacao_id for v in p["variacoes"]))
    assert next(v["preco"] for v in produto["variacoes"] if v["id"] == variacao_id) == 99.95
    headers, _ = novo_cliente
    r = client.post("/api/checkout", json=_compra(variacao_id), headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["subtotal"] == 99.95 != preco_produto


def test_pedido_sem_cliente_aparece_no_painel(client, admin):
    with SessionLocal() as db:
        _venda_vulto(db, db.get(m.Loja, 1), _variacao_do_seed(db), cliente_contato="contato8012@gmail.com")
        db.commit()
    lista = client.get("/api/pedidos?busca=contato8012", headers=admin).json()
    assert len(lista) == 1
    pedido = lista[0]
    assert pedido["clienteId"] is None and pedido["contato"] is None
    assert pedido["clienteContato"] == "contato8012@gmail.com"
    assert (pedido["desconto"], pedido["total"], pedido["statusOrigem"]) == (27.98, 251.82, "Sem status")
    assert pedido["vendedorNome"] == "Rafael Lima ou Rafaela Couto"
    assert client.get(f"/api/pedidos/{pedido['id']}", headers=admin).status_code == 200


def test_atendimento_de_whatsapp_sem_cliente_e_sem_loja(client, admin):
    with SessionLocal() as db:
        atendimento = m.Atendimento(
            protocolo="VLT-40003",
            cliente_id=None,
            loja_id=None,
            marca="VULTO",
            canal="WHATSAPP",
            contato="+55 11 94885-4328",
            contato_nome="Lorena",
            pedido_citado="1343",
            tipo_solicitacao_id=1,
            status="EM_ANDAMENTO",
            criado_em=AGORA,
            atualizado_em=AGORA,
        )
        db.add(atendimento)
        db.add_all(
            [
                m.Mensagem(atendimento=atendimento, autor_tipo="CLIENTE", conteudo="Meus pontos sumiram!!", enviado_em=AGORA),
                m.Mensagem(
                    atendimento=atendimento,
                    autor_tipo="ATENDENTE",
                    autor_nome="Júlia",
                    conteudo="Já abrimos a solicitação. Prazo de 7 dias úteis.",
                    enviado_em=AGORA,
                ),
            ]
        )
        db.commit()
        atendimento_id = atendimento.id

    lista = client.get("/api/atendimentos?busca=Lorena", headers=admin).json()
    assert [a["protocolo"] for a in lista] == ["VLT-40003"]
    assert lista[0]["cliente"] == {"id": None, "nome": "Lorena"}
    assert (lista[0]["canal"], lista[0]["marca"], lista[0]["loja"]) == ("WHATSAPP", "VULTO", None)
    detalhe = client.get(f"/api/atendimentos/{atendimento_id}", headers=admin).json()
    assert detalhe["cliente"]["totalPedidos"] == 0
    assert detalhe["mensagens"][-1]["autorNome"] == "Júlia" and detalhe["pedidoCitado"] == "1343"
    assert client.get("/api/dashboard/resumo", headers=admin).status_code == 200
    _recusado(
        "ck_atendimentos_cliente_ou_contato",
        m.Atendimento(protocolo="VLT-1", tipo_solicitacao_id=1, marca="VULTO", canal="INSTAGRAM", criado_em=AGORA),
    )  # nem cliente nem contato


def test_email_de_mais_de_um_cliente_nao_entra_nem_cadastra_de_novo(client):
    from src.database.seed import SENHA_DEMO

    with SessionLocal() as db:
        mariana_db = db.scalar(select(m.Cliente).where(m.Cliente.cpf == CLIENTE_DEMO_ID))
        db.add(m.Cliente(nome="Irmã da Mariana", cpf="11144477735", email=mariana_db.email))
        db.commit()
        email = mariana_db.email
    # E-mail de duas pessoas não identifica ninguém: a mensagem é a de sempre
    r = client.post("/api/auth/login", json={"email": email, "senha": SENHA_DEMO})
    assert r.status_code == 401 and r.json() == {"detail": "E-mail, CPF ou senha incorretos."}
    assert client.post("/api/auth/esqueci-senha", json={"email": email}).json()["linkDemo"] is None
    r = client.post(
        "/api/auth/cadastro",
        json={
            "nome": "Terceira",
            "cpf": "529.982.247-25",
            "email": email,
            "telefone": "",
            "senha": "senha-forte",
            "senhaConfirmacao": "senha-forte",
        },
    )
    assert r.status_code == 409


def test_conta_nova_registra_o_canal_de_cadastro(client, novo_cliente):
    _, cpf = novo_cliente
    with SessionLocal() as db:
        assert db.scalar(select(m.Cliente.canal_cadastro).where(m.Cliente.cpf == cpf)) == "E-commerce"


def test_devolucao_guarda_a_peca_e_o_pedido_na_movimentacao(client, admin):
    from tests.test_vendas import _devolver, _pedido_entregue_com_um_item

    pedido = _pedido_entregue_com_um_item(client, admin)
    item = pedido["itens"][0]
    r = _devolver(client, admin, pedido["id"], itemPedidoId=item["id"], quantidade=1)
    assert r.status_code == 201, r.text
    assert r.json()["variacaoId"] == item["variacaoId"]
    with SessionLocal() as db:
        devolucao = db.get(m.Devolucao, r.json()["id"])
        assert devolucao.variacao_id == item["variacaoId"]
        assert devolucao.movimentacao.pedido_id == pedido["id"]


def test_devolucao_da_vulto_sem_venda_original(client, admin):
    with SessionLocal() as db:
        variacao = _variacao_do_seed(db)
        db.add(
            m.Devolucao(
                variacao_id=variacao.id,
                loja_id=1,
                quantidade=1,
                valor_devolvido=Decimal("289.90"),
                motivo="dev",
                criada_em=AGORA,
            )
        )
        db.commit()
    devolucoes = client.get("/api/devolucoes", headers=admin).json()
    vulto = next(d for d in devolucoes if d["pedidoId"] is None)
    assert vulto["pedidoNumero"] is None and vulto["usuario"] is None
    _recusado(  # item sem o pedido dele
        "ck_devolucoes_item_do_pedido",
        m.Devolucao(item_pedido_id=1, variacao_id=1, loja_id=1, quantidade=1, valor_devolvido=1, criada_em=AGORA),
    )


# ---------- Dados válidos: o que só o cliente pode corrigir ----------


@pytest.mark.parametrize(
    ("cpf", "email", "telefone", "problemas"),
    [
        ("15881399803", "mariana@gmail.com", "(11) 98422-1937", []),
        ("15881399803", "mariana@gmail.com", "41907233343", []),
        ("15881399803", "mariana@gmail.com", "+55 11 94885-4328", []),
        ("15881399803", "mariana@gmail.com", None, []),  # telefone é opcional
        ("21297628578", "alice@gmail.com", None, ["CPF_INVALIDO"]),  # dígito errado (decisão 50)
        (None, "antigo@gmail.com", None, ["SEM_CPF"]),
        ("15881399803", None, "943716949", ["SEM_EMAIL", "TELEFONE_SEM_DDD"]),
        ("15881399803", "fulano@gmial", "123", ["EMAIL_INVALIDO", "TELEFONE_INVALIDO"]),
    ],
)
def test_problemas_do_cadastro(cpf, email, telefone, problemas):
    assert problemas_do_cadastro(cpf, email, telefone) == problemas


def test_lista_de_clientes_com_cadastro_a_corrigir(client, admin):
    _gravar(
        m.Cliente(nome="(sem cadastro na planilha)", cpf="00009297197", atualizar_cadastro=True),
        m.Cliente(nome="Alice Nogueira", cpf="21297628578", email="alice@gmail.com", atualizar_cadastro=True),
        m.Cliente(nome="Alexandre Almeida Ribeiro", cpf="16643840813", email="alexandre@yahoo.com.br", telefone="943716949"),
        m.Cliente(nome="Cadastro Completo", cpf="11144477735", email="completo@gmail.com", telefone="41907233343"),
    )
    a_corrigir = {c["nome"]: c for c in client.get("/api/clientes?dadosValidos=false", headers=admin).json()}
    assert set(a_corrigir) == {"(sem cadastro na planilha)", "Alice Nogueira", "Alexandre Almeida Ribeiro"}
    assert a_corrigir["(sem cadastro na planilha)"]["problemasCadastro"] == ["SEM_EMAIL"]
    assert a_corrigir["Alice Nogueira"]["problemasCadastro"] == ["CPF_INVALIDO"]
    assert a_corrigir["Alice Nogueira"]["atualizarCadastro"] is True
    assert a_corrigir["Alexandre Almeida Ribeiro"]["problemasCadastro"] == ["TELEFONE_SEM_DDD"]

    validos = client.get("/api/clientes?dadosValidos=true", headers=admin).json()
    assert "Cadastro Completo" in {c["nome"] for c in validos} and all(c["dadosValidos"] for c in validos)
    detalhe = client.get("/api/clientes/11144477735", headers=admin).json()
    assert detalhe["dadosValidos"] is True and detalhe["problemasCadastro"] == []


def test_filtro_de_dados_validos_traz_todos_sem_o_limite_da_busca(client, admin):
    def cpf(base: int) -> str:
        digitos = f"{base:09d}"
        for _ in range(2):
            soma = sum(int(d) * (len(digitos) + 1 - i) for i, d in enumerate(digitos))
            digitos += str(soma * 10 % 11 % 10)
        return digitos

    _gravar(*(m.Cliente(nome=f"Só sistema {n}", cpf=cpf(400000000 + n)) for n in range(60)))
    assert len(client.get("/api/clientes?busca=Só sistema", headers=admin).json()) == 50
    assert len(client.get("/api/clientes?busca=Só sistema&dadosValidos=false", headers=admin).json()) == 60


def test_troca_nao_conta_como_receita(client, admin):
    """A Vulto lançava a troca como venda nova (decisão 16): ela baixa o estoque, mas não é receita."""
    hoje = datetime.now(UTC)
    periodo = f"de={hoje:%Y-%m-%d}&ate={hoje:%Y-%m-%d}&comparar=nenhum"
    antes = client.get(f"/api/financeiro/resumo?{periodo}", headers=admin).json()
    with SessionLocal() as db:
        variacao = db.scalar(select(m.Variacao).limit(1))
        db.add(
            m.Pedido(
                numero="VLT-9",
                loja_id=1,
                canal="Loja física",
                tipo="TROCA",
                status="ENTREGUE",
                subtotal=Decimal("100.00"),
                total=Decimal("100.00"),
                criado_em=hoje,
                itens=[m.ItemPedido(variacao_id=variacao.id, quantidade=1, preco_unitario=Decimal("100.00"))],
            )
        )
        db.commit()
    depois = client.get(f"/api/financeiro/resumo?{periodo}", headers=admin).json()
    assert (depois["receita"], depois["pedidos"]) == (antes["receita"], antes["pedidos"])
