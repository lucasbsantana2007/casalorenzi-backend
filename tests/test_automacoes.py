"""Automações e alertas: criam, atualizam sem duplicar e resolvem sozinhas; uma execução por vez; descartado
não volta logo; cada perfil vê só os alertas do que pode acessar; retenção das conversas."""

from datetime import timedelta

from sqlalchemy import text

from src.database.connection import SessionLocal
from src.use_cases import automacoes, fidelidade
from src.utils.datas import agora
from tests.util_assistente import abrir_site, diga, entrar, sql

# Camisa de Linho Toscana, Branco, M na Oscar Freire (loja 1): vende no seed
ITEM = "SELECT e.id FROM estoques e JOIN variacoes v ON v.id = e.variacao_id WHERE e.loja_id = 1 AND v.sku = 'CL-CML-BRA-M'"


def _alertas(tipo: str, status: str = "ABERTO") -> list:
    return sql("SELECT chave, titulo FROM alertas WHERE tipo = :t AND status = :s", t=tipo, s=status)


def test_estoque_baixo_cria_atualiza_e_resolve(client):
    sql(f"UPDATE estoques SET quantidade = 0 WHERE id = ({ITEM})")
    primeira = automacoes.executar("estoque_baixo")
    assert primeira.status == "SUCESSO" and primeira.criados > 0
    chaves = {chave for chave, _ in _alertas("ESTOQUE_BAIXO")}
    item = sql(ITEM)[0][0]
    variacao = sql("SELECT variacao_id FROM estoques WHERE id = :i", i=item)[0][0]
    assert f"ESTOQUE_BAIXO:1:{variacao}" in chaves

    # De novo: atualiza, não duplica
    segunda = automacoes.executar("estoque_baixo", forcar=True)
    assert (segunda.criados, segunda.atualizados) == (0, primeira.criados)
    assert len(_alertas("ESTOQUE_BAIXO")) == primeira.criados

    # A loja repôs: o alerta é resolvido sozinho
    sql("UPDATE estoques SET quantidade = 50 WHERE id = :i", i=item)
    terceira = automacoes.executar("estoque_baixo", forcar=True)
    assert terceira.resolvidos >= 1
    assert f"ESTOQUE_BAIXO:1:{variacao}" in {chave for chave, _ in _alertas("ESTOQUE_BAIXO", "RESOLVIDO")}


def test_intervalo_minimo_entre_execucoes(client):
    assert automacoes.executar("estoque_parado").status == "SUCESSO"
    assert automacoes.executar("estoque_parado").status == "IGNORADA"


def test_execucao_simultanea_e_ignorada(client):
    with SessionLocal() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext('automacao:estoque_baixo'))"))
        execucao = automacoes.executar("estoque_baixo")
        db.rollback()
    assert execucao.status == "IGNORADA"
    assert "andamento" in execucao.detalhe


def test_descartado_nao_volta_na_proxima_execucao(client):
    sql(f"UPDATE estoques SET quantidade = 0 WHERE id = ({ITEM})")
    automacoes.executar("estoque_baixo")
    admin = entrar(client, "helena@casalorenzi.com.br")
    alerta = client.get("/api/alertas", params={"tipo": "ESTOQUE_BAIXO"}, headers=admin).json()["alertas"][0]
    assert client.patch(f"/api/alertas/{alerta['id']}", json={"status": "DESCARTADO"}, headers=admin).status_code == 200
    automacoes.executar("estoque_baixo", forcar=True)
    assert alerta["titulo"] not in {titulo for _, titulo in _alertas("ESTOQUE_BAIXO")}


def test_sugestao_de_transferencia_nao_transfere_nada(client):
    transferencias = sql("SELECT count(*) FROM transferencias")[0][0]
    sql(f"UPDATE estoques SET quantidade = 0 WHERE id = ({ITEM})")
    automacoes.executar("sugestoes_transferencia")
    assert sql("SELECT count(*) FROM transferencias")[0][0] == transferencias
    for _, titulo in _alertas("SUGESTAO_TRANSFERENCIA"):
        assert titulo.startswith("Sugestão:")


def test_pontos_a_vencer_sem_dado_pessoal_e_sem_envio(client):
    with SessionLocal() as db:
        fidelidade.travar(db, 101)
        fidelidade.lancar(db, 101, "CREDITO", 800, agora() - timedelta(days=355), obs="teste")
        db.commit()
    automacoes.executar("pontos_a_vencer")
    [(chave, titulo)] = _alertas("PONTOS_A_VENCER")
    descricao = sql("SELECT descricao FROM alertas WHERE chave = :c", c=chave)[0][0]
    assert titulo.startswith("1 clientes têm 800 pontos")
    assert "aviso por e-mail aos clientes está desligado" in descricao and "Mariana" not in titulo + descricao


def test_limpeza_apaga_conversas_vencidas(client):
    conversa, chave = abrir_site(client)
    diga(client, conversa, chave, "camisa azul")
    sql("UPDATE conversas_assistente SET expira_em = now() - interval '1 day' WHERE id = :c", c=conversa)
    execucao = automacoes.executar("limpeza_conversas")
    assert execucao.status == "SUCESSO" and execucao.detalhe.startswith("1 conversa")
    assert sql("SELECT count(*) FROM mensagens_assistente WHERE conversa_id = :c", c=conversa)[0][0] == 0


def test_cada_perfil_ve_os_alertas_que_pode(client):
    sql(f"UPDATE estoques SET quantidade = 0 WHERE id = ({ITEM})")
    with SessionLocal() as db:
        fidelidade.travar(db, 101)
        fidelidade.lancar(db, 101, "CREDITO", 800, agora() - timedelta(days=355), obs="teste")
        db.commit()
    automacoes.executar_todas()
    tipos = {
        email: set(client.get("/api/alertas", headers=entrar(client, email)).json()["abertosPorTipo"])
        for email in ("helena@casalorenzi.com.br", "diego.almeida@casalorenzi.com.br", "rafael.monteiro@casalorenzi.com.br")
    }
    assert tipos["helena@casalorenzi.com.br"] == {"ESTOQUE_BAIXO", "ESTOQUE_PARADO", "SUGESTAO_TRANSFERENCIA", "PONTOS_A_VENCER"}
    assert tipos["diego.almeida@casalorenzi.com.br"] == {"ESTOQUE_BAIXO", "ESTOQUE_PARADO", "SUGESTAO_TRANSFERENCIA"}  # Operador
    # Lojista: estoque e, desde a decisão 118, os pontos a vencer (Lupe+); transferência não
    assert tipos["rafael.monteiro@casalorenzi.com.br"] == {"ESTOQUE_BAIXO", "ESTOQUE_PARADO", "PONTOS_A_VENCER"}
    # Equipe da Vulto não vê os alertas da Casa Lorenzi
    paula = entrar(client, "paula.ferraz@vulto.com.br")
    assert all(a["marca"] in (None, "VULTO") for a in client.get("/api/alertas", headers=paula).json()["alertas"])
    # Cliente não acessa
    assert client.get("/api/alertas", headers=entrar(client, "mariana.costa@gmail.com")).status_code == 401


def test_rodar_automacao_pelo_painel_so_administrador(client):
    diego = entrar(client, "diego.almeida@casalorenzi.com.br")
    assert client.post("/api/automacoes/estoque_baixo/executar", headers=diego).status_code == 403
    admin = entrar(client, "helena@casalorenzi.com.br")
    resposta = client.post("/api/automacoes/estoque_baixo/executar", headers=admin)
    assert resposta.status_code == 200 and resposta.json()[0]["status"] == "SUCESSO"
    log = client.get("/api/automacoes/execucoes", headers=admin).json()
    assert log[0]["automacao"] == "estoque_baixo" and log[0]["disparadaPor"] == 1
