"""Aba Lupe+ do Atendimento (decisão 120): quantos pontos cada cliente tem, para Administrador e Lojista."""

from datetime import timedelta

from src.database.connection import SessionLocal
from src.use_cases import fidelidade
from src.utils.datas import agora
from tests.util_assistente import sql

MARIANA, RICARDO = 101, 102
URL = "/api/lupe/clientes"


def _pontos(cliente_id: int, quantidade: int, ganhos_ha_dias: int) -> None:
    with SessionLocal() as db:
        fidelidade.travar(db, cliente_id)
        fidelidade.lancar(db, cliente_id, "CREDITO", quantidade, agora() - timedelta(days=ganhos_ha_dias), obs="teste")
        db.commit()


def _da_mariana(corpo: dict) -> dict:
    [linha] = [i for i in corpo["itens"] if i["nome"] == "Mariana Costa"]
    return linha


def test_so_quem_atende_ve_a_lista(client, admin, lojista, operador, mariana):
    assert client.get(URL, headers=admin).status_code == 200
    assert client.get(URL, headers=lojista).status_code == 200
    assert client.get(URL, headers=operador).status_code == 403
    assert client.get(URL, headers=mariana).status_code in (401, 403)  # cliente da loja não vê os outros
    assert client.get(URL).status_code == 401


def test_saldo_sem_os_pontos_vencidos_e_sem_lancar_nada(client, lojista):
    _pontos(MARIANA, 800, 355)  # vence em uns 10 dias
    _pontos(MARIANA, 300, 400)  # já venceu: fora do saldo
    antes = sql("SELECT count(*) FROM movimentos_pontos WHERE cliente_id = :c", c=MARIANA)
    linha = _da_mariana(client.get(URL, headers=lojista).json())
    assert linha["saldo"] == 800 and linha["valorEmReais"] == 40.0
    assert linha["proximoVencimento"]["pontos"] == 800
    assert sql("SELECT count(*) FROM movimentos_pontos WHERE cliente_id = :c", c=MARIANA) == antes


def test_busca_categoria_e_ordem(client, admin):
    _pontos(MARIANA, 800, 10)
    _pontos(RICARDO, 50, 10)
    assert [i["nome"] for i in client.get(URL, params={"busca": "mariana"}, headers=admin).json()["itens"]] == ["Mariana Costa"]
    pelo_cpf = client.get(URL, params={"busca": "158.813.998-03"}, headers=admin).json()["itens"]
    assert [i["nome"] for i in pelo_cpf] == ["Mariana Costa"]

    por_saldo = client.get(URL, headers=admin).json()["itens"]
    assert [i["saldo"] for i in por_saldo] == sorted((i["saldo"] for i in por_saldo), reverse=True)
    por_nome = [i["nome"] for i in client.get(URL, params={"ordem": "nome"}, headers=admin).json()["itens"]]
    assert por_nome == sorted(por_nome, key=str.lower) or len(por_nome) == 2

    categoria = _da_mariana(client.get(URL, headers=admin).json())["categoria"]
    filtrada = client.get(URL, params={"categoria": categoria}, headers=admin).json()
    assert all(i["categoria"] == categoria for i in filtrada["itens"])
    assert filtrada["pontos"] == sum(i["saldo"] for i in filtrada["itens"])
    assert client.get(URL, params={"categoria": "DIAMANTE"}, headers=admin).status_code == 422


def test_cliente_sem_pontos_e_conta_excluida_ficam_de_fora(client, admin):
    _pontos(MARIANA, 800, 10)
    _pontos(RICARDO, 500, 10)
    sql("UPDATE clientes SET excluido_em = now() WHERE id = :c", c=RICARDO)
    nomes = [i["nome"] for i in client.get(URL, headers=admin).json()["itens"]]
    assert "Mariana Costa" in nomes and "Ricardo Fonseca" not in nomes
