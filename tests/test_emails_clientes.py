"""Aba Automações (decisão 127): os e-mails automáticos aos clientes no painel. Só o Administrador vê; cada envio
mostra se está ligado, o modo, a fila e os envios de hoje, com as mesmas regras do envio; o botão manda os e-mails e
eles aparecem na lista; os alertas da equipe continuam sendo criados para o Assistente IA. Nada sai de verdade: o
envio é trocado por uma lista."""

from datetime import timedelta

import pytest

from src.config import settings
from src.database.connection import SessionLocal
from src.use_cases import automacoes, avisos_cliente, avisos_pontos, fidelidade
from src.utils.datas import agora
from tests.util_assistente import abrir_copiloto, blocos, pergunte, sql

MARIANA, RICARDO = 101, 102
EMAIL_MARIANA = "mariana.costa@gmail.com"
TIME = "time@exemplo.com"
EMAILS = ["aviso_pontos", "lembrete_sacola", "aviso_estoque"]
CHAVES = ("AVISO_PONTOS_ENVIAR", "LEMBRETE_SACOLA_ENVIAR", "AVISO_ESTOQUE_ENVIAR")


@pytest.fixture
def desligados(monkeypatch):
    for chave in CHAVES:
        monkeypatch.setattr(settings, chave, False)
    monkeypatch.setattr(settings, "AVISO_PONTOS_TESTE_PARA", "")
    monkeypatch.setattr(settings, "AVISOS_TESTE_PARA", "")


@pytest.fixture
def caixa(monkeypatch):
    """Liga os três envios no modo teste e troca o Resend por uma lista (a conferência "na hora" roda sem thread)."""
    enviados = []
    for chave in CHAVES:
        monkeypatch.setattr(settings, chave, True)
    monkeypatch.setattr(settings, "AVISO_PONTOS_TESTE_PARA", TIME)
    monkeypatch.setattr(settings, "AVISOS_TESTE_PARA", TIME)
    for modulo in (avisos_pontos, avisos_cliente):
        monkeypatch.setattr(modulo, "PAUSA_ENTRE_ENVIOS", 0)
        monkeypatch.setattr(modulo, "_enviar_de_verdade", enviados.append)

    class Imediata:
        def submit(self, funcao, *args):
            funcao(*args)

    monkeypatch.setattr(avisos_cliente, "_fila", Imediata())
    return enviados


def _painel(client, admin) -> dict:
    resposta = client.get("/api/automacoes/emails", headers=admin)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _email(painel: dict, nome: str) -> dict:
    return next(e for e in painel["emails"] if e["nome"] == nome)


def _executar(client, admin) -> dict:
    """O botão do painel: roda todas as automações. Devolve as execuções pelo nome."""
    resposta = client.post("/api/automacoes/todas/executar", headers=admin)
    assert resposta.status_code == 200, resposta.text
    return {e["automacao"]: e for e in resposta.json()}


def _pontos_vencendo(cliente_id: int, quantidade: int = 800) -> None:
    """Pontos ganhos há 355 dias: vencem em uns 10 dias, dentro da janela do aviso."""
    with SessionLocal() as db:
        fidelidade.travar(db, cliente_id)
        fidelidade.lancar(db, cliente_id, "CREDITO", quantidade, agora() - timedelta(days=355), obs="teste")
        db.commit()


def _peca_disponivel(client) -> int:
    for produto in client.get("/api/produtos?ativo=true").json():
        for variacao in produto["variacoes"]:
            if variacao["disponivel"] >= 2:
                return variacao["id"]
    raise AssertionError("nenhuma peça disponível")


def test_so_o_administrador_ve_a_aba(client, admin, lojista, operador):
    assert client.get("/api/automacoes/emails", headers=lojista).status_code == 403
    assert client.get("/api/automacoes/emails", headers=operador).status_code == 403
    assert client.get("/api/automacoes/emails", headers=admin).status_code == 200


def test_desligados_por_padrao_o_botao_nao_manda_e_mail(client, admin, desligados):
    painel = _painel(client, admin)
    assert [e["nome"] for e in painel["emails"]] == EMAILS
    assert [e["chave"] for e in painel["emails"]] == list(CHAVES)
    for email in painel["emails"]:
        assert email["ligado"] is False and email["modo"] == "REAL" and email["enviadosHoje"] == 0
    assert painel["envios"] == []
    # As rotinas internas (alertas do Assistente IA, limpeza das conversas, WhatsApp) continuam na lista
    assert {r["nome"] for r in painel["rotinas"]} == set(automacoes.AUTOMACOES) - set(EMAILS)

    execucoes = _executar(client, admin)
    for nome in EMAILS:
        assert execucoes[nome]["criados"] == 0 and "desligado" in execucoes[nome]["detalhe"]
        assert execucoes[nome]["iniciadaEm"] <= execucoes[nome]["terminadaEm"]
    assert _painel(client, admin)["envios"] == []


def test_modo_teste_manda_para_o_time_e_mostra_na_lista(client, admin, caixa):
    _pontos_vencendo(MARIANA)
    antes = _email(_painel(client, admin), "aviso_pontos")
    assert antes["ligado"] and antes["modo"] == "TESTE" and antes["testePara"] == TIME
    assert antes["limiteDia"] == 5 and antes["enviadosHoje"] == 0 and antes["naFila"] >= 1

    pontos = _executar(client, admin)["aviso_pontos"]
    enviados = min(antes["naFila"], 5)
    assert pontos["status"] == "SUCESSO" and pontos["criados"] == enviados
    assert caixa and all(e.para == TIME and e.assunto.startswith("[Teste · para ") for e in caixa)
    assert sum("Lupe+" in e.assunto for e in caixa) == enviados

    depois = _painel(client, admin)
    situacao = _email(depois, "aviso_pontos")
    assert situacao["enviadosHoje"] == enviados and situacao["naFila"] == antes["naFila"] - enviados
    linhas = [linha for linha in depois["envios"] if linha["tipo"] == "aviso_pontos"]
    assert len(linhas) == enviados
    for linha in linhas:
        assert linha["modo"] == "TESTE" and linha["para"] == TIME and linha["cliente"]
        assert linha["enviadoEm"] >= pontos["iniciadaEm"]


def test_fila_da_sacola_segue_as_regras_do_envio(client, admin, mariana, caixa):
    variacao = _peca_disponivel(client)
    assert (
        client.put("/api/conta/sacola", headers=mariana, json={"itens": [{"variacaoId": variacao, "quantidade": 2}]}).status_code
        == 204
    )
    sql("UPDATE sacolas SET atualizada_em = :t", t=agora() - timedelta(hours=25))
    sql("UPDATE clientes SET aceita_marketing = false WHERE id = :c", c=MARIANA)
    assert _email(_painel(client, admin), "lembrete_sacola")["naFila"] == 0  # sem consentimento, não entra
    sql("UPDATE clientes SET aceita_marketing = true WHERE id = :c", c=MARIANA)
    assert _email(_painel(client, admin), "lembrete_sacola")["naFila"] == 1

    assert _executar(client, admin)["lembrete_sacola"]["criados"] == 1
    painel = _painel(client, admin)
    sacola = _email(painel, "lembrete_sacola")
    assert sacola["naFila"] == 0 and sacola["enviadosHoje"] == 1
    [linha] = [linha for linha in painel["envios"] if linha["tipo"] == "lembrete_sacola"]
    assert linha["cliente"] == "Mariana Costa" and linha["modo"] == "TESTE" and linha["para"] is None


def test_fila_do_avise_me_conta_quem_tem_peca_de_volta(client, admin, caixa):
    variacao = _peca_disponivel(client)
    sql("INSERT INTO avisos_estoque (cliente_id, variacao_id, criado_em) VALUES (:c, :v, :t)", c=MARIANA, v=variacao, t=agora())
    assert _email(_painel(client, admin), "aviso_estoque")["naFila"] == 1

    assert _executar(client, admin)["aviso_estoque"]["criados"] == 1
    painel = _painel(client, admin)
    assert _email(painel, "aviso_estoque")["naFila"] == 0
    [linha] = [linha for linha in painel["envios"] if linha["tipo"] == "aviso_estoque"]
    assert (linha["cliente"], linha["para"], linha["resumo"]) == ("Mariana Costa", TIME, "1 peça de volta")


def test_lista_junta_os_tres_tipos_do_mais_recente_para_o_mais_antigo(client, admin):
    momento = agora()
    variacao = sql("SELECT id FROM variacoes ORDER BY id LIMIT 1")[0][0]
    [(nome_ricardo,)] = sql("SELECT nome FROM clientes WHERE id = :c", c=RICARDO)
    # Dois vencimentos avisados no mesmo e-mail viram uma linha só, com os pontos somados
    for dias, pontos in ((10, 800), (20, 200)):
        sql(
            "INSERT INTO avisos_pontos (cliente_id, vencimento, pontos, modo, email, sem_numeros, enviado_em) "
            "VALUES (:c, :v, :p, 'REAL', :e, false, :t)",
            c=MARIANA,
            v=(momento + timedelta(days=dias)).date(),
            p=pontos,
            e=EMAIL_MARIANA,
            t=momento - timedelta(hours=3),
        )
    sql(
        "INSERT INTO avisos_estoque (cliente_id, variacao_id, criado_em, avisado_em, modo, email) VALUES (:c, :v, :t, :t, 'TESTE', :e)",
        c=RICARDO,
        v=variacao,
        t=momento - timedelta(hours=2),
        e=TIME,
    )
    sql(
        "INSERT INTO sacolas (cliente_id, itens, atualizada_em, lembrete_em, lembrete_modo) VALUES (:c, '[]', :t, :t, 'REAL')",
        c=MARIANA,
        t=momento - timedelta(hours=1),
    )

    envios = _painel(client, admin)["envios"]
    assert [(e["tipo"], e["cliente"], e["modo"], e["para"], e["resumo"]) for e in envios] == [
        ("lembrete_sacola", "Mariana Costa", "REAL", EMAIL_MARIANA, "Peças paradas na sacola"),
        ("aviso_estoque", nome_ricardo, "TESTE", TIME, "1 peça de volta"),
        ("aviso_pontos", "Mariana Costa", "REAL", EMAIL_MARIANA, "1.000 pontos vencendo"),
    ]

    # Cliente que excluiu a conta: a linha fica, sem o nome
    sql("UPDATE clientes SET excluido_em = :t WHERE id = :c", t=momento, c=RICARDO)
    envios = _painel(client, admin)["envios"]
    assert [e["cliente"] for e in envios] == ["Mariana Costa", None, "Mariana Costa"]


def test_alertas_continuam_no_assistente_ia(client, admin, desligados):
    """Os alertas saíram da tela, mas o botão continua criando os alertas que o Assistente IA consulta."""
    sql(
        "UPDATE estoques SET quantidade = 0 WHERE id = (SELECT e.id FROM estoques e JOIN variacoes v ON v.id = e.variacao_id WHERE e.loja_id = 1 AND v.sku = 'CL-CML-BRA-M')"
    )
    assert _executar(client, admin)["estoque_baixo"]["criados"] > 0
    [(abertos,)] = sql("SELECT count(*) FROM alertas WHERE status = 'ABERTO'")

    resposta = pergunte(client, abrir_copiloto(client, admin), admin, "Quais são os alertas abertos?")
    assert f"Há {abertos} alertas abertos" in resposta["texto"]
    assert blocos(resposta, "tabela") and not blocos(resposta, "link")


@pytest.fixture
def modo_real(monkeypatch):
    """Os três envios ligados no modo real, com o Resend trocado por uma lista."""
    enviados = []
    for chave in CHAVES:
        monkeypatch.setattr(settings, chave, True)
    monkeypatch.setattr(settings, "AVISO_PONTOS_TESTE_PARA", "")
    monkeypatch.setattr(settings, "AVISOS_TESTE_PARA", "")
    for modulo in (avisos_pontos, avisos_cliente):
        monkeypatch.setattr(modulo, "PAUSA_ENTRE_ENVIOS", 0)
        monkeypatch.setattr(modulo, "_enviar_de_verdade", enviados.append)
    return enviados


def test_modo_real_so_manda_para_quem_criou_conta_no_site(client, admin, mariana, modo_real):
    """Decisão 127: a base migrada e as contas de demonstração não recebem; quem criou a conta no site recebe."""
    _pontos_vencendo(MARIANA)
    variacao = _peca_disponivel(client)
    client.put("/api/conta/sacola", headers=mariana, json={"itens": [{"variacaoId": variacao, "quantidade": 1}]})
    sql("UPDATE sacolas SET atualizada_em = :t", t=agora() - timedelta(hours=25))
    sql("UPDATE clientes SET aceita_marketing = true WHERE id = :c", c=MARIANA)

    # Mariana é conta do seed (sem cadastro pelo site): nada sai, nem entra na fila
    painel = _painel(client, admin)
    assert _email(painel, "lembrete_sacola")["naFila"] == 0
    execucoes = _executar(client, admin)
    assert execucoes["lembrete_sacola"]["criados"] == 0 and execucoes["aviso_pontos"]["criados"] == 0
    assert modo_real == []

    # Criou a conta no site: recebe no próprio e-mail, sem a marca de teste
    sql("UPDATE clientes SET canal_cadastro = 'E-commerce' WHERE id = :c", c=MARIANA)
    assert _email(_painel(client, admin), "lembrete_sacola")["naFila"] == 1
    sql("DELETE FROM execucoes_automacao")  # o intervalo mínimo de 1 minuto
    execucoes = _executar(client, admin)
    assert execucoes["lembrete_sacola"]["criados"] == 1 and execucoes["aviso_pontos"]["criados"] == 1
    assert {e.para for e in modo_real} == {EMAIL_MARIANA}
    assert not any(e.assunto.startswith("[Teste") for e in modo_real)
