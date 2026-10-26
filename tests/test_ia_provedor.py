"""Provedor do modelo (SDK oficial da Anthropic) contra um transporte HTTP simulado: o pedido sai no formato
certo (sem temperature, com cache e esforço), a resposta é lida pelo tipo dos blocos e os erros da API viram
ErroIA. Nenhuma chamada sai para a internet."""

import json

import httpx2
import pytest

from src.integrations.ia import ErroIA, ProvedorAnthropic

RESPOSTA_COM_FERRAMENTA = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-haiku-5-5",
    "content": [
        {"type": "thinking", "thinking": "", "signature": "assinatura"},
        {"type": "text", "text": "Vou procurar."},
        {"type": "tool_use", "id": "toolu_1", "name": "buscar_produtos", "input": {"tipo_peca": "camisa"}},
    ],
    "stop_reason": "tool_use",
    "stop_sequence": None,
    "usage": {"input_tokens": 1200, "output_tokens": 80, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 50},
}


def _provedor(resposta, pedidos: list | None = None) -> ProvedorAnthropic:
    def transporte(request):
        if pedidos is not None:
            pedidos.append((request.headers, json.loads(request.content)))
        return resposta(request) if callable(resposta) else httpx2.Response(200, json=resposta)

    return ProvedorAnthropic(
        api_key="sk-teste",
        modelo="claude-haiku-5-5",
        esforco="low",
        max_tokens=2048,
        timeout=5,
        max_tentativas=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(transporte)),
    )


def _gerar(provedor, **extra):
    return provedor.gerar(
        sistema=[{"type": "text", "text": "fixo", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "contexto"}],
        ferramentas=[{"name": "buscar_produtos", "description": "busca", "input_schema": {"type": "object", "properties": {}}}],
        mensagens=[{"role": "user", "content": "tem camisa?"}],
        **extra,
    )


def test_formato_do_pedido():
    pedidos = []
    _gerar(_provedor(RESPOSTA_COM_FERRAMENTA, pedidos))
    cabecalhos, corpo = pedidos[0]
    assert corpo["model"] == "claude-haiku-5-5"
    assert corpo["output_config"] == {"effort": "low"}
    assert corpo["tool_choice"] == {"type": "auto"}
    assert corpo["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert not {"temperature", "top_p", "top_k"} & set(corpo)  # a API atual recusa os três
    assert cabecalhos["anthropic-version"] == "2026-10-21"


def test_ultima_rodada_pede_so_texto():
    pedidos = []
    _gerar(_provedor(RESPOSTA_COM_FERRAMENTA, pedidos), sem_ferramentas=True)
    assert pedidos[0][1]["tool_choice"] == {"type": "none"}


def test_le_a_resposta_pelo_tipo_dos_blocos():
    resposta = _gerar(_provedor(RESPOSTA_COM_FERRAMENTA))
    assert resposta.texto == "Vou procurar."
    assert [(c.nome, c.argumentos) for c in resposta.chamadas] == [("buscar_produtos", {"tipo_peca": "camisa"})]
    assert resposta.parada == "tool_use"
    assert (resposta.tokens_entrada, resposta.tokens_saida, resposta.tokens_cache_leitura, resposta.tokens_cache_escrita) == (
        1200,
        80,
        900,
        50,
    )
    assert [b.type for b in resposta.conteudo] == ["thinking", "text", "tool_use"]


def test_raciocinio_volta_intacto_na_mesma_rodada():
    pedidos = []
    provedor = _provedor(RESPOSTA_COM_FERRAMENTA, pedidos)
    primeira = _gerar(provedor)
    provedor.gerar(
        sistema=[{"type": "text", "text": "fixo"}],
        ferramentas=[],
        mensagens=[
            {"role": "user", "content": "tem camisa?"},
            {"role": "assistant", "content": primeira.conteudo},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "{}"}]},
        ],
    )
    devolvidos = pedidos[1][1]["messages"][1]["content"]
    assert [b["type"] for b in devolvidos] == ["thinking", "text", "tool_use"]
    assert devolvidos[0]["signature"] == "assinatura"


@pytest.mark.parametrize(
    ("status", "tipo"),
    [(529, "SERVIDOR"), (500, "SERVIDOR"), (429, "LIMITE"), (401, "AUTENTICACAO"), (400, "REQUISICAO")],
)
def test_erros_da_api_viram_erro_ia(status, tipo):
    def falha(request):
        return httpx2.Response(status, json={"type": "error", "error": {"type": "x", "message": "falhou"}})

    with pytest.raises(ErroIA) as erro:
        _gerar(_provedor(falha))
    assert erro.value.tipo == tipo
    assert "sk-teste" not in erro.value.mensagem


def test_tempo_esgotado_e_sem_conexao():
    def lento(request):
        raise httpx2.ReadTimeout("lento", request=request)

    def fora(request):
        raise httpx2.ConnectError("sem rede", request=request)

    with pytest.raises(ErroIA) as erro:
        _gerar(_provedor(lento))
    assert erro.value.tipo == "TIMEOUT"
    with pytest.raises(ErroIA) as erro:
        _gerar(_provedor(fora))
    assert erro.value.tipo == "CONEXAO"
