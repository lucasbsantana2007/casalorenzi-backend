"""Carga da Vulto: as conversões, o site da Casa Lorenzi filtrando pela marca e a carga completa com os
dados reais (esta só roda quando o repositório da Vulto está na máquina: VULTO_ORIGEM ou
~/copy.vulto-legado-back)."""

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src import models as m
from src.database.connection import SessionLocal
from src.migracao_vulto.carga import (
    TZ,
    Carga,
    CargaRecusada,
    dinheiro,
    estacao_da_colecao,
    ler_decisoes_do_markdown,
    movimento_de_estoque,
    movimento_de_pontos,
    ordem_dos_pontos,
)

RAIZ = Path(__file__).resolve().parents[1]
REGISTRO = RAIZ / "docs" / "registro_decisoes_uniao.md"
ORIGEM = Path(os.getenv("VULTO_ORIGEM", Path.home() / "copy.vulto-legado-back"))


# ---------- conversões ----------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("559,70", "559.70"),
        ("1.234,56", "1234.56"),
        ("219.8", "219.80"),
        (99.95, "99.95"),
        ("0", "0.00"),
        ("", None),
        (None, None),
    ],
)
def test_dinheiro(valor, esperado):
    assert dinheiro(valor) == (Decimal(esperado) if esperado else None)


def test_estacao_vem_da_colecao():
    assert [estacao_da_colecao(c) for c in ("Verão 26", "Inverno 25", "Atemporais", "2024 (lista antiga)", None)] == [
        "Verão",
        "Inverno",
        "Atemporal",
        None,
        None,
    ]


def test_tipos_do_historico_de_estoque():
    assert movimento_de_estoque("Saldo inicial (reconstruído)") == ("SALDO_INICIAL", True)
    assert movimento_de_estoque("Troca (peça nova)") == ("VENDA", False)
    assert movimento_de_estoque("Envio p/ Batel (só o recebimento anotado)") == ("TRANSFERENCIA_SAIDA", False)
    assert movimento_de_estoque("Recebido do CD (só o CD anotou)") == ("TRANSFERENCIA_ENTRADA", False)
    assert movimento_de_estoque("Ajuste de inventário (contagem física)") == ("INVENTARIO", False)
    assert movimento_de_estoque("Avaria (contada na Pinheiros)") == ("AVARIA", False)
    assert movimento_de_estoque("Avaria estimada (decisão 54)") == ("AVARIA", True)
    assert movimento_de_estoque("Ajuste: vendeu mais que o contado (estoque não fica negativo)") == ("AJUSTE", False)


def test_tipos_dos_pontos():
    assert movimento_de_pontos("C", 280, "") == ("CREDITO", 280)
    assert movimento_de_pontos("D", 500, "balcao") == ("RESGATE", -500)  # a Vulto grava o resgate positivo
    assert movimento_de_pontos("E", -280, "cancelou") == ("ESTORNO", -280)
    assert movimento_de_pontos("AJ", 3638, "saldo da planilha Vulto+ congelado em 01/01/2025") == ("SALDO_INICIAL", 3638)
    assert movimento_de_pontos("AJ", -1638, "pontos vencidos em 01/10/2026") == ("VENCIMENTO", -1638)
    assert movimento_de_pontos("AJ", 209, "resgate maior que o saldo") == ("AJUSTE", 209)


def test_no_mesmo_instante_entradas_vem_antes_das_saidas():
    linhas = [
        ("cpf", "2025-01-11 22:05:13", -500, 174),
        ("cpf", "2025-01-11 22:05:13", 209, 13493),
        ("cpf", "2025-01-04", 291, 49),
    ]
    ordem = sorted(linhas, key=lambda r: ordem_dos_pontos(*r))
    assert [r[3] for r in ordem] == [49, 13493, 174]


def test_registro_da_uniao_esta_no_formato_da_carga():
    decisoes = ler_decisoes_do_markdown(REGISTRO)
    assert [int(d["numero"]) for d in decisoes] == list(range(55, 70))
    assert {d["tipo"] for d in decisoes} <= {"automático", "padrão assumido", "negócio"}


# ---------- a carga completa, com os dados reais da Vulto ----------

com_dados_reais = pytest.mark.skipif(not (ORIGEM / "data" / "vulto_corrigido.db").exists(), reason="repositório da Vulto ausente")


@com_dados_reais
def test_carga_completa_bate_os_tres_numeros_e_roda_uma_vez_so(client, admin):
    with SessionLocal() as db:
        relatorio = Carga(db, ORIGEM, REGISTRO).executar(aviso=lambda _: None)
        db.commit()
    numeros = relatorio.numeros
    assert numeros["faturamento jan/2025 a set/2026 (R$)"] == (Decimal("6498071.30"), Decimal("6498071.30"))
    assert numeros["estoque em 01/10/2026 (peças)"] == (15033, 15033)
    assert numeros["passivo Vulto+ em 01/10/2026 (pontos)"] == (3373251, 3373251)

    with SessionLocal() as db, pytest.raises(CargaRecusada, match="já foi feita"):
        Carga(db, ORIGEM, REGISTRO).executar(aviso=lambda _: None)

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.Loja).where(m.Loja.marca == "VULTO")) == 5
        assert db.scalar(select(func.count()).select_from(m.DecisaoMigracao)) == 66
        # Vendas do app: canal App, expedidas pelo CD, com o status original guardado
        app = db.scalar(select(m.Pedido).where(m.Pedido.numero == "APP-7001205"))
        assert (app.canal, app.loja.nome, app.status, app.status_origem) == (
            "App",
            "CD Cajamar",
            "CANCELADO",
            "Aguardando pagamento",
        )
        # Ship from store: pedido do site com "SFS PIN" sai da Pinheiros
        sfs = db.scalar(
            select(func.count())
            .select_from(m.Pedido)
            .join(m.Loja)
            .where(m.Loja.nome == "Vulto Pinheiros", m.Pedido.canal == "E-commerce")
        )
        assert sfs > 0
        # Venda manual da Batel com a forma de pagamento da planilha (BATEL-4: Crédito 2x)
        batel = db.scalar(select(m.Pedido).where(m.Pedido.numero == "BATEL-4"))
        assert (batel.pagamentos[0].metodo, batel.pagamentos[0].parcelas) == ("CARTAO", 2)
        # Decisão 59: preço da Calça Cargo Comfort subiu para R$ 329,90
        assert {
            v.preco_vigente
            for v in db.scalars(
                select(m.Variacao).join(m.Produto).where(m.Produto.codigo_modelo == "CAL-008", m.Variacao.status == "ATIVO")
            )
        } == {Decimal("329.90")}

    # As telas do painel com os dados da Vulto, e o site da Lorenzi sem eles
    assert client.get("/api/pedidos?busca=APP-7001205", headers=admin).json()[0]["canal"] == "App"
    atendimento = client.get("/api/atendimentos?busca=VLT-40003", headers=admin).json()[0]
    assert atendimento["canal"] == "WHATSAPP" and atendimento["marca"] == "VULTO"
    assert client.get(f"/api/atendimentos/{atendimento['id']}", headers=admin).status_code == 200
    assert client.get("/api/clientes/16643840813", headers=admin).json()["problemasCadastro"] == ["TELEFONE_SEM_DDD"]
    posicao = client.get("/api/estoque/posicao?data=2026-09-14&busca=VLT-CAL-008", headers=admin)
    assert posicao.status_code == 200
    assert all(p["marca"] == "LORENZI" for p in client.get("/api/produtos").json())
    assert {loja["marca"] for loja in client.get("/api/lojas").json()} == {"LORENZI"}
    marco = client.get("/api/financeiro/resumo?de=2026-03-01&ate=2026-03-31", headers=admin)
    assert marco.status_code == 200 and marco.json()["receita"] > 0


def test_carga_recusa_origem_sem_os_arquivos(tmp_path):
    with SessionLocal() as db, pytest.raises(CargaRecusada, match="não encontrados"):
        Carga(db, tmp_path, REGISTRO)


def test_momento_da_venda_fica_em_brasilia():
    from src.migracao_vulto.carga import momento

    assert momento("2025-03-31 22:30:00") == datetime(2025, 3, 31, 22, 30, tzinfo=TZ)
