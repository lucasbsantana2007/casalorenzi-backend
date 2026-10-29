"""Decisões 119 e 120: pontos Lupe+ de um cliente no Assistente IA do painel, para quem já vê a ficha do cliente
(Administrador e Lojista). Só o necessário, sem CPF, telefone ou e-mail completo, e só lendo (não lança vencimento).
Pelo Claude (MCP), não: lá só há números agregados."""

import json
from datetime import timedelta

from src.database.connection import SessionLocal
from src.entities import assistente as regra
from src.use_cases import fidelidade
from src.use_cases.assistente import ferramentas_gerenciais
from src.use_cases.assistente.ferramentas import Contexto, executar, registro_de
from src.utils.datas import agora
from tests.conftest import _entrar
from tests.test_mcp import criar_token, legado
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


PERFIS = {RAFAEL: (2, "LOJISTA", "LORENZI"), DIEGO: (6, "OPERADOR", "LORENZI")}
REGISTRO = registro_de(ferramentas_gerenciais.FERRAMENTAS)


def chamar_no_painel(email: str, argumentos: dict) -> dict:
    """A consulta como o copiloto do painel a roda (mesma validação e permissão), no formato do MCP para os testes."""
    usuario_id, papel, marca = PERFIS[email]
    ctx = Contexto(
        tipo=regra.GERENCIAL, conversa_id="teste", origem="REGRAS", usuario_id=usuario_id, papel=papel, marca_escopo=marca
    )
    execucao = executar(REGISTRO, "consultar_pontos_cliente", argumentos, ctx)
    if not execucao.sucesso:
        return {"isError": True, "content": [{"type": "text", "text": execucao.erro}]}
    return {"isError": False, "structuredContent": execucao.resultado.dados}


def test_lojista_ve_o_saldo_de_um_cliente_sem_dados_sensiveis(client):
    _pontos(800, 355)  # vence em uns 10 dias
    _pontos(300, 400)  # já venceu: fica de fora do saldo
    movimentos_antes = sql("SELECT count(*) FROM movimentos_pontos WHERE cliente_id = :c", c=MARIANA)

    resultado = chamar_no_painel(RAFAEL, {"busca": "Mariana Costa"})
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
    for busca in ("158.813.998-03", "mariana.costa@gmail.com"):
        dados = chamar_no_painel(RAFAEL, {"busca": busca})["structuredContent"]
        assert dados["cliente"] == "Mariana Costa" and dados["saldo"] == "500"


def test_varios_parecidos_pedem_para_escolher_sem_mostrar_pontos(client):
    _pontos(500, 10)
    resultado = chamar_no_painel(RAFAEL, {"busca": "gmail"})
    dados = resultado["structuredContent"]
    assert dados["encontrados"] > 1 and "saldo" not in dados
    assert all("***@" in c["email"] or c["email"] == "sem e-mail" for c in dados["candidatos"])


def test_cliente_que_nao_existe(client):
    resultado = chamar_no_painel(RAFAEL, {"busca": "Fulano Inexistente"})
    assert resultado["isError"] is False and resultado["structuredContent"]["encontrados"] == 0


def test_operador_nao_ve_cliente(client):
    recusa = chamar_no_painel(DIEGO, {"busca": "Mariana Costa"})
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


def test_pelo_claude_nao_ha_dados_de_cliente(client):
    """Decisão 120: o MCP não lista nem roda a consulta de um cliente, nem para o Administrador do grupo."""
    _pontos(800, 355)
    token = criar_token(client, _entrar(client, "helena@casalorenzi.com.br"))
    nomes = [f["name"] for f in legado(client, token, "tools/list").json()["result"]["tools"]]
    assert "consultar_pontos_cliente" not in nomes
    resultado = legado(client, token, "tools/call", {"name": "consultar_pontos_cliente", "arguments": {"busca": "Mariana Costa"}})
    assert "Mariana Costa" not in resultado.text
