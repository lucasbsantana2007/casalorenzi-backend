"""Migração dos clientes da Vulto (etapa 4): deduplicação CPF → e-mail → telefone, também contra a
Casa Lorenzi, consentimento (LGPD), conta Vulto+ e a busca unificada do cliente nas duas marcas."""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from src import models as m
from src.config.settings import VULTO_DADOS
from src.database.connection import SessionLocal
from src.migracao_vulto import clientes
from src.migracao_vulto.__main__ import rodar
from src.migracao_vulto.clientes import Registro, agrupar

_SEM_DADOS = not os.path.isdir(VULTO_DADOS)


def _r(origem="x", id_origem="1", **campos) -> Registro:
    return Registro(origem, id_origem, datetime(2025, 1, 1, tzinfo=UTC), **campos)


# ---------- Regra de deduplicação (sem banco) ----------


def test_cpf_junta_e_email_e_telefone_ligam_o_resto():
    planilha = _r(id_origem="1", cpf="40132410800", email="rodrigo@x.com")
    venda_por_email = _r(id_origem="2", email="rodrigo@x.com")
    venda_por_cpf = _r(id_origem="3", cpf="40132410800", telefone="+5511900712224")
    contato_por_telefone = _r(id_origem="4", telefone="+5511900712224", nome="rodrigo")
    grupos = agrupar([planilha, venda_por_email, venda_por_cpf, contato_por_telefone])
    assert len(grupos) == 1 and grupos[0].regras == {"CPF", "EMAIL", "TELEFONE"}


def test_cpfs_diferentes_nunca_viram_uma_pessoa_so():
    """Casal ou família com o mesmo e-mail ou telefone: duas pessoas."""
    ela = _r(id_origem="1", cpf="40132410800", email="familia@x.com", telefone="+5511900712224")
    ele = _r(id_origem="2", cpf="52998224725", email="familia@x.com", telefone="+5511900712224")
    assert len(agrupar([ela, ele])) == 2


def test_telefone_nao_junta_quem_tem_emails_diferentes():
    a = _r(id_origem="1", email="a@x.com", telefone="+5511900712224")
    b = _r(id_origem="2", email="b@x.com", telefone="+5511900712224")
    assert len(agrupar([a, b])) == 2
    sem_email = _r(id_origem="3", telefone="+5511900712224")
    assert len(agrupar([a, sem_email])) == 1


# ---------- Com os dados reais ----------


@pytest.fixture(scope="module")
def staging():
    if _SEM_DADOS:
        pytest.skip("Pasta VULTO_DADOS com os dados da Vulto não encontrada.")
    rodar(["staging"])


def _contar(db, modelo, *condicoes) -> int:
    return db.scalar(select(func.count()).select_from(modelo).where(*condicoes))


def _cliente_da_linha(db, linha: int) -> m.Cliente:
    cliente_id = db.scalar(
        select(m.DePara.id_destino).where(m.DePara.origem == clientes.ORIGEM_CLIENTES, m.DePara.id_origem == str(linha))
    )
    return db.get(m.Cliente, cliente_id)


def test_clientes_reais_deduplicados_com_consentimento_conservador(staging):
    resultado = {r.dominio: r for r in rodar(["lojas", "clientes"])}["clientes"]
    with SessionLocal() as db:
        vulto = m.Cliente.id.in_(select(m.DePara.id_destino).where(m.DePara.origem == clientes.ORIGEM_CRIADO))
        assert _contar(db, m.Cliente, vulto) == resultado.carregados == 4854
        assert _contar(db, m.ContaPontos) == 3071  # um por cliente com CPF
        # Aba Clientes: 2.535 linhas = 2.367 CPFs distintos (131 repetidos) + 28 linhas sem CPF válido, uma
        # delas ligada pelo e-mail a quem tem CPF: 2.394 clientes
        da_aba = select(func.count(func.distinct(m.DePara.id_destino))).where(m.DePara.origem == clientes.ORIGEM_CLIENTES)
        assert db.scalar(da_aba) == 2394
        assert db.scalar(select(func.count(m.Cliente.cpf.distinct()))) == _contar(db, m.Cliente, m.Cliente.cpf.is_not(None))

        # Mesma pessoa na aba Clientes (linha 168) e nos antigos (linha 201)
        antigo = db.scalar(
            select(m.DePara.id_destino).where(m.DePara.origem == clientes.ORIGEM_ANTIGOS, m.DePara.id_origem == "201")
        )
        assert _cliente_da_linha(db, 168).id == antigo

        # LGPD: "N" é sem consentimento; "sim" com "não ligar" na observação também
        assert not _cliente_da_linha(db, 120).aceita_marketing  # Paulo Vieira Teixeira, aceita_msg = N
        emanuelly = _cliente_da_linha(db, 75)  # aceita_msg = sim, obs = não ligar
        assert not emanuelly.aceita_marketing
        aceitam = db.scalars(select(m.Cliente).where(m.Cliente.aceita_marketing)).all()
        assert aceitam and all(c.aceita_marketing_origem == clientes.CONSENTIMENTO_ORIGEM for c in aceitam)

        # Telefone sem DDD fica sem telefone; nome com espaços sobrando é limpo; CPF sem máscara
        felipe = _cliente_da_linha(db, 14)
        assert felipe.telefone is None and felipe.cpf == "86367772677"
        assert _cliente_da_linha(db, 116).nome == "Melissa Gomes Dias"

        # Quem só aparece nas vendas entra com nome provisório, sempre com ocorrência
        provisorios = _contar(db, m.Cliente, m.Cliente.nome == clientes.NOME_PROVISORIO)
        sem_nome = _contar(db, m.MigracaoOcorrencia, m.MigracaoOcorrencia.codigo_problema == "CLIENTE_SEM_NOME")
        assert provisorios == sem_nome > 0

    rodar(["clientes"])  # de novo: atualiza, não duplica
    with SessionLocal() as db:
        assert _contar(db, m.Cliente, vulto) == 4854 and _contar(db, m.ContaPontos) == 3071


def test_cliente_que_ja_era_da_lorenzi_vira_um_registro_so(staging, client, admin):
    """Paulo Vieira Teixeira já era cliente da Lorenzi (com outro e-mail e sem telefone) e aceitava
    mensagens da Lorenzi; na Vulto, recusou (aceita_msg = N)."""
    with SessionLocal() as db:
        paulo = m.Cliente(
            nome="Paulo V. Teixeira",
            cpf="34335916280",
            email="paulo.lorenzi@exemplo.com",
            aceita_marketing=True,
            aceita_marketing_em=datetime(2026, 1, 1, tzinfo=UTC),
            aceita_marketing_origem="cadastro do site",
        )
        db.add(paulo)
        db.commit()
        paulo_id = paulo.id

    rodar(["lojas", "clientes"])
    with SessionLocal() as db:
        paulo = db.get(m.Cliente, paulo_id)
        assert _cliente_da_linha(db, 120).id == paulo_id
        assert _contar(db, m.Cliente, m.Cliente.cpf == "34335916280") == 1
        # Nada da Lorenzi é trocado: só completa o que estava vazio e respeita a recusa
        assert (paulo.nome, paulo.email) == ("Paulo V. Teixeira", "paulo.lorenzi@exemplo.com")
        assert paulo.telefone == "+5521960011211"
        assert paulo.aceita_marketing is False
        assert _contar(db, m.ContaPontos, m.ContaPontos.cliente_id == paulo_id) == 1

    # A busca unificada acha a mesma pessoa por qualquer identificador
    for parametros in ({"cpf": "343.359.162-80"}, {"email": "paulo.lorenzi@exemplo.com"}, {"telefone": "(21) 96001-1211"}):
        r = client.get("/api/clientes/unificado", params=parametros, headers=admin)
        assert r.status_code == 200 and [c["nome"] for c in r.json()] == ["Paulo V. Teixeira"], parametros
    assert client.get("/api/clientes/unificado", params={"email": "paulo.teixeira12@gmail.com"}, headers=admin).json() == []


def test_busca_unificada_mostra_os_pedidos_das_duas_marcas(client, admin, lojista, mariana):
    r = client.get("/api/clientes/unificado", params={"telefone": "(11) 98422-1937"}, headers=admin)
    assert r.status_code == 200
    (encontrada,) = r.json()
    assert encontrada["id"] == "15881399803" and encontrada["vultoMais"] is None
    assert set(encontrada["totaisPorMarca"]) == {"LORENZI"}
    assert encontrada["pedidos"] and all(p["marca"] == "LORENZI" for p in encontrada["pedidos"])
    assert encontrada["totaisPorMarca"]["LORENZI"]["pedidos"] == len(encontrada["pedidos"])

    assert client.get("/api/clientes/unificado", params={"cpf": "15881399803"}, headers=lojista).status_code == 200
    assert client.get("/api/clientes/unificado", headers=admin).status_code == 422
    assert client.get("/api/clientes/unificado", params={"telefone": "98422-1937"}, headers=admin).status_code == 422
    assert client.get("/api/clientes/unificado", params={"cpf": "15881399803"}).status_code == 401
    assert client.get("/api/clientes/unificado", params={"cpf": "15881399803"}, headers=mariana).status_code in (401, 403)
    # Rota de cliente por CPF continua funcionando ("unificado" não é confundido com um id)
    assert client.get("/api/clientes/15881399803", headers=admin).status_code == 200
