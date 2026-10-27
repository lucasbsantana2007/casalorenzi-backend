"""Entendimento das perguntas (busca, períodos), custo e a busca no catálogo real (seed)."""

from datetime import date
from decimal import Decimal

import pytest

from src.database.connection import SessionLeitura
from src.entities.assistente import custo_estimado
from src.entities.busca import interpretar_busca
from src.entities.periodo import resolver
from src.use_cases.assistente import catalogo
from src.use_cases.assistente.regras_gerenciais import extrair_periodo
from tests.util_assistente import sql


@pytest.mark.parametrize(
    ("frase", "tipos", "cor", "tamanho", "preco_max"),
    [
        ("Vocês têm camisa azul de botão?", ["camisa"], "azul", None, None),
        ("Tem calça preta tamanho 40?", ["calca"], "preto", "40", None),
        ("Quero uma camiseta branca até R$ 150.", ["camiseta"], "branco", None, Decimal("150")),
        ("camisa xadrez azul M", ["camisa"], "azul", "M", None),
        ("moletom cinza GG", ["moletom"], "cinza", "GG", None),
        ("calça de alfaiataria 44 feminina", ["calca"], None, "44", None),
    ],
)
def test_interpreta_as_perguntas_do_cliente(frase, tipos, cor, tamanho, preco_max):
    pedido = interpretar_busca(frase)
    assert pedido.tipos == tipos
    assert pedido.cor == cor
    assert pedido.tamanho == tamanho
    assert pedido.preco_max == preco_max


def test_faixa_de_preco_e_tamanhos_curtos():
    pedido = interpretar_busca("vestido entre 200 e 300 reais")
    assert (pedido.preco_min, pedido.preco_max) == (Decimal("200"), Decimal("300"))
    assert interpretar_busca("acima de R$ 1.000").preco_min == Decimal("1000")
    assert interpretar_busca("M").tamanho == "M"
    assert interpretar_busca("e no G?").tamanho == "G"
    # "e" e "o" não viram tamanho numa frase longa
    assert interpretar_busca("quero uma camisa e o que mais tiver de linho").tamanho is None


@pytest.mark.parametrize(
    ("frase", "tamanho"),
    [
        ("camiseta preta XS", "XP"),
        ("tem camisa azul tamanho S?", "P"),
        ("moletom cinza L", "G"),
        ("quero no XL", "GG"),
        ("e o xs?", "XP"),
        ("L", "G"),
    ],
)
def test_entende_a_grade_internacional(frase, tamanho):
    """Muitos clientes escrevem XS, S, L e XL: XS = XP, S = P, L = G, XL = GG."""
    assert interpretar_busca(frase).tamanho == tamanho


def test_lucia_responde_l_com_as_pecas_no_g(client):
    """Na conversa: o cliente pede a peça e responde só "L"; os cards vêm no G."""
    conversa = client.post("/api/assistente/conversas", json={}).json()
    cabecalho = {"X-Conversa-Chave": conversa["chave"]}
    url = f"/api/assistente/conversas/{conversa['id']}/mensagens"
    client.post(url, json={"texto": "Vocês têm camisa azul?"}, headers=cabecalho)
    resposta = client.post(url, json={"texto": "L"}, headers=cabecalho).json()["resposta"]
    [cards] = [b for b in resposta["blocos"] if b["tipo"] == "produtos"]
    assert cards["itens"] and all(item["tamanhos"] == ["G"] for item in cards["itens"])


def test_periodos_em_datas_do_fuso():
    hoje = date(2026, 10, 26)  # segunda-feira
    assert resolver("hoje", hoje).rotulo == "26/10/2026"
    assert resolver("semana_atual", hoje).inicio == date(2026, 10, 26)
    assert resolver("mes_passado", hoje).rotulo == "01/09/2026 a 30/09/2026"
    assert resolver("ultimos_7_dias", hoje).inicio == date(2026, 10, 20)
    assert extrair_periodo("quanto faturamos em setembro", hoje) == {
        "periodo": "personalizado",
        "de": "2026-09-01",
        "ate": "2026-09-30",
    }
    assert extrair_periodo("vendas de dezembro", hoje)["de"] == "2025-12-01"  # dezembro ainda não chegou: o do ano passado
    assert extrair_periodo("de 01/09 a 15/09", hoje) == {"periodo": "personalizado", "de": "2026-09-01", "ate": "2026-09-15"}
    assert extrair_periodo("ultimos 15 dias", hoje)["de"] == "2026-10-12"
    assert extrair_periodo("nesta semana", hoje) == {"periodo": "semana_atual"}


def test_custo_estimado_pela_tabela_de_precos():
    # Haiku 5.5: US$ 0,10 por milhão de tokens de entrada e US$ 0,50 de saída (prompt até 100 mil tokens)
    assert custo_estimado("claude-haiku-5-5", 100_000, 0) == Decimal("0.010000")
    assert custo_estimado("claude-haiku-5-5", 0, 1_000_000) == Decimal("0.500000")
    # Leitura de cache a 0,1x e escrita a 1,25x do preço de entrada
    assert custo_estimado("claude-haiku-5-5", 0, 0, cache_leitura=100_000) == Decimal("0.001000")
    assert custo_estimado("claude-haiku-5-5", 0, 0, cache_escrita=80_000) == Decimal("0.010000")
    # Prompt acima de 100 mil tokens: tabela de prompt longo (US$ 0,50 / US$ 2,50)
    assert custo_estimado("claude-haiku-5-5", 200_000, 0) == Decimal("0.100000")
    assert custo_estimado("modelo-desconhecido", 10, 10) is None


def _buscar(frase: str, **extra):
    with SessionLeitura() as db:
        resultado = catalogo.buscar(db, interpretar_busca(frase), **extra)
        return resultado, [a.produto.nome for a in resultado.achados]


def test_busca_por_cor_e_tamanho_no_catalogo_real():
    resultado, nomes = _buscar("camisa azul M")
    assert set(nomes) == {"Camisa de Linho Toscana", "Camisa de Linho Positano"}
    assert resultado.afrouxado == []


def test_busca_por_preco():
    _, nomes = _buscar("camisa até R$ 400")
    assert nomes == ["Camisa de Linho Positano"]  # a Toscana custa R$ 489,00


def test_peca_inexistente_nao_e_inventada():
    resultado, nomes = _buscar("quero um terno")
    assert nomes == []
    assert resultado.desconhecidos == ["terno"]


def test_cor_parecida_e_avisada():
    resultado, nomes = _buscar("calça preta")
    assert nomes == ["Calça de Linho Amalfi"]  # só tem Grafite e Marinho
    assert resultado.afrouxado == ["cor parecida"]


def test_produto_inativo_fica_fora():
    _, nomes = _buscar("bermuda")
    assert nomes == []  # Bermuda de Sarja Resort está inativa


def test_tamanho_esgotado_afrouxa_e_avisa():
    # A saia 40 (variação 39) não tem transferência a caminho: zerada, sai da vitrine
    sql("UPDATE estoques SET quantidade = 0 WHERE variacao_id = 39")
    resultado, nomes = _buscar("saia preta 40")
    assert nomes == ["Saia Plissada Midi"]
    assert resultado.afrouxado == ["outros tamanhos (sem o 40 disponível)"]
    assert resultado.esgotados == ["Saia Plissada Midi"]
    assert "40" not in catalogo.card(resultado.achados[0])["tamanhos"]


def test_peca_a_caminho_conta_como_disponivel():
    # Regra oficial da vitrine: o que está em trânsito para uma loja já pode ser vendido
    sql("UPDATE estoques SET quantidade = 0 WHERE variacao_id = 37")
    _, nomes = _buscar("saia preta 36")
    assert nomes == ["Saia Plissada Midi"]


def test_lojas_citadas_por_nome_cidade_e_shopping():
    with SessionLeitura() as db:
        assert [loja.nome for loja in catalogo.encontrar_lojas(db, "tem no Leblon?")] == ["Leblon"]
        assert [loja.nome for loja in catalogo.encontrar_lojas(db, "lojas em BH")] == ["Belvedere"]
        assert {loja.nome for loja in catalogo.encontrar_lojas(db, "na loja do shopping")} == {"Lago Norte", "Pátio Batel"}
        assert catalogo.encontrar_lojas(db, "camisa até R$ 150") == []
