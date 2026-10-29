"""Decisão 124: dado de um cliente não vai para a IA. O Assistente IA do painel e o Claude (MCP) não consultam os
pontos de um cliente específico; a equipe consulta em Atendimento > Lupe+. Os números do programa continuam."""

from datetime import timedelta

from src.database.connection import SessionLocal
from src.integrations import ia
from src.use_cases import fidelidade
from src.use_cases.assistente import ferramentas_gerenciais, prompts, regras_gerenciais, servidor_mcp
from src.utils.datas import agora
from tests.conftest import _entrar
from tests.ia_falsa import ProvedorFalso, texto
from tests.test_mcp import criar_token, legado
from tests.util_assistente import abrir_copiloto, pergunte

MARIANA = 101
RAFAEL = "rafael.monteiro@casalorenzi.com.br"  # Lojista


def _pontos(quantidade: int, ganhos_ha_dias: int) -> None:
    with SessionLocal() as db:
        fidelidade.travar(db, MARIANA)
        fidelidade.lancar(db, MARIANA, "CREDITO", quantidade, agora() - timedelta(days=ganhos_ha_dias), obs="teste")
        db.commit()


def test_nenhuma_ferramenta_consulta_um_cliente():
    nomes = {f.nome for f in ferramentas_gerenciais.FERRAMENTAS}
    assert "consultar_pontos_cliente" not in nomes
    assert {f.nome for f in servidor_mcp.FERRAMENTAS} == {"ver_contexto"} | nomes
    assert "consultar_pontos_cliente" not in prompts.PROMPT_GERENCIAL


def test_pergunta_de_um_cliente_no_painel_sem_modelo_leva_ao_lupe_do_atendimento(client):
    _pontos(800, 355)
    rafael = _entrar(client, RAFAEL)
    conversa = abrir_copiloto(client, rafael)
    resposta = pergunte(client, conversa, rafael, "Me fale quantos pontos no Lupe+ a cliente Mariana Costa possui?")
    assert resposta["texto"] == regras_gerenciais.DADO_DE_CLIENTE and "800" not in resposta["texto"]
    # Pergunta do programa (sem cliente citado) continua nos números agregados
    resposta = pergunte(client, conversa, rafael, "Quantos pontos vencem nos próximos 30 dias?")
    assert "Mariana" not in resposta["texto"] and resposta["texto"] != regras_gerenciais.DADO_DE_CLIENTE


def test_o_modelo_nao_recebe_a_consulta_de_um_cliente(client, admin):
    falso = ProvedorFalso(texto("Os pontos de um cliente ficam em Atendimento > Lupe+."))
    ia.definir_provedor(falso)
    conversa = abrir_copiloto(client, admin)
    pergunte(client, conversa, admin, "Quantos pontos a cliente Mariana Costa tem?")
    assert "consultar_pontos_cliente" not in str(falso.pedidos[0])


def test_pelo_claude_nao_ha_dados_de_cliente(client):
    _pontos(800, 355)
    token = criar_token(client, _entrar(client, "helena@casalorenzi.com.br"))
    nomes = [f["name"] for f in legado(client, token, "tools/list").json()["result"]["tools"]]
    assert "consultar_pontos_cliente" not in nomes
    resultado = legado(client, token, "tools/call", {"name": "consultar_pontos_cliente", "arguments": {"busca": "Mariana Costa"}})
    assert "Mariana Costa" not in resultado.text
