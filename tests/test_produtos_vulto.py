"""Migração dos produtos da Vulto (etapa 3) com os dados reais: catálogo unificado, grafias de SKU,
código reaproveitado, regras de preço e custo, descontinuados, e a vitrine da Casa Lorenzi intacta.
Pulados se a pasta VULTO_DADOS não existir."""

import os
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from src import models as m
from src.config.settings import VULTO_DADOS
from src.database.connection import SessionLocal
from src.entities.produto import alias_normalizado
from src.migracao_vulto import produtos
from src.migracao_vulto.__main__ import rodar

pytestmark = pytest.mark.skipif(not os.path.isdir(VULTO_DADOS), reason="Pasta VULTO_DADOS com os dados da Vulto não encontrada.")


@pytest.fixture(scope="module")
def staging():
    """O staging fica fora das tabelas que o seed recria: carrega uma vez para o módulo."""
    rodar(["staging"])


@pytest.fixture
def migrado(staging):
    return {r.dominio: r for r in rodar(["lojas", "produtos"])}


def _variacao(db, sku: str) -> m.Variacao:
    return db.scalar(select(m.Variacao).where(m.Variacao.sku == sku))


def _contar(db, modelo, *condicoes) -> int:
    return db.scalar(select(func.count()).select_from(modelo).where(*condicoes))


def test_catalogo_vira_produtos_da_vulto_nas_categorias_da_plataforma(migrado):
    resultado = migrado["produtos"]
    assert resultado.lidos == 1173 and resultado.descartados == 0
    with SessionLocal() as db:
        vulto = m.Produto.marca == "VULTO"
        assert _contar(db, m.Produto, vulto) == 181  # 174 modelos + 6 peças de 2024 + o "não catalogado"
        assert _contar(db, m.Produto, m.Produto.marca == "LORENZI") == 13  # os da Lorenzi continuam iguais
        categorias = set(db.scalars(select(m.Categoria.nome).join(m.Produto).where(vulto)))
        assert categorias == {
            "Malharia", "Calças", "Camisaria", "Tricô", "Acessórios", "Saias", "Vestidos",
            "Bermudas e Shorts", "Outerwear", "Não catalogado",
        }  # fmt: skip
        short = db.scalar(select(m.Produto).where(m.Produto.nome == "Short Jeans Clássica"))
        assert (short.colecao, short.estacao, short.genero, short.categoria.nome) == (
            "Verão 26",
            "Verão",
            None,
            "Bermudas e Shorts",
        )


def test_toda_grafia_vendida_acha_uma_variacao_e_rodar_de_novo_nao_duplica(migrado):
    with SessionLocal() as db:
        antes = (_contar(db, m.Variacao), _contar(db, m.SkuAlias), _contar(db, m.DePara), _contar(db, m.MigracaoOcorrencia))
        vendidas = {alias_normalizado(s) for s in db.scalars(text("SELECT DISTINCT sku FROM legado_vulto.db__itens_venda"))}
        com_alias = set(db.scalars(select(m.SkuAlias.alias_normalizado)))
        assert vendidas - com_alias == {"TESTE-001"}  # venda de teste: descartada na migração das vendas
    rodar(["produtos"])
    with SessionLocal() as db:
        depois = (_contar(db, m.Variacao), _contar(db, m.SkuAlias), _contar(db, m.DePara), _contar(db, m.MigracaoOcorrencia))
    assert depois == antes


def test_codigo_reaproveitado_aponta_para_a_peca_certa_pela_data(client, admin, migrado):
    with SessionLocal() as db:
        antiga, nova = _variacao(db, "VLT-JAQ-001-OLI-P-2024"), _variacao(db, "VLT-JAQ-001-OLI-P")
        assert antiga.produto.nome.endswith("(2024)") and not antiga.produto.ativo and not antiga.ativa
        assert nova.produto.nome == "Bomber Matelassê" and nova.produto.ativo
    em_2025 = client.get("/api/produtos/sku/JAQ001VP?data=2025-06-01", headers=admin).json()
    em_2026 = client.get("/api/produtos/sku/JAQ001VP?data=2026-06-01", headers=admin).json()
    assert em_2025["variacao"]["sku"] == "VLT-JAQ-001-OLI-P-2024" and em_2025["alias"]["validoAte"] == "2026-04-18"
    assert em_2026["variacao"]["sku"] == "VLT-JAQ-001-OLI-P" and em_2026["alias"]["validoDe"] == "2026-04-19"
    assert client.get("/api/produtos/sku/JAQ001VP", headers=admin).json()["variacao"]["sku"] == "VLT-JAQ-001-OLI-P"


def test_busca_por_qualquer_grafia_e_so_para_a_equipe(client, admin, mariana, migrado):
    for grafia in ("BER001B40", "vlt ber 001 branco 40", "VLT-BER-001-BRA-40"):
        r = client.get(f"/api/produtos/sku/{grafia}", headers=admin)
        assert r.status_code == 200 and r.json()["variacao"]["sku"] == "VLT-BER-001-BRA-40", grafia
    assert client.get("/api/produtos/sku/DIVERSO", headers=admin).json()["variacao"]["sku"] == produtos.SKU_NAO_CATALOGADO
    assert client.get("/api/produtos/sku/CL-NAO-EXISTE", headers=admin).status_code == 404
    assert client.get("/api/produtos/sku/BER001B40").status_code == 401
    assert client.get("/api/produtos/sku/BER001B40", headers=mariana).status_code == 401


def test_vitrine_continua_so_com_a_lorenzi(client, admin, migrado):
    vitrine = client.get("/api/produtos").json()
    assert len(vitrine) == 13 and {p["marca"] for p in vitrine} == {"LORENZI"}
    assert len(client.get("/api/produtos?marca=VULTO").json()) == 13  # visitante não escolhe a marca
    assert len(client.get("/api/produtos?marca=VULTO", headers=admin).json()) == 181
    vulto_id = client.get("/api/produtos?marca=VULTO", headers=admin).json()[0]["id"]
    assert client.get(f"/api/produtos/{vulto_id}").status_code == 404
    assert client.get(f"/api/produtos/{vulto_id}", headers=admin).status_code == 200


def test_preco_entre_colecoes_segue_a_regra_parametrizada(migrado, monkeypatch):
    """Short Jeans Clássica: R$ 129,90 no Verão 25 e R$ 139,90 no Verão 26."""
    with SessionLocal() as db:
        assert db.scalar(select(m.Produto.preco_base).where(m.Produto.nome == "Short Jeans Clássica")) == Decimal("129.90")
        conflitos = db.scalars(
            select(m.MigracaoOcorrencia).where(m.MigracaoOcorrencia.codigo_problema == "PRECO_ENTRE_COLECOES")
        ).all()
        # 22 peças em duas coleções; em 8 (Verão 26 × Atemporais, revisada em mar/26) a mais nova já é a
        # mais barata e as duas regras dão o mesmo preço. Nas outras 14, o menor fica R$ 10 a 30 abaixo.
        assert len(conflitos) == 22 and all(o.impacto >= 0 for o in conflitos)
        assert sum(1 for o in conflitos if o.impacto > 0) == 14 and sum(o.impacto for o in conflitos) == Decimal("260.00")
    monkeypatch.setattr(produtos, "REGRA_PRECO", "MAIS_NOVA")
    rodar(["produtos"])
    with SessionLocal() as db:
        assert db.scalar(select(m.Produto.preco_base).where(m.Produto.nome == "Short Jeans Clássica")) == Decimal("139.90")


def test_descontinuados_varios_tamanhos_ean_e_custos(migrado):
    with SessionLocal() as db:
        # Só a cor bege do cinto saiu de linha: a variação fica inativa e o produto continua
        cinto = _variacao(db, "VLT-ACE-005-BEG-U")
        assert not cinto.ativa and cinto.produto.ativo
        # "P/M/G/GG" numa linha só vira uma variação por tamanho, sem EAN
        vestido = [_variacao(db, f"VLT-VES-006-MRR-{t}") for t in ("P", "M", "G", "GG")]
        assert all(v is not None and v.ean is None for v in vestido)
        # EAN único e nunca o fictício
        assert _contar(db, m.Variacao, m.Variacao.ean == "7890000000000") == 0
        # Último custo (a regra de Compras) e custo médio das notas (a do Financeiro)
        meia = _variacao(db, "VLT-ACE-004-CIN-U")
        assert (meia.preco_custo, meia.custo_medio) == (Decimal("61.60"), Decimal("68.90"))
        # Nenhuma variação da Vulto ganhou estoque em loja da Lorenzi (o estoque vem na etapa 6)
        assert (
            _contar(
                db, m.Estoque, m.Estoque.variacao_id.in_(select(m.Variacao.id).join(m.Produto).where(m.Produto.marca == "VULTO"))
            )
            == 0
        )
