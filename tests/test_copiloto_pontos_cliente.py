"""Decisão 119: pontos Lupe+ de um cliente no Assistente IA e pelo Claude, para quem já vê a ficha do cliente no painel
(Administrador e Lojista). Só o necessário, sem CPF, telefone ou e-mail completo, e só lendo (não lança vencimento)."""

import json
from datetime import timedelta

from src.database.connection import SessionLocal
from src.use_cases import fidelidade
from src.utils.datas import agora
from tests.conftest import _entrar
from tests.test_mcp import chamar, criar_token
from tests.util_assistente import abrir_copiloto, pergunte, sql

MARIANA = 101
CPF_MARIANA = "15881399803"
RAFAEL = "rafael.monteiro@casalorenzi.com.br"  # Lojista
DIEGO = "diego.almeida@casalorenzi.com.br"  # Operador


def _pontos(quantidade: int, ganhos_ha_dias: int) -> None:
    with SessionLocal() as db:
        fidelidade.travar(db, MARIANA)
        fidelidade.lancar(db, MARIANA, "CREDITO", quantidade, agora() - timedelta(days=ganhos_ha_dias), obs="teste")
        db.commit()


def _token(client, email):
    return criar_token(client, _entrar(client, email))


def test_lojista_ve_o_saldo_de_um_cliente_sem_dados_sensiveis(client):
    _pontos(800, 355)  # vence em uns 10 dias
    _pontos(300, 400)  # já venceu: fica de fora do saldo
    movimentos_antes = sql("SELECT count(*) FROM movimentos_pontos WHERE cliente_id = :c", c=MARIANA)

    resultado = chamar(client, _token(client, RAFAEL), "consultar_pontos_cliente", {"busca": "Mariana Costa"})
    assert resultado["isError"] is False
    dados = resultado["structuredContent"]
    assert dados["cliente"] == "Mariana Costa" and dados["saldo"] == "800" and dados["valorEmReais"] == "R$ 40,00"
    assert dados["email"] == "m***@gmail.com" and len(dados["proximosVencimentos"]) == 1
    texto = json.dumps(resultado, ensure_ascii=False)
    assert "mariana.costa@gmail.com" not in texto and CPF_MARIANA not in texto and "158.813" not in texto
    # Só leu: o vencimento dos 300 pontos não foi lançado
    assert sql("SELECT count(*) FROM movimentos_pontos WHERE cliente_id = :c", c=MARIANA) == movimentos_antes


def test_busca_pelo_cpf_e_pelo_email(client):
    _pontos(500, 10)
    token = _token(client, RAFAEL)
    for busca in ("158.813.998-03", "mariana.costa@gmail.com"):
        dados = chamar(client, token, "consultar_pontos_cliente", {"busca": busca})["structuredContent"]
        assert dados["cliente"] == "Mariana Costa" and dados["saldo"] == "500"


def test_varios_parecidos_pedem_para_escolher_sem_mostrar_pontos(client):
    _pontos(500, 10)
    resultado = chamar(client, _token(client, RAFAEL), "consultar_pontos_cliente", {"busca": "gmail"})
    dados = resultado["structuredContent"]
    assert dados["encontrados"] > 1 and "saldo" not in dados
    assert all("***@" in c["email"] or c["email"] == "sem e-mail" for c in dados["candidatos"])


def test_cliente_que_nao_existe(client):
    resultado = chamar(client, _token(client, RAFAEL), "consultar_pontos_cliente", {"busca": "Fulano Inexistente"})
    assert resultado["isError"] is False and resultado["structuredContent"]["encontrados"] == 0


def test_operador_nao_ve_cliente(client):
    recusa = chamar(client, _token(client, DIEGO), "consultar_pontos_cliente", {"busca": "Mariana Costa"})
    assert recusa["isError"] is True and "SEM_PERMISSAO: o perfil Operador" in recusa["content"][0]["text"]


def test_pergunta_no_painel_sem_modelo(client):
    _pontos(800, 355)
    rafael = _entrar(client, RAFAEL)
    conversa = abrir_copiloto(client, rafael)
    resposta = pergunte(client, conversa, rafael, "Me fale quantos pontos no Lupe+ a cliente Mariana Costa possui?")
    assert "Mariana Costa tem 800 pontos Lupe+" in resposta["texto"]
    # Pergunta do programa (sem cliente citado) continua nos números agregados
    resposta = pergunte(client, conversa, rafael, "Quantos pontos vencem nos próximos 30 dias?")
    assert "Mariana" not in resposta["texto"]
