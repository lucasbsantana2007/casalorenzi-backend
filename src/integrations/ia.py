"""Modelo de linguagem dos assistentes: Claude, da Anthropic, pelo SDK oficial (anthropic).

O resto do sistema só conhece RespostaIA e ErroIA. Trocar de modelo é mudar IA_MODELO no ambiente; os
testes trocam o provedor inteiro por um falso (definir_provedor). Sem ANTHROPIC_API_KEY, provedor()
devolve None e os assistentes respondem pelas regras determinísticas.

Cuidados com os modelos atuais (Claude Haiku 5.5, Sonnet 5.5, Opus 5.5):
- nada de temperature/top_p/top_k (a versão 2026-10-21 da API recusa); o custo se controla pelo esforço
  (output_config.effort) e pelo teto de tokens;
- a resposta pode começar com blocos de raciocínio: o texto é lido pelo tipo do bloco, nunca pela posição,
  e os blocos voltam intactos ao modelo na mesma rodada de ferramentas (RespostaIA.conteudo);
- a parte fixa (ferramentas + instruções) leva cache_control: as chamadas seguintes leem do cache;
- stop_reason "refusal": o modelo recusou por segurança. Não é erro: o assistente responde com segurança.
A chave nunca sai daqui: não vai para o frontend, para os logs nem para o banco.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from src.config import settings

log = logging.getLogger("casalorenzi.ia")


@dataclass
class ChamadaFerramentaIA:
    id: str
    nome: str
    # O que o modelo mandou, sem confiar: quem executa valida (pode nem ser um dicionário)
    argumentos: Any


@dataclass
class RespostaIA:
    texto: str
    chamadas: list[ChamadaFerramentaIA]
    # end_turn, tool_use, max_tokens, refusal...
    parada: str
    # Blocos da resposta como vieram (inclusive o raciocínio), para devolver ao modelo na mesma rodada
    conteudo: list = field(default_factory=list)
    modelo: str = ""
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache_leitura: int = 0
    tokens_cache_escrita: int = 0
    duracao_ms: int = 0


class ErroIA(Exception):
    """Falha ao falar com o modelo. tipo: TIMEOUT, CONEXAO, LIMITE, AUTENTICACAO, REQUISICAO, SERVIDOR ou
    RESPOSTA (resposta num formato inesperado). A mensagem não traz a chave nem o conteúdo da conversa."""

    def __init__(self, tipo: str, mensagem: str, duracao_ms: int = 0):
        super().__init__(mensagem)
        self.tipo = tipo
        self.mensagem = mensagem
        self.duracao_ms = duracao_ms


class ProvedorIA(Protocol):
    nome: str
    modelo: str

    def gerar(
        self, *, sistema: list[dict], ferramentas: list[dict], mensagens: list[dict], sem_ferramentas: bool = False
    ) -> RespostaIA: ...


def _uso(resposta, campo: str) -> int:
    return int(getattr(resposta.usage, campo, 0) or 0)


class ProvedorAnthropic:
    nome = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        modelo: str,
        esforco: str,
        max_tokens: int,
        timeout: float,
        max_tentativas: int,
        http_client=None,
    ):
        self.modelo = modelo
        self.esforco = esforco
        self.max_tokens = max_tokens
        opcoes = {"http_client": http_client} if http_client is not None else {}
        self._cliente = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=max_tentativas, **opcoes)

    def gerar(
        self, *, sistema: list[dict], ferramentas: list[dict], mensagens: list[dict], sem_ferramentas: bool = False
    ) -> RespostaIA:
        """Uma chamada à API de mensagens. sem_ferramentas: a última rodada, em que o modelo precisa
        responder com texto (as ferramentas continuam declaradas, o que mantém o cache)."""
        parametros: dict[str, Any] = {
            "model": self.modelo,
            "max_tokens": self.max_tokens,
            "system": sistema,
            "messages": mensagens,
            "output_config": {"effort": self.esforco},
            # Cache automático da conversa (o bloco fixo do sistema já tem o seu cache_control)
            "cache_control": {"type": "ephemeral"},
        }
        if ferramentas:
            parametros["tools"] = ferramentas
            parametros["tool_choice"] = {"type": "none"} if sem_ferramentas else {"type": "auto"}
        inicio = time.perf_counter()

        def duracao() -> int:
            return int((time.perf_counter() - inicio) * 1000)

        try:
            resposta = self._cliente.messages.create(**parametros)
        except anthropic.APITimeoutError:
            raise ErroIA("TIMEOUT", "O modelo demorou demais para responder.", duracao()) from None
        except anthropic.APIConnectionError:
            raise ErroIA("CONEXAO", "Sem conexão com a API do modelo.", duracao()) from None
        except anthropic.RateLimitError:
            raise ErroIA("LIMITE", "Limite de uso da API do modelo atingido.", duracao()) from None
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise ErroIA("AUTENTICACAO", "A chave da API do modelo foi recusada.", duracao()) from None
        except anthropic.APIStatusError as erro:
            tipo = "SERVIDOR" if erro.status_code >= 500 else "REQUISICAO"
            raise ErroIA(tipo, f"A API do modelo respondeu {erro.status_code}.", duracao()) from None
        return self._ler(resposta, duracao())

    def _ler(self, resposta, duracao_ms: int) -> RespostaIA:
        try:
            textos, chamadas = [], []
            for bloco in resposta.content:
                if bloco.type == "text":
                    textos.append(bloco.text)
                elif bloco.type == "tool_use":
                    chamadas.append(ChamadaFerramentaIA(id=bloco.id, nome=bloco.name, argumentos=bloco.input))
            return RespostaIA(
                texto="\n".join(t for t in textos if t).strip(),
                chamadas=chamadas,
                parada=resposta.stop_reason or "",
                conteudo=list(resposta.content),
                modelo=resposta.model or self.modelo,
                tokens_entrada=_uso(resposta, "input_tokens"),
                tokens_saida=_uso(resposta, "output_tokens"),
                tokens_cache_leitura=_uso(resposta, "cache_read_input_tokens"),
                tokens_cache_escrita=_uso(resposta, "cache_creation_input_tokens"),
                duracao_ms=duracao_ms,
            )
        except (AttributeError, TypeError) as erro:
            raise ErroIA("RESPOSTA", f"Resposta do modelo em formato inesperado ({type(erro).__name__}).", duracao_ms) from None


_provedor: ProvedorIA | None = None
_substituto: ProvedorIA | None = None
_substituido = False


def provedor() -> ProvedorIA | None:
    """O modelo configurado, ou None (sem chave: os assistentes usam só as regras)."""
    global _provedor
    if _substituido:
        return _substituto
    if not settings.ANTHROPIC_API_KEY:
        return None
    if _provedor is None:
        _provedor = ProvedorAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            modelo=settings.IA_MODELO,
            esforco=settings.IA_ESFORCO,
            max_tokens=settings.IA_MAX_TOKENS,
            timeout=settings.IA_TIMEOUT_SEGUNDOS,
            max_tentativas=settings.IA_MAX_TENTATIVAS,
        )
    return _provedor


def definir_provedor(substituto: ProvedorIA | None) -> None:
    """Testes: troca o provedor (None = como se não houvesse chave)."""
    global _substituto, _substituido
    _substituto, _substituido = substituto, True


def restaurar_provedor() -> None:
    global _substituto, _substituido
    _substituto, _substituido = None, False
