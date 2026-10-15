"""Atendimento da Vulto (etapa 8): funcionários sem senha e sem e-mail (inativos), o CSV de atendimento em
atendimentos + mensagens, com o cliente e o pedido certos para a equipe não perguntar de novo."""

import os

import pytest
from sqlalchemy import func, select

from src import models as m
from src.config.settings import VULTO_DADOS
from src.database.connection import SessionLocal
from src.migracao_vulto.__main__ import rodar
from src.migracao_vulto.atendimento import DEVOLUCAO, ENTREGA, ORIGEM, PONTOS, TROCA, mensagens, tipo_do_atendimento
from src.migracao_vulto.usuarios import ORIGEM_FUNCIONARIOS, atendente


def test_tipo_pelo_assunto_tags_e_texto():
    assert tipo_do_atendimento("troca/devolução", "", "Quero devolver a calça, não gostei") == DEVOLUCAO
    assert tipo_do_atendimento("troca/devolução", "", "Ficou grande. Quero trocar pelo 38.") == TROCA
    assert tipo_do_atendimento("Atraso entrega", "", "") == ENTREGA
    assert tipo_do_atendimento("Pontos Vulto+", "", "") == PONTOS
    assert tipo_do_atendimento("", "entrega;atraso", "") == ENTREGA  # sem assunto: pelas tags
    assert tipo_do_atendimento("", "", "") is None


def test_conversa_embutida_vira_mensagens():
    texto = "Oi, meu pedido não chegou\n\n[Atendente]: Vou verificar\n\n[Bot]: Recebemos sua mensagem\n[Cliente]: Obrigada"
    assert mensagens(texto) == [
        ("CLIENTE", "Oi, meu pedido não chegou"),
        ("ATENDENTE", "Vou verificar"),
        ("SISTEMA", "Recebemos sua mensagem"),
        ("CLIENTE", "Obrigada"),
    ]


def test_grafias_do_atendente():
    assert atendente("julia") == atendente("Júlia (SAC)") == "Júlia (SAC)"
    assert atendente("renata.sac") == "Renata (SAC)"
    assert atendente("Bot Vulto") is None
    assert atendente("time insta") is None


@pytest.fixture(scope="module")
def staging():
    if not os.path.isdir(VULTO_DADOS):
        pytest.skip("Pasta VULTO_DADOS com os dados da Vulto não encontrada.")
    rodar(["staging"])


def _atendimento_da_linha(db, linha: str) -> int:
    return db.scalar(select(m.DePara.id_destino).where(m.DePara.origem == ORIGEM, m.DePara.id_origem == linha))


def test_atendimento_da_vulto(staging, client, admin):
    lorenzi = client.get("/api/atendimentos?marca=LORENZI", headers=admin).json()
    rodar(["lojas", "produtos", "clientes", "usuarios", "vendas", "atendimento"])

    # Os da Casa Lorenzi continuam iguais
    assert client.get("/api/atendimentos?marca=LORENZI", headers=admin).json() == lorenzi
    vulto = client.get("/api/atendimentos?marca=VULTO", headers=admin).json()
    assert len(vulto) == 1637  # 1.664 linhas − 17 repetidas − 10 spam
    assert len(client.get("/api/atendimentos?marca=VULTO&canal=INSTAGRAM", headers=admin).json()) == 404
    # A busca acha pelo contato
    assert any(a["contato"] == "@yuri.alves" for a in client.get("/api/atendimentos?busca=yuri.alves", headers=admin).json())

    with SessionLocal() as db:
        sem_ddd = _atendimento_da_linha(db, "41622")  # WhatsApp "96335-5304" (sem DDD), pedido S104033
        sem_cliente = db.scalar(select(m.Atendimento.id).where(m.Atendimento.cliente_id.is_(None)).limit(1))
        sem_cliente_total = db.scalar(select(func.count()).where(m.Atendimento.cliente_id.is_(None)))

    # Telefone sem DDD não identifica ninguém: o cliente vem do pedido citado
    detalhe = client.get(f"/api/atendimentos/{sem_ddd}", headers=admin).json()
    assert (detalhe["canal"], detalhe["contato"], detalhe["marca"]) == ("WHATSAPP", "96335-5304", "VULTO")
    assert detalhe["pedido"]["pedidoExterno"] == "S104033"
    assert detalhe["cliente"]["nome"] == "Thiago Monteiro Nogueira"  # o contato se apresentou como "thiago"
    assert detalhe["pedido"]["numero"] in [p["numero"] for p in detalhe["pedidosDoCliente"]]
    assert detalhe["mensagens"][0]["autorTipo"] == "CLIENTE"

    # Sem cliente: o contato e o nome que a pessoa deu
    detalhe = client.get(f"/api/atendimentos/{sem_cliente}", headers=admin).json()
    assert detalhe["clienteId"] is None and detalhe["cliente"]["identificado"] is False
    assert detalhe["cliente"]["nome"] and detalhe["contato"]
    assert sem_cliente_total == 250
    # O painel continua abrindo com atendimentos sem cliente
    assert client.get("/api/dashboard/resumo", headers=admin).status_code == 200

    with SessionLocal() as db:
        # Funcionários: inativos, sem e-mail e sem senha; Diego, Paula e Marina como administradores
        vindos = select(m.DePara.id_destino).where(m.DePara.origem == ORIGEM_FUNCIONARIOS)
        usuarios = list(db.scalars(select(m.Usuario).where(m.Usuario.id.in_(vindos))))
        assert len(usuarios) == 21  # 24 − teste da TI, admin genérico, estagiário
        assert all(not u.ativo and u.email is None and u.senha_hash is None for u in usuarios)
        diego = next(u for u in usuarios if u.nome.startswith("Diego"))
        assert diego.papel == "ADMINISTRADOR"
        total = db.scalar(select(func.count()).select_from(m.Atendimento))
    # Reativar sem e-mail não pode: o convite não teria para onde ir
    resposta = client.patch(f"/api/admin/funcionarios/{diego.id}/status", json={"ativo": True}, headers=admin)
    assert resposta.status_code == 422 and "e-mail" in resposta.json()["detail"]

    with SessionLocal() as db:
        ocorrencias = db.scalar(select(func.count()).where(m.MigracaoOcorrencia.dominio == "atendimento"))
    rodar(["usuarios", "atendimento"])  # de novo: refaz igual, com as mesmas ocorrências
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.Atendimento)) == total
        assert db.scalar(select(func.count()).where(m.MigracaoOcorrencia.dominio == "atendimento")) == ocorrencias
        assert db.scalar(select(func.count()).select_from(m.Usuario).where(m.Usuario.id.in_(vindos))) == 21
