"""Copiloto gerencial: os números batem com as regras oficiais, cada perfil só vê o que pode (papel e
marca), as consultas são só leitura e o modelo não contorna nada disso."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError

from src.database.connection import SessionLeitura, SessionLocal
from src.integrations import ia
from src.use_cases import fidelidade
from src.use_cases.assistente import ferramentas_gerenciais
from src.utils.datas import agora, hoje
from tests.ia_falsa import ProvedorFalso, ferramenta, texto
from tests.util_assistente import abrir_copiloto, blocos, entrar, indicador, pergunte, sql


@pytest.fixture
def helena(client):
    return entrar(client, "helena@casalorenzi.com.br")  # Administradora do grupo


def test_faturamento_igual_ao_do_financeiro(client, helena):
    conversa = abrir_copiloto(client, helena)
    resposta = pergunte(client, conversa, helena, "Quanto faturamos nos últimos 30 dias?")
    oficial = client.get(
        "/api/financeiro/resumo", params={"comparar": "nenhum"}, headers=helena
    ).json()  # padrão: últimos 30 dias
    assert indicador(resposta, "Faturamento") == pytest.approx(round(oficial["receitaLiquida"], 2))
    assert indicador(resposta, "Receita de vendas") == pytest.approx(round(oficial["receita"], 2))
    assert indicador(resposta, "Pedidos") == oficial["pedidos"]
    assert indicador(resposta, "Pedidos cancelados") == oficial["cancelados"]
    fonte = blocos(resposta, "fonte")[0]
    assert "regra da diretoria" in fonte["definicao"] and fonte["periodo"]


def test_faturamento_por_loja_e_por_marca_fecha_com_o_total(client, helena):
    conversa = abrir_copiloto(client, helena)
    por_loja = pergunte(client, conversa, helena, "Qual loja apresentou maior faturamento nos últimos 30 dias?")
    total = indicador(por_loja, "Faturamento")
    linhas = blocos(por_loja, "tabela")[0]["linhas"]
    assert sum(linha["faturamento"] for linha in linhas) == pytest.approx(total)
    assert linhas == sorted(linhas, key=lambda linha: -linha["faturamento"])
    por_marca = pergunte(client, conversa, helena, "Qual marca vendeu mais nos últimos 30 dias?")
    assert sum(linha["faturamento"] for linha in blocos(por_marca, "tabela")[0]["linhas"]) == pytest.approx(total)


def test_mais_vendidos_confere_com_os_pedidos(client, helena):
    conversa = abrir_copiloto(client, helena)
    resposta = pergunte(client, conversa, helena, "Quais foram os produtos mais vendidos nos últimos 30 dias?")
    primeira = blocos(resposta, "tabela")[0]["linhas"][0]
    esperado = sql(
        """SELECT p.nome, SUM(i.quantidade) FROM itens_pedido i JOIN pedidos pe ON pe.id = i.pedido_id
           JOIN variacoes v ON v.id = i.variacao_id JOIN produtos p ON p.id = v.produto_id
           WHERE pe.criado_em >= :inicio AND pe.status <> 'CANCELADO' AND pe.tipo = 'VENDA'
           GROUP BY p.nome ORDER BY 2 DESC, p.nome LIMIT 1""",
        inicio=(hoje() - timedelta(days=29)).isoformat() + " 00:00-03",
    )[0]
    assert (primeira["produto"], primeira["pecas"]) == (esperado[0], esperado[1])


def test_cancelamentos_conferem(client, helena):
    conversa = abrir_copiloto(client, helena)
    resposta = pergunte(client, conversa, helena, "Quantas vendas foram canceladas nos últimos 90 dias?")
    esperado = sql(
        "SELECT count(*) FROM pedidos WHERE status = 'CANCELADO' AND tipo = 'VENDA' AND criado_em >= :inicio",
        inicio=(hoje() - timedelta(days=89)).isoformat() + " 00:00-03",
    )[0][0]
    assert indicador(resposta, "Pedidos cancelados") == esperado


def test_periodo_sem_vendas_diz_ate_quando_vao_os_dados(client, helena):
    conversa = abrir_copiloto(client, helena)
    resposta = pergunte(client, conversa, helena, "Quanto faturamos em janeiro de 2025?")
    assert indicador(resposta, "Faturamento") == 0
    assert "Os dados de vendas vão até" in resposta["texto"]


def test_estoque_baixo_confere_com_o_status_oficial(client, helena):
    conversa = abrir_copiloto(client, helena)
    falso = ProvedorFalso(
        ferramenta("consultar_estoque_baixo", {"somente_com_demanda": False, "limite": 30}), texto("Lista abaixo.")
    )
    ia.definir_provedor(falso)
    resposta = pergunte(client, conversa, helena, "estoque baixo, mesmo sem venda")
    esperado = sql(
        """SELECT count(*) FROM estoques e JOIN variacoes v ON v.id = e.variacao_id JOIN produtos p ON p.id = v.produto_id
           JOIN lojas l ON l.id = e.loja_id
           WHERE e.quantidade <= e.quantidade_min AND p.ativo AND p.removido_em IS NULL AND l.ativa
             AND v.status IN ('ATIVO', 'DESCONTINUADO', 'FORA_DO_CATALOGO')"""
    )[0][0]
    assert indicador(resposta, "Itens no mínimo ou zerados") == esperado


def test_estoque_parado_tem_a_definicao_e_a_ultima_venda(client, helena):
    conversa = abrir_copiloto(client, helena)
    resposta = pergunte(client, conversa, helena, "Quais produtos estão parados há mais de 7 dias?")
    assert "sem saída por venda" in blocos(resposta, "fonte")[0]["definicao"]
    for linha in blocos(resposta, "tabela")[-1]["linhas"]:
        assert linha["diasSemVenda"] >= 7


def test_operador_nao_ve_dados_financeiros(client):
    diego = entrar(client, "diego.almeida@casalorenzi.com.br")  # Operador
    conversa = abrir_copiloto(client, diego)
    resposta = pergunte(client, conversa, diego, "Quanto faturamos nos últimos 30 dias?")
    assert "não tem acesso" in resposta["texto"]
    assert blocos(resposta, "indicadores") == []
    assert sql("SELECT sucesso FROM chamadas_ferramenta WHERE conversa_id = :c", c=conversa) == [(False,)]
    # Estoque ele pode
    assert indicador(pergunte(client, conversa, diego, "Quais produtos estão com estoque baixo?"), "Zerados") >= 0


def test_modelo_nem_recebe_as_ferramentas_proibidas(client):
    diego = entrar(client, "diego.almeida@casalorenzi.com.br")
    falso = ProvedorFalso(ferramenta("consultar_faturamento", {"periodo": "mes_atual"}), texto("Não tenho acesso a isso."))
    ia.definir_provedor(falso)
    conversa = abrir_copiloto(client, diego)
    resposta = pergunte(client, conversa, diego, "quanto faturamos?")
    assert "consultar_faturamento" not in falso.nomes_oferecidos()
    assert falso.resultados_de_ferramenta()[0]["content"].startswith("FERRAMENTA_INEXISTENTE")
    assert blocos(resposta, "indicadores") == []


def test_lojista_nao_ve_transferencias(client):
    rafael = entrar(client, "rafael.monteiro@casalorenzi.com.br")  # Lojista
    conversa = abrir_copiloto(client, rafael)
    resposta = pergunte(client, conversa, rafael, "Que transferências você sugere?")
    assert "não tem acesso a transferências" in resposta["texto"]


def test_equipe_de_uma_marca_nao_ve_a_outra(client):
    paula = entrar(client, "paula.ferraz@vulto.com.br")  # Administradora só da Vulto
    conversa = abrir_copiloto(client, paula)
    resposta = pergunte(client, conversa, paula, "Quanto faturamos nos últimos 30 dias na Casa Lorenzi?")
    assert "só da Vulto" in resposta["texto"]
    # Sem dizer a marca: só a Vulto (o seed não tem lojas da Vulto, então nada)
    resposta = pergunte(client, conversa, paula, "Quanto faturamos nos últimos 30 dias?")
    assert indicador(resposta, "Faturamento") == 0
    assert "Marca: Vulto" in blocos(resposta, "fonte")[0]["filtros"]


def test_administrador_de_uma_marca_ve_so_a_dele(client, helena):
    otavio = entrar(client, "otavio.vasconcelos@casalorenzi.com.br")  # Administrador só da Casa Lorenzi
    conversa = abrir_copiloto(client, otavio)
    dele = indicador(pergunte(client, conversa, otavio, "Quanto faturamos nos últimos 30 dias?"), "Faturamento")
    conversa_helena = abrir_copiloto(client, helena)
    do_grupo = indicador(pergunte(client, conversa_helena, helena, "Quanto faturamos nos últimos 30 dias?"), "Faturamento")
    assert dele == do_grupo  # o seed só tem a Casa Lorenzi


def test_cliente_e_anonimo_nao_usam_o_copiloto(client):
    mariana = entrar(client, "mariana.costa@gmail.com")
    assert client.post("/api/copiloto/conversas", headers=mariana).status_code == 401
    assert client.post("/api/copiloto/conversas").status_code == 401


def test_conversa_do_copiloto_e_so_de_quem_abriu(client, helena):
    conversa = abrir_copiloto(client, helena)
    pergunte(client, conversa, helena, "estoque baixo")
    otavio = entrar(client, "otavio.vasconcelos@casalorenzi.com.br")
    assert client.get(f"/api/copiloto/conversas/{conversa}", headers=otavio).status_code == 404
    assert [c["id"] for c in client.get("/api/copiloto/conversas", headers=helena).json()] == [conversa]


def test_consultas_do_copiloto_sao_somente_leitura(client, helena, monkeypatch):
    with SessionLeitura() as db, pytest.raises(InternalError):
        db.execute(text("UPDATE estoques SET quantidade = quantidade + 1"))

    def tenta_gravar(db, ctx, entrada):
        db.execute(text("UPDATE estoques SET quantidade = 999"))
        return None

    original = next(f for f in ferramentas_gerenciais.FERRAMENTAS if f.nome == "consultar_estoque_por_loja")
    trocada = type(original)(original.nome, original.descricao, original.entrada, tenta_gravar, original.modulo)
    monkeypatch.setattr(
        ferramentas_gerenciais, "FERRAMENTAS", [trocada if f is original else f for f in ferramentas_gerenciais.FERRAMENTAS]
    )
    from src.use_cases.assistente import conversas

    monkeypatch.setattr(conversas.ASSISTENTE_GERENCIAL, "ferramentas", ferramentas_gerenciais.FERRAMENTAS)
    conversa = abrir_copiloto(client, helena)
    resposta = pergunte(client, conversa, helena, "Quais lojas concentram mais estoque?")
    assert "Não consegui consultar" in resposta["texto"]
    assert sql("SELECT count(*) FROM estoques WHERE quantidade = 999")[0][0] == 0


def test_modelo_monta_a_resposta_mas_os_numeros_vem_da_ferramenta(client, helena):
    falso = ProvedorFalso(
        ferramenta("consultar_faturamento", {"periodo": "ultimos_30_dias", "agrupar_por": "loja"}),
        texto("A Oscar Freire liderou o faturamento."),
    )
    ia.definir_provedor(falso)
    conversa = abrir_copiloto(client, helena)
    resposta = pergunte(client, conversa, helena, "qual loja faturou mais no último mês?")
    assert resposta["modo"] == "LLM"
    assert {b["tipo"] for b in resposta["blocos"]} >= {"indicadores", "tabela", "grafico", "fonte"}
    dados = json.loads(falso.resultados_de_ferramenta()[0]["content"])
    assert dados["faturamento"].startswith("R$ ")  # o modelo recebe o valor pronto, não precisa calcular
    assert "Vendas registradas até" in falso.pedidos[0]["sistema"][1]["text"]


def test_vulto_mais_agregado_sem_dado_pessoal(client, helena):
    with SessionLocal() as db:
        for cliente_id, pontos in ((101, 500), (102, 700)):
            fidelidade.travar(db, cliente_id)
            fidelidade.lancar(db, cliente_id, "CREDITO", pontos, agora() - timedelta(days=355), obs="teste")
        db.commit()
    conversa = abrir_copiloto(client, helena)
    resposta = pergunte(client, conversa, helena, "Quantos clientes possuem pontos vencendo nos próximos 30 dias?")
    assert indicador(resposta, "Vencendo em 30 dias") == 1200
    assert indicador(resposta, "Clientes com pontos vencendo") == 2
    corpo = json.dumps(resposta)
    assert "Mariana" not in corpo and "15881399803" not in corpo


def test_uso_da_ia_so_para_o_administrador(client, helena):
    assert client.get("/api/copiloto/uso", headers=helena).json()["modoIA"] == "REGRAS"
    diego = entrar(client, "diego.almeida@casalorenzi.com.br")
    assert client.get("/api/copiloto/uso", headers=diego).status_code == 403


def test_sugestoes_respeitam_o_perfil(client, helena):
    diego = entrar(client, "diego.almeida@casalorenzi.com.br")
    do_operador = client.get("/api/copiloto/sugestoes", headers=diego).json()
    assert not any("fatur" in s for s in do_operador["sugestoes"])
    assert do_operador["permissoes"]["vendas"] is False
    assert any("fatur" in s for s in client.get("/api/copiloto/sugestoes", headers=helena).json()["sugestoes"])


def test_comparar_as_marcas_so_aparece_para_quem_ve_as_duas(client, helena):
    # Decisão 123: o administrador de uma marca (Otávio, Casa Lorenzi) não vê a outra
    otavio = entrar(client, "otavio.vasconcelos@casalorenzi.com.br")
    pergunta = "Qual marca vendeu mais no mês passado?"
    assert pergunta in client.get("/api/copiloto/sugestoes", headers=helena).json()["sugestoes"]
    assert pergunta not in client.get("/api/copiloto/sugestoes", headers=otavio).json()["sugestoes"]
    boas_vindas = client.post("/api/copiloto/conversas", headers=otavio).json()["mensagens"][0]["blocos"][0]["itens"]
    assert pergunta not in boas_vindas and "Quanto faturamos em setembro?" in boas_vindas


def test_agradecimento_so_tem_resposta_pronta_sem_pergunta(client, admin):
    conversa = abrir_copiloto(client, admin)
    assert pergunte(client, conversa, admin, "perfeito, obrigado")["texto"].startswith("Por nada!")
    # Com pergunta junto, responde a pergunta (antes ficava só o "Por nada!")
    resposta = pergunte(client, conversa, admin, "valeu, quanto faturamos em setembro?")
    assert "Por nada" not in resposta["texto"]
