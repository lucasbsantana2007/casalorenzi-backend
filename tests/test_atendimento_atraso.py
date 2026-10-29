"""Chamado atrasado (decisão 122): o chamado que a Lúcia abriu (pedido de atendimento humano) fica atrasado quando o
cliente espera a resposta da equipe há mais de 30 minutos. A resposta da equipe zera a espera; a próxima mensagem do
cliente começa outra. Chamado aberto fora da Lúcia não entra na regra."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from src import models as m
from src.config import settings
from src.database.connection import SessionLocal
from src.entities.atendimento import aguardando_equipe_desde, atrasado

SEGREDO = "segredo-do-canal-de-teste"
TELEFONE = "5511987654321"


@pytest.fixture(autouse=True)
def segredo(monkeypatch):
    monkeypatch.setattr(settings, "CANAL_WHATSAPP_SEGREDO", SEGREDO)


def _chamado_da_lucia(client) -> int:
    """Cliente pede a equipe no WhatsApp: a Lúcia abre o chamado."""
    for corpo in ({"texto": "minha encomenda não chegou"}, {"botao": "EQUIPE"}):
        resposta = client.post(
            "/api/canais/whatsapp/mensagens", json={"telefone": TELEFONE, **corpo}, headers={"X-Canal-Segredo": SEGREDO}
        )
        assert resposta.status_code == 200, resposta.text
    with SessionLocal() as db:
        return db.scalar(select(m.Atendimento.id).where(m.Atendimento.protocolo == resposta.json()["protocolo"]))


def _recuar(atendimento_id, minutos):
    with SessionLocal() as db:
        for mensagem in db.scalars(select(m.Mensagem).where(m.Mensagem.atendimento_id == atendimento_id)):
            mensagem.enviado_em = mensagem.enviado_em - timedelta(minutes=minutos)
        db.commit()


def _na_lista(client, admin, atendimento_id) -> dict:
    lista = client.get("/api/atendimentos", headers=admin).json()
    return next(a for a in lista if a["id"] == atendimento_id)


def test_espera_conta_da_primeira_mensagem_do_cliente_depois_da_equipe():
    t = [datetime(2026, 10, 29, 10, minuto) for minuto in range(5)]
    assert aguardando_equipe_desde([("CLIENTE", t[0]), ("CLIENTE", t[1])]) == t[0]
    assert aguardando_equipe_desde([("CLIENTE", t[0]), ("ATENDENTE", t[1])]) is None
    assert aguardando_equipe_desde([("CLIENTE", t[0]), ("ATENDENTE", t[1]), ("CLIENTE", t[2]), ("CLIENTE", t[3])]) == t[2]
    assert aguardando_equipe_desde([]) is None
    assert not atrasado(t[0], t[0] + timedelta(minutes=30), 30)
    assert atrasado(t[0], t[0] + timedelta(minutes=31), 30)
    assert not atrasado(None, t[4], 30)


def test_chamado_da_lucia_atrasa_depois_de_30_minutos(client, admin):
    atendimento_id = _chamado_da_lucia(client)
    recente = _na_lista(client, admin, atendimento_id)
    assert recente["atrasado"] is False and recente["aguardandoEquipeDesde"] is not None
    _recuar(atendimento_id, 31)
    assert _na_lista(client, admin, atendimento_id)["atrasado"] is True
    detalhe = client.get(f"/api/atendimentos/{atendimento_id}", headers=admin).json()
    assert detalhe["atrasado"] is True


def test_resposta_da_equipe_tira_o_atraso(client, admin):
    atendimento_id = _chamado_da_lucia(client)
    _recuar(atendimento_id, 45)
    resposta = client.post(f"/api/atendimentos/{atendimento_id}/mensagens", json={"conteudo": "Oi! Vou ver."}, headers=admin)
    assert resposta.status_code == 201, resposta.text
    depois = _na_lista(client, admin, atendimento_id)
    assert depois["atrasado"] is False and depois["aguardandoEquipeDesde"] is None


def test_chamado_aberto_fora_da_lucia_nao_atrasa(client, admin):
    lista = client.get("/api/atendimentos", headers=admin).json()
    assert lista and not any(a["atrasado"] for a in lista)  # os chamados do seed não vieram da Lúcia
