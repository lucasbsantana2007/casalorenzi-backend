"""Decisão 118: o Lojista consulta Lupe+, pedidos e atendimentos no Assistente IA (e pelo Claude), sem ver faturamento,
pedidos de outra loja ou dados pessoais de clientes. Cada perfil continua com o recorte da tela correspondente do painel."""

import json

import pytest

from src.utils.datas import agora
from tests.conftest import _entrar
from tests.test_mcp import chamar, criar_token
from tests.util_assistente import abrir_copiloto, pergunte, sql

RAFAEL = "rafael.monteiro@casalorenzi.com.br"  # Lojista da loja 1 (Casa Lorenzi)
DIEGO = "diego.almeida@casalorenzi.com.br"  # Operador da loja 1
HELENA = "helena@casalorenzi.com.br"


@pytest.fixture
def pedidos_em_duas_lojas():
    """Dois pedidos em separação da Casa Lorenzi, um na loja 1 e um na loja 2, com cliente identificado."""
    linhas = sql(
        "SELECT p.id FROM pedidos p JOIN lojas l ON l.id = p.loja_id "
        "WHERE l.marca = 'LORENZI' AND p.cliente_id IS NOT NULL ORDER BY p.id LIMIT 2"
    )
    assert len(linhas) == 2, "o seed precisa de dois pedidos com cliente na Casa Lorenzi"
    (da_loja_1,), (da_loja_2,) = linhas
    for pedido_id, loja_id, numero in ((da_loja_1, 1, "CL-TESTE-1"), (da_loja_2, 2, "CL-TESTE-2")):
        sql(
            "UPDATE pedidos SET loja_id = :l, status = 'PROCESSANDO', criado_em = :t, numero = :n WHERE id = :p",
            l=loja_id,
            t=agora(),
            n=numero,
            p=pedido_id,
        )
    nomes = [
        n
        for (n,) in sql(
            "SELECT c.nome FROM pedidos p JOIN clientes c ON c.id = p.cliente_id WHERE p.id IN (:a, :b)", a=da_loja_1, b=da_loja_2
        )
    ]
    return nomes


def _token(client, email):
    return criar_token(client, _entrar(client, email))


def _texto(resultado) -> str:
    return json.dumps(resultado, ensure_ascii=False)


def test_lojista_ve_lupe_mas_continua_sem_faturamento(client):
    token = _token(client, RAFAEL)
    lupe = chamar(client, token, "consultar_fidelidade")
    assert lupe["isError"] is False
    faturamento = chamar(client, token, "consultar_faturamento")
    assert faturamento["isError"] is True and "SEM_PERMISSAO" in faturamento["content"][0]["text"]
    assert "Lupe+" not in faturamento["content"][0]["text"]  # o rótulo do financeiro não fala mais do Lupe+


def test_lojista_ve_so_os_pedidos_da_propria_loja_sem_dados_do_cliente(client, pedidos_em_duas_lojas):
    token = _token(client, RAFAEL)
    resultado = chamar(client, token, "consultar_pedidos", {"status": "PROCESSANDO"})
    assert resultado["isError"] is False
    numeros = [p["numero"] for p in resultado["structuredContent"]["pedidos"]]
    assert "CL-TESTE-1" in numeros and "CL-TESTE-2" not in numeros
    lojas = {p["loja"] for p in resultado["structuredContent"]["pedidos"]}
    assert len(lojas) == 1
    texto = _texto(resultado)
    for nome in pedidos_em_duas_lojas:
        assert nome not in texto  # nome do cliente nunca sai

    # Pedir outra loja de propósito: recusado
    outra = chamar(client, token, "consultar_pedidos", {"loja_id": 2})
    assert outra["isError"] is True and "só os pedidos da sua loja" in outra["content"][0]["text"]


def test_administrador_ve_os_pedidos_da_rede(client, pedidos_em_duas_lojas):
    resultado = chamar(client, _token(client, HELENA), "consultar_pedidos", {"status": "PROCESSANDO", "limite": 30})
    numeros = [p["numero"] for p in resultado["structuredContent"]["pedidos"]]
    assert {"CL-TESTE-1", "CL-TESTE-2"} <= set(numeros)  # os mais recentes primeiro: as duas lojas aparecem


def test_lojista_ve_atendimentos_da_marca_sem_dados_do_cliente(client):
    token = _token(client, RAFAEL)
    resultado = chamar(client, token, "consultar_atendimentos")
    assert resultado["isError"] is False
    dados = resultado["structuredContent"]
    assert dados["filtros"][0] == "Marca: Casa Lorenzi"
    texto = _texto(resultado)
    for chave in ("contato", "email", "telefone", "mensagens", "cliente"):
        assert f'"{chave}"' not in texto
    # Pedir a outra marca: recusado
    vulto = chamar(client, token, "consultar_atendimentos", {"marca": "VULTO"})
    assert vulto["isError"] is True and "SEM_PERMISSAO" in vulto["content"][0]["text"]


def test_operador_ve_pedidos_mas_nao_atendimento_nem_lupe(client, pedidos_em_duas_lojas):
    token = _token(client, DIEGO)
    pedidos = chamar(client, token, "consultar_pedidos", {"status": "PROCESSANDO"})
    assert pedidos["isError"] is False
    assert "CL-TESTE-2" not in [p["numero"] for p in pedidos["structuredContent"]["pedidos"]]
    for ferramenta in ("consultar_atendimentos", "consultar_fidelidade", "consultar_faturamento"):
        recusa = chamar(client, token, ferramenta)
        assert recusa["isError"] is True and "SEM_PERMISSAO: o perfil Operador" in recusa["content"][0]["text"]


def test_lojista_pergunta_no_painel_sem_modelo(client, pedidos_em_duas_lojas):
    """As regras (sem chave do modelo) levam as perguntas para as consultas novas."""
    rafael = _entrar(client, RAFAEL)
    conversa = abrir_copiloto(client, rafael)
    resposta = pergunte(client, conversa, rafael, "Quais pedidos estão em separação?")
    assert "Em separação agora" in resposta["texto"]
    resposta = pergunte(client, conversa, rafael, "Quais atendimentos estão em aberto?")
    assert "atendimentos em aberto" in resposta["texto"]
    resposta = pergunte(client, conversa, rafael, "Quantos clientes temos em cada categoria do Lupe+?")
    assert "não tem acesso" not in resposta["texto"]
    resposta = pergunte(client, conversa, rafael, "Quanto faturamos em setembro?")
    assert "não tem acesso" in resposta["texto"]


def test_sugestoes_do_lojista(client):
    rafael = _entrar(client, RAFAEL)
    corpo = client.get("/api/copiloto/sugestoes", headers=rafael).json()
    assert corpo["permissoes"]["fidelidade"] and corpo["permissoes"]["pedidos"] and corpo["permissoes"]["atendimento"]
    assert not corpo["permissoes"]["vendas"]
    assert "Quais pedidos estão em separação?" in corpo["sugestoes"]
    assert "Quanto faturamos em setembro?" not in corpo["sugestoes"]
