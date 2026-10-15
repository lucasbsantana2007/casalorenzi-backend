"""Reconstrução do estoque da Vulto (etapa 6): transferências contadas uma vez, vendas e devoluções,
abertura estimada, contagem de set/26 como âncora e o saldo em qualquer data."""

import os

import pytest
from sqlalchemy import func, select

from src import models as m
from src.config.settings import VULTO_DADOS
from src.database.connection import SessionLocal
from src.migracao_vulto.__main__ import rodar
from src.migracao_vulto.estoque import _envio, quantidade_contada


def test_textos_do_legado_de_envio_e_de_contagem():
    assert _envio("1 un -> batel") == (4, 1)
    assert _envio("TRANSF SAVASSI 3") == (3, 3)
    assert _envio("enviado pinheiros - 2 pçs") == (1, 2)
    assert _envio("transf p/ eldorado 1un") == (2, 1)
    assert _envio("veio do CD") is None
    assert quantidade_contada("3") == (3, True)
    assert quantidade_contada("4 (3 no estoque + 1 vitrine)") == (4, True)
    assert quantidade_contada("4 (2 no estoque + 1 vitrine)") == (4, False)


@pytest.fixture(scope="module")
def staging():
    if not os.path.isdir(VULTO_DADOS):
        pytest.skip("Pasta VULTO_DADOS com os dados da Vulto não encontrada.")
    rodar(["staging"])


def _soma_lorenzi(db) -> tuple[int, int]:
    lorenzi = select(m.Estoque.id).join(m.Loja, m.Loja.id == m.Estoque.loja_id).where(m.Loja.marca == "LORENZI")
    return (
        db.scalar(select(func.sum(m.Estoque.quantidade)).where(m.Estoque.id.in_(lorenzi))),
        db.scalar(select(func.count()).select_from(m.Movimentacao).where(m.Movimentacao.estoque_id.in_(lorenzi))),
    )


def _ocorrencia(db, codigo: str) -> m.MigracaoOcorrencia:
    return db.scalars(select(m.MigracaoOcorrencia).where(m.MigracaoOcorrencia.codigo_problema == codigo)).first()


def test_estoque_reconstruido_ancorado_na_contagem(staging, client, admin):
    with SessionLocal() as db:
        antes_lorenzi = _soma_lorenzi(db)
    rodar(["lojas", "produtos", "clientes", "vendas", "estoque"])

    lojas = {loja["nome"]: loja["id"] for loja in client.get("/api/lojas?marca=VULTO", headers=admin).json()}
    # No fim do dia da contagem, o saldo de Pinheiros é o contado (2.436 peças − 14 de SKUs ilegíveis)
    na_contagem = client.get(f"/api/estoque/posicao?data=2026-09-20&lojaId={lojas['Vulto Pinheiros']}", headers=admin).json()
    assert sum(i["quantidadeNaData"] for i in na_contagem["itens"]) == 2422
    # Saldo em 01/10/2026 = contagem + movimentos depois dela; a Savassi (contada por modelo) fecha no total contado
    em_outubro = client.get("/api/estoque/posicao?data=2026-10-01&marca=VULTO&agrupar=produto", headers=admin).json()
    por_loja: dict[str, int] = {}
    for item in em_outubro["itens"]:
        por_loja[item["loja"]["nome"]] = por_loja.get(item["loja"]["nome"], 0) + item["quantidadeNaData"]
    assert por_loja["Vulto Savassi"] == 2114
    assert por_loja["Vulto Pinheiros"] == 2406
    assert {item["loja"]["marca"] for item in em_outubro["itens"]} == {"VULTO"}

    with SessionLocal() as db:
        # A Casa Lorenzi não muda
        assert _soma_lorenzi(db) == antes_lorenzi
        # Transferências anotadas dos dois lados contam uma vez
        transferencias = _ocorrencia(db, "TRANSFERENCIA_DOS_DOIS_LADOS")
        assert "5290 peças aparecem dos dois lados" in transferencias.descricao
        # A tabela estoque da Vulto (com 1.156 negativos) não entra
        assert "1156 saldos negativos" in _ocorrencia(db, "ESTOQUE_DO_LEGADO_SO_COMPARACAO").descricao
        # Contagem sem data (Eldorado, Savassi, Batel) e rateio da Savassi ficam marcados como estimativa
        assert db.scalar(select(func.count()).where(m.MigracaoOcorrencia.codigo_problema == "CONTAGEM_SEM_DATA")) == 3
        assert db.scalar(select(func.count()).where(m.MigracaoOcorrencia.codigo_problema == "SAVASSI_CONTAGEM_POR_MODELO")) == 161
        # Toda devolução migrada tem a movimentação que devolveu a peça
        vulto = select(m.Loja.id).where(m.Loja.marca == "VULTO")
        assert db.scalar(select(func.count()).where(m.Devolucao.loja_id.in_(vulto), m.Devolucao.movimentacao_id.is_(None))) == 0
        # Nenhum saldo negativo no histórico antes da contagem (abertura estimada); depois dela, só os marcados
        negativos = db.scalar(
            select(func.count()).select_from(m.Estoque).where(m.Estoque.loja_id.in_(vulto), m.Estoque.quantidade < 0)
        )
        assert negativos == _ocorrencia(db, "SALDO_NEGATIVO_DEPOIS_DA_CONTAGEM").impacto
        movimentacoes = db.scalar(
            select(func.count()).select_from(m.Movimentacao).join(m.Estoque).where(m.Estoque.loja_id.in_(vulto))
        )

    rodar(["estoque"])  # de novo: refaz igual
    with SessionLocal() as db:
        vulto = select(m.Loja.id).where(m.Loja.marca == "VULTO")
        assert (
            db.scalar(select(func.count()).select_from(m.Movimentacao).join(m.Estoque).where(m.Estoque.loja_id.in_(vulto)))
            == movimentacoes
        )
