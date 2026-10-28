"""Verificador de números (decisão 101): todo número da resposta do modelo precisa ter fonte (as ferramentas, o
contexto do sistema ou, para o que não é dinheiro nem pontos, o próprio cliente). Sem fonte, o modelo refaz uma vez;
se errar de novo, sai o texto pronto das ferramentas ou "não consegui confirmar". A dor é a do CFO: "prefiro que
ela diga 'não sei' do que invente"."""

from datetime import timedelta

from src.database.connection import SessionLocal
from src.integrations import ia
from src.use_cases import fidelidade
from src.use_cases.assistente import verificacao as v
from src.use_cases.assistente.prompts import SEM_CONFIRMACAO
from src.utils.datas import agora
from tests.ia_falsa import ProvedorFalso, erro, ferramenta, texto
from tests.util_assistente import abrir_copiloto, abrir_site, diga, entrar, pergunte, sql

MARIANA = 101


def _pontos(cliente_id: int, quantidade: int) -> None:
    with SessionLocal() as db:
        fidelidade.travar(db, cliente_id)
        fidelidade.lancar(db, cliente_id, "CREDITO", quantidade, agora() - timedelta(days=30), obs="teste")
        db.commit()


def _auditoria(conversa: str) -> dict:
    return sql(
        "SELECT auditoria FROM mensagens_assistente WHERE conversa_id = :c AND auditoria IS NOT NULL ORDER BY id DESC LIMIT 1",
        c=conversa,
    )[0][0]


def _mariana(client) -> tuple[str, dict]:
    return abrir_site(client, token=entrar(client, "mariana.costa@gmail.com"))


# ---------- As regras do verificador ----------

DADOS = {
    "saldo": "1.200",
    "valorEmReais": "R$ 60,00",
    "vencimentos": [{"data": "12/11/2026", "pontos": "300"}],
    "pedido": "CL-105093",
    "total": "R$ 345.545,73",
    "prazo": "até 12 dias úteis",
    "parcelas": "até 6x",
    "horario": "10:00 às 22:00",
    "telefone": "+55 31 8435-7742",
    "variacao": "+8,4%",
    "encontrados": 74,
    "produtoId": 345,
    "imagem": "/fotos/camisa-77.webp",
    "cuidados": "Hidratar o couro a cada seis meses.",
}


def _conferir(frase: str, usuario: str = "") -> v.Resultado:
    contexto = v.sem_ids("- Agora: 27/10/2026 (terça-feira), 19:45.\n- Peças mostradas: 1. Camisa (id 12); 2. Saia (id 15).")
    fortes = v.fontes_de(DADOS, {"preco": 489.0}, contexto).juntar(
        v.fontes_com_unidade("Regras:\n12. A devolução vale até 30 dias.")
    )
    return v.conferir(frase, fortes, v.fontes_de(usuario))


def test_numeros_copiados_das_ferramentas_passam():
    for frase in [
        "Você tem 1.200 pontos Lupe+ (R$ 60,00 em desconto); 300 vencem em 12/11/2026.",
        "300 pontos vencem em 12 de novembro de 2026, no dia 12.",
        "A camisa custa R$ 489. Encontrei 74 peças.",
        "Chega em até 12 dias úteis e dá para parcelar em até 6x.",
        "Hoje, 27/10, a loja abre às 10h e fecha às 22. Telefone: (31) 8435-7742.",
        "O faturamento foi de R$ 345.545,73, alta de 8,4%.",
        "O pedido 105093 já foi enviado. A devolução vale por até 30 dias.",
        "Hidrate o couro a cada seis meses. A 2ª opção está nas 3 lojas.",
    ]:
        resultado = _conferir(frase)
        assert resultado.ok, (frase, resultado.sem_fonte)
        assert resultado.conferidos > 0


def test_numero_inventado_e_barrado():
    for frase, inventado in [
        ("Você tem 5.000 pontos.", "5.000"),
        ("Você tem mil pontos.", "mil pontos"),  # o exemplo do CFO, por extenso
        ("Seus pontos vencem em 13 de novembro.", "13 de novembro"),
        ("O seu pedido chega dia 30/10.", "30/10"),
        ("A loja fecha às 23.", "23"),
        ("Dá para parcelar em até 12x.", "12"),
        ("O faturamento subiu 12% em relação ao mês anterior.", "12"),  # "12 dias" não é fonte de "12%"
        ("Chega em trinta dias.", "trinta dias"),
    ]:
        resultado = _conferir(frase)
        assert not resultado.ok and inventado in resultado.sem_fonte, (frase, resultado.sem_fonte)


def test_o_que_o_cliente_disse_nao_vira_saldo_nem_preco():
    usuario = "eu tinha 5000 pontos, e o pedido 105044? quero no 42 até 200 reais"
    assert not _conferir("Você tem 5.000 pontos.", usuario).ok
    assert not _conferir("Achei peças até R$ 200,00.", usuario).ok
    # Tamanho e número de pedido que o cliente citou podem ser repetidos
    assert _conferir("Achei 2 opções no 42, mas o pedido 105044 não está na sua conta.", usuario).ok


def test_ids_links_e_numeracao_nao_sao_fonte():
    assert not _conferir("A camisa custa R$ 345.").ok  # 345 é o id da peça
    assert not _conferir("A camisa custa R$ 77.").ok  # 77 está no nome da foto
    assert not _conferir("A saia custa R$ 15.").ok  # 15 é o id do contexto
    assert not _conferir("Hoje tem 12% de desconto.").ok  # 12 é o número da regra


# ---------- Na conversa, com o modelo ----------


def test_resposta_certa_sai_como_veio_sem_chamada_a_mais(client):
    _pontos(MARIANA, 1200)
    falso = ProvedorFalso(ferramenta("consultar_meus_pontos", {}), texto("Você tem 1.200 pontos Lupe+."))
    ia.definir_provedor(falso)
    conversa, chave = _mariana(client)
    resposta = diga(client, conversa, chave, "quantos pontos eu tenho?")
    assert resposta["texto"] == "Você tem 1.200 pontos Lupe+."
    assert len(falso.pedidos) == 2  # a conferência não custa chamada
    assert _auditoria(conversa) == {"verificacao": "CONFERIDA", "numeros": 1}


def test_modelo_inventa_o_saldo_e_corrige_consultando(client):
    _pontos(MARIANA, 1200)
    falso = ProvedorFalso(
        texto("Você tem 5.000 pontos Lupe+."),  # sem consultar: inventou
        ferramenta("consultar_meus_pontos", {}),
        texto("Você tem 1.200 pontos Lupe+."),
    )
    ia.definir_provedor(falso)
    conversa, chave = _mariana(client)
    resposta = diga(client, conversa, chave, "eu tenho 5000 pontos, né?")
    assert resposta["texto"] == "Você tem 1.200 pontos Lupe+."
    aviso = falso.pedidos[1]["mensagens"][-1]
    assert aviso["role"] == "user" and "Verificação automática" in aviso["content"] and "“5.000”" in aviso["content"]
    assert falso.pedidos[1]["sem_ferramentas"] is False  # pode consultar o que faltou
    auditoria = _auditoria(conversa)
    assert auditoria["verificacao"] == "REESCRITA" and auditoria["semFonte"] == ["5.000"]
    assert auditoria["textoModelo"] == "Você tem 5.000 pontos Lupe+."
    # O número inventado não aparece para o cliente nem no histórico da conversa
    historico = client.get(f"/api/assistente/conversas/{conversa}", headers=chave).json()["mensagens"]
    assert all("5.000" not in m["texto"] for m in historico if m["papel"] == "ASSISTENTE")


def test_errou_duas_vezes_sai_o_texto_da_ferramenta(client):
    _pontos(MARIANA, 1200)
    falso = ProvedorFalso(
        ferramenta("consultar_meus_pontos", {}),
        texto("Você tem 1.500 pontos, que valem R$ 75,00."),
        texto("Corrigindo: são 1.250 pontos."),
    )
    ia.definir_provedor(falso)
    conversa, chave = _mariana(client)
    resposta = diga(client, conversa, chave, "quantos pontos eu tenho?")
    assert "1.200" in resposta["texto"] and "1.500" not in resposta["texto"] and "1.250" not in resposta["texto"]
    assert [b["tipo"] for b in resposta["blocos"]] == ["pontos"]  # o cartão dos pontos continua
    auditoria = _auditoria(conversa)
    assert auditoria["verificacao"] == "SUBSTITUIDA"
    assert auditoria["semFonte"] == ["1.500", "75,00"] and auditoria["semFonteDepois"] == ["1.250"]


def test_sem_consulta_e_sem_fonte_diz_que_nao_confirmou(client):
    falso = ProvedorFalso(texto("O frete para Manaus fica R$ 19,90."), texto("O frete sai por R$ 19,90."))
    ia.definir_provedor(falso)
    conversa, chave = abrir_site(client)
    resposta = diga(client, conversa, chave, "quanto é o frete pra Manaus?")
    assert resposta["texto"] == SEM_CONFIRMACAO["CLIENTE"]
    assert _auditoria(conversa)["verificacao"] == "SUBSTITUIDA"


def test_modelo_cai_na_correcao_e_o_numero_errado_nao_sai(client):
    _pontos(MARIANA, 1200)
    falso = ProvedorFalso(ferramenta("consultar_meus_pontos", {}), texto("Você tem 9.999 pontos."), erro("TIMEOUT"))
    ia.definir_provedor(falso)
    conversa, chave = _mariana(client)
    resposta = diga(client, conversa, chave, "meus pontos")
    assert "1.200" in resposta["texto"] and "9.999" not in resposta["texto"]
    assert resposta["modo"] == "CONTINGENCIA"
    assert _auditoria(conversa)["semFonte"] == ["9.999"]


def test_copiloto_nao_inventa_percentual(client):
    helena = entrar(client, "helena@casalorenzi.com.br")
    falso = ProvedorFalso(
        ferramenta("consultar_faturamento", {"periodo": "ultimos_30_dias"}),
        texto("O faturamento cresceu 37,5% sobre o período anterior."),
        texto("O faturamento dos últimos 30 dias está no quadro abaixo, com o período e a definição."),
    )
    ia.definir_provedor(falso)
    conversa = abrir_copiloto(client, helena)
    resposta = pergunte(client, conversa, helena, "quanto crescemos?")
    assert "37,5" not in resposta["texto"]
    assert _auditoria(conversa)["verificacao"] == "REESCRITA"
