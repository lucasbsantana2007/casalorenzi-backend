"""Aviso por e-mail de pontos Lupe+ a vencer (decisão 82): desligado por padrão, uma vez por vencimento, sem
número quando o e-mail é de mais de uma conta, modo teste para o e-mail do time, limite diário e nenhum
aviso gravado sem o e-mail ter saído."""

from datetime import timedelta

import pytest

from src.config import settings
from src.database.connection import SessionLocal
from src.use_cases import automacoes, avisos_pontos, fidelidade
from src.utils.datas import agora
from tests.util_assistente import sql

MARIANA, RICARDO = 101, 102
EMAIL_MARIANA = "mariana.costa@gmail.com"


def _pontos(cliente_id: int, quantidade: int, ganhos_ha_dias: int) -> None:
    """Pontos ganhos há N dias: vencem 12 meses depois (355 dias atrás = vencem em uns 10 dias)."""
    with SessionLocal() as db:
        fidelidade.travar(db, cliente_id)
        fidelidade.lancar(db, cliente_id, "CREDITO", quantidade, agora() - timedelta(days=ganhos_ha_dias), obs="teste")
        db.commit()


@pytest.fixture
def enviados(monkeypatch):
    """Liga o aviso e troca o Resend por uma lista."""
    caixa = []
    monkeypatch.setattr(settings, "AVISO_PONTOS_ENVIAR", True)
    monkeypatch.setattr(settings, "AVISO_PONTOS_TESTE_PARA", "")
    monkeypatch.setattr(avisos_pontos, "PAUSA_ENTRE_ENVIOS", 0)
    monkeypatch.setattr(avisos_pontos, "_enviar_de_verdade", caixa.append)
    return caixa


def _avisos() -> list:
    return sql("SELECT cliente_id, pontos, modo, email, sem_numeros FROM avisos_pontos ORDER BY cliente_id, vencimento")


def test_desligado_por_padrao_nao_manda_nada(client, monkeypatch):
    monkeypatch.setattr(settings, "AVISO_PONTOS_ENVIAR", False)
    _pontos(MARIANA, 800, 355)
    execucao = automacoes.executar("aviso_pontos")
    assert execucao.status == "SUCESSO" and "desligado" in execucao.detalhe
    assert _avisos() == []


def test_avisa_uma_vez_por_vencimento(client, enviados):
    _pontos(MARIANA, 800, 355)
    _pontos(RICARDO, 300, 400)  # já venceu: não é aviso
    _pontos(RICARDO, 500, 300)  # vence daqui a uns 2 meses: ainda não

    primeira = automacoes.executar("aviso_pontos")
    assert primeira.status == "SUCESSO" and primeira.criados == 1
    [email] = enviados
    assert email.para == EMAIL_MARIANA
    assert "800 pontos Lupe+ vencem em" in email.assunto
    assert "Você tem 800 pontos Lupe+ (R$ 40,00 em desconto)" in email.texto
    assert "aviso sobre a sua conta Lupe+" in email.texto and "/cliente/pontos" in email.texto
    assert _avisos() == [(MARIANA, 800, "REAL", EMAIL_MARIANA, False)]

    # De novo: ninguém recebe duas vezes o mesmo aviso
    segunda = automacoes.executar("aviso_pontos", forcar=True)
    assert segunda.criados == 0 and len(enviados) == 1

    # Um lote novo entra na janela: avisa só dele, mas o e-mail mostra os dois vencimentos
    _pontos(MARIANA, 200, 345)
    automacoes.executar("aviso_pontos", forcar=True)
    assert len(enviados) == 2
    assert "1.000 pontos Lupe+" in enviados[1].assunto and "200 pontos em" in enviados[1].texto
    assert [linha[1] for linha in _avisos()] == [800, 200]


def test_email_de_duas_contas_vai_sem_o_saldo(client, enviados):
    sql("UPDATE clientes SET email = :e WHERE id = :c", e=EMAIL_MARIANA, c=RICARDO)
    _pontos(MARIANA, 800, 355)
    _pontos(RICARDO, 1200, 350)
    automacoes.executar("aviso_pontos")
    assert len(enviados) == 2
    for email in enviados:
        assert email.assunto.endswith("Há pontos Lupe+ vencendo na sua conta")
        assert "800" not in email.texto and "1.200" not in email.texto and "saldo" in email.texto
    assert all(sem_numeros for *_, sem_numeros in _avisos())


def test_modo_teste_manda_para_o_time_e_nao_conta_como_aviso_real(client, enviados, monkeypatch):
    monkeypatch.setattr(settings, "AVISO_PONTOS_TESTE_PARA", "time@exemplo.com")
    _pontos(MARIANA, 800, 355)
    automacoes.executar("aviso_pontos")
    [email] = enviados
    assert email.para == "time@exemplo.com" and email.assunto.startswith(f"[Teste · para {EMAIL_MARIANA}]")
    assert _avisos() == [(MARIANA, 800, "TESTE", "time@exemplo.com", False)]

    # Desligado o modo teste, a cliente recebe o aviso de verdade
    monkeypatch.setattr(settings, "AVISO_PONTOS_TESTE_PARA", "")
    automacoes.executar("aviso_pontos", forcar=True)
    assert enviados[1].para == EMAIL_MARIANA


def test_limite_diario_deixa_o_resto_para_amanha(client, enviados, monkeypatch):
    monkeypatch.setattr(settings, "AVISO_PONTOS_LIMITE_DIA", 1)
    _pontos(MARIANA, 800, 350)
    _pontos(RICARDO, 500, 355)  # vence antes: vai primeiro
    execucao = automacoes.executar("aviso_pontos")
    assert execucao.criados == 1 and "1 para os próximos dias" in execucao.detalhe
    assert [email.para for email in enviados] == [sql("SELECT email FROM clientes WHERE id = :c", c=RICARDO)[0][0]]
    # No mesmo dia, rodar de novo não passa do limite
    assert automacoes.executar("aviso_pontos", forcar=True).criados == 0


def test_falha_no_envio_nao_grava_e_tenta_de_novo(client, enviados, monkeypatch):
    def fora_do_ar(email):
        raise RuntimeError("Resend respondeu 500")

    _pontos(MARIANA, 800, 355)
    monkeypatch.setattr(avisos_pontos, "_enviar_de_verdade", fora_do_ar)
    execucao = automacoes.executar("aviso_pontos")
    assert execucao.status == "SUCESSO" and "1 falha" in execucao.detalhe and _avisos() == []

    monkeypatch.setattr(avisos_pontos, "_enviar_de_verdade", enviados.append)
    automacoes.executar("aviso_pontos", forcar=True)
    assert len(enviados) == 1 and len(_avisos()) == 1


def test_sem_email_valido_ou_conta_excluida_fica_de_fora(client, enviados):
    sql("UPDATE clientes SET email = 'sem-arroba' WHERE id = :c", c=MARIANA)
    sql("UPDATE clientes SET excluido_em = now() WHERE id = :c", c=RICARDO)
    _pontos(MARIANA, 800, 355)
    _pontos(RICARDO, 500, 355)
    automacoes.executar("aviso_pontos")
    assert enviados == [] and _avisos() == []
