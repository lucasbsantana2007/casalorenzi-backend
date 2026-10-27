"""Uma rodada do assistente: a mensagem do usuário vira uma resposta com texto e blocos.

Ordem de decisão:
1. Mensagem simples (saudação, agradecimento, pedido de atendente): resposta direta, sem modelo (custo zero).
2. Com ANTHROPIC_API_KEY: o modelo escolhe as ferramentas, no máximo IA_MAX_RODADAS idas e voltas e
   IA_MAX_FERRAMENTAS consultas; a última rodada pede só texto. Os blocos da tela vêm das ferramentas.
3. Sem chave: as regras determinísticas respondem com as mesmas ferramentas (modo REGRAS).
4. O modelo falhou (fora do ar, tempo esgotado, resposta inválida): se alguma consulta já tinha dado certo,
   a resposta usa o resultado dela; senão, as regras respondem (modo CONTINGENCIA). O usuário nunca vê o erro técnico.
5. Todo número da resposta do modelo é conferido antes de sair (verificacao.py, decisão 98). Número sem fonte: o
   modelo tem uma chance de refazer (com as ferramentas, porque pode ter faltado uma consulta); se errar de novo, a
   resposta vira o texto pronto das ferramentas ou "não consegui confirmar". A auditoria guarda o que aconteceu.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from src.config import settings
from src.entities.assistente import CONTINGENCIA, LLM, REGRAS, custo_estimado
from src.integrations import ia
from src.use_cases.assistente import verificacao
from src.use_cases.assistente.ferramentas import Contexto, Execucao, Ferramenta, executar, oferecidas, registro_de
from src.use_cases.assistente.formatacao import cru
from src.use_cases.assistente.prompts import CORRIGIR_NUMEROS, RECUSA_SEGURA, SEM_CONFIRMACAO, SEM_RESPOSTA

log = logging.getLogger("casalorenzi.assistente")

# Bloco que pede o login dentro do chat (pontos, pedidos e outros dados do cliente)
BLOCO_ENTRAR = "entrar"


@dataclass
class Rodada:
    texto: str
    blocos: list[dict] = field(default_factory=list)
    modo: str = REGRAS
    memoria: dict = field(default_factory=dict)
    execucoes: list[Execucao] = field(default_factory=list)
    consumos: list[dict] = field(default_factory=list)
    # A rodada não resolveu (não entendeu, não conseguiu responder ou não confirmou o número): conta para
    # "duas falhas seguidas → pessoa" (decisão 99)
    falhou: bool = False
    # Conferência dos números da resposta do modelo (decisão 98), gravada com a mensagem
    auditoria: dict | None = None


@dataclass
class Assistente:
    """O que muda entre o assistente do site e o copiloto."""

    tipo: str
    ferramentas: list[Ferramenta]
    prompt_fixo: str
    # (texto, contexto, executar) -> Rodada ou None
    direta: Callable[[str, Contexto, Callable], Rodada | None]
    regras: Callable[[str, Contexto, Callable], Rodada]


def aplicar_memoria(memoria: dict, mudancas: dict) -> dict:
    """None apaga a chave; o resto substitui."""
    nova = dict(memoria)
    for chave, valor in mudancas.items():
        if valor is None:
            nova.pop(chave, None)
        else:
            nova[chave] = valor
    return nova


class Coletor:
    """Junta o que as ferramentas devolveram numa rodada: memória, blocos (o último de cada ferramenta) e a auditoria."""

    def __init__(self, ctx: Contexto, registro: dict[str, Ferramenta]):
        self.ctx = ctx
        self.registro = registro
        self.execucoes: list[Execucao] = []
        self._blocos: dict[str, list[dict]] = {}

    def __call__(self, nome: str, argumentos: dict | None = None) -> Execucao:
        if len(self.execucoes) >= settings.IA_MAX_FERRAMENTAS:
            execucao = Execucao(str(nome)[:60], argumentos, None, "LIMITE_DE_CONSULTAS: responda com o que já tem.", 0)
        else:
            execucao = executar(self.registro, nome, argumentos, self.ctx)
        execucao.origem = self.ctx.origem
        self.execucoes.append(execucao)
        if execucao.sucesso and execucao.resultado is not None:
            self.ctx.memoria = aplicar_memoria(self.ctx.memoria, execucao.resultado.memoria)
            self._blocos.pop(execucao.nome, None)
            self._blocos[execucao.nome] = execucao.resultado.blocos
        elif (execucao.erro or "").startswith("LOGIN_NECESSARIO"):
            # O chat mostra o login ali mesmo; depois de entrar, a pergunta é respondida sem sair da conversa
            self._blocos[BLOCO_ENTRAR] = [{"tipo": BLOCO_ENTRAR}]
        return execucao

    @property
    def blocos(self) -> list[dict]:
        return [bloco for blocos in self._blocos.values() for bloco in blocos]

    def ultimo_texto(self) -> str | None:
        for execucao in reversed(self.execucoes):
            if execucao.sucesso and execucao.resultado and execucao.resultado.texto:
                return execucao.resultado.texto
        return None

    def textos(self, limite: int = 3) -> list[str]:
        """Os textos prontos das consultas que deram certo, sem repetir (os últimos `limite`)."""
        prontos = [e.resultado.texto for e in self.execucoes if e.sucesso and e.resultado and e.resultado.texto]
        return list(dict.fromkeys(prontos))[-limite:]


def _historico_para_modelo(historico: list[tuple[str, str]]) -> list[dict]:
    """Últimas mensagens (papel, texto) no formato da API: começa pelo usuário e pula texto vazio."""
    mensagens = []
    for papel, texto in historico[-settings.IA_HISTORICO_MENSAGENS :]:
        if not texto.strip():
            continue
        role = "user" if papel == "USUARIO" else "assistant"
        if not mensagens and role != "user":
            continue
        mensagens.append({"role": role, "content": texto})
    return mensagens


def _consumo(provedor, resposta: ia.RespostaIA | None, status: str, erro: ia.ErroIA | None = None) -> dict:
    if resposta is None:
        return {
            "provedor": provedor.nome,
            "modelo": provedor.modelo,
            "status": status,
            "duracao_ms": erro.duracao_ms if erro else 0,
        }
    custo = custo_estimado(
        resposta.modelo or provedor.modelo,
        resposta.tokens_entrada,
        resposta.tokens_saida,
        resposta.tokens_cache_leitura,
        resposta.tokens_cache_escrita,
    )
    return {
        "provedor": provedor.nome,
        "modelo": resposta.modelo or provedor.modelo,
        "status": status,
        "tokens_entrada": resposta.tokens_entrada,
        "tokens_saida": resposta.tokens_saida,
        "tokens_cache_leitura": resposta.tokens_cache_leitura,
        "tokens_cache_escrita": resposta.tokens_cache_escrita,
        "custo_estimado": custo,
        "duracao_ms": resposta.duracao_ms,
    }


def _resultado_para_modelo(execucao: Execucao) -> dict:
    if execucao.sucesso and execucao.resultado is not None:
        conteudo = json.dumps(cru(execucao.resultado.dados), ensure_ascii=False, separators=(",", ":"))
        return {"type": "tool_result", "content": conteudo}
    return {"type": "tool_result", "content": execucao.erro or "FALHA_INTERNA", "is_error": True}


def _fontes(assistente: Assistente, lista, contexto_dinamico: str, coletor: Coletor, historico, texto: str):
    """(fontes fortes, fontes do usuário) para conferir os números da resposta do modelo (decisão 98)."""
    saidas = [
        (e.resultado.dados, e.resultado.blocos, e.resultado.texto) if e.sucesso and e.resultado else e.erro
        for e in coletor.execucoes
    ]
    respostas_anteriores = [t for papel, t in historico if papel != "USUARIO"]
    fortes = verificacao.fontes_com_unidade(assistente.prompt_fixo, verificacao.descricoes(lista)).juntar(
        verificacao.fontes_de(verificacao.sem_ids(contexto_dinamico), respostas_anteriores, saidas)
    )
    do_usuario = verificacao.fontes_de(texto, [t for papel, t in historico if papel == "USUARIO"])
    return fortes, do_usuario


def _auditoria(situacao: str, final: verificacao.Resultado, primeira: verificacao.Resultado | None, texto_modelo: str) -> dict:
    auditoria = {"verificacao": situacao, "numeros": final.conferidos}
    if primeira is not None:
        auditoria |= {"semFonte": primeira.sem_fonte, "textoModelo": texto_modelo[:1500]}
    return auditoria


def _com_modelo(provedor, assistente: Assistente, texto: str, ctx: Contexto, historico, contexto_dinamico: str) -> Rodada:
    lista = oferecidas(assistente.ferramentas, ctx)
    coletor = Coletor(ctx, registro_de(lista))
    esquemas = [f.esquema() for f in lista]
    sistema = [
        {"type": "text", "text": assistente.prompt_fixo, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": contexto_dinamico},
    ]
    mensagens = [*_historico_para_modelo(historico), {"role": "user", "content": texto}]
    consumos: list[dict] = []
    resposta_final = ""
    conferencia = verificacao.Resultado(ok=True)
    # A conferência que falhou e o texto do modelo, quando ele teve a chance de refazer
    primeira: verificacao.Resultado | None = None
    texto_modelo = ""
    try:
        # +1: a chance de refazer a resposta que trouxe número sem fonte
        for rodada in range(settings.IA_MAX_RODADAS + 1):
            ultima = rodada >= settings.IA_MAX_RODADAS - 1 or len(coletor.execucoes) >= settings.IA_MAX_FERRAMENTAS
            resposta = provedor.gerar(sistema=sistema, ferramentas=esquemas, mensagens=mensagens, sem_ferramentas=ultima)
            if resposta.parada == "refusal":
                consumos.append(_consumo(provedor, resposta, "RECUSA"))
                return Rodada(RECUSA_SEGURA[assistente.tipo], [], LLM, ctx.memoria, coletor.execucoes, consumos)
            consumos.append(_consumo(provedor, resposta, "OK"))
            if resposta.parada == "tool_use" and resposta.chamadas and not ultima:
                mensagens.append({"role": "assistant", "content": resposta.conteudo})
                resultados = []
                for chamada in resposta.chamadas:
                    execucao = coletor(chamada.nome, chamada.argumentos)
                    resultados.append({**_resultado_para_modelo(execucao), "tool_use_id": chamada.id})
                mensagens.append({"role": "user", "content": resultados})
                continue
            resposta_final = resposta.texto
            conferencia = verificacao.conferir(
                resposta_final, *_fontes(assistente, lista, contexto_dinamico, coletor, historico, texto)
            )
            if conferencia.ok or primeira is not None:
                break
            primeira, texto_modelo = conferencia, resposta_final
            log.info("Número sem fonte na conversa %s: %s", ctx.conversa_id, ", ".join(conferencia.sem_fonte))
            numeros = ", ".join(f"“{n}”" for n in conferencia.sem_fonte)
            mensagens.append({"role": "assistant", "content": resposta_final})
            mensagens.append({"role": "user", "content": CORRIGIR_NUMEROS.format(numeros=numeros)})
    except ia.ErroIA as erro:
        log.warning("Modelo indisponível (%s) na conversa %s: %s", erro.tipo, ctx.conversa_id, erro.mensagem)
        consumos.append(_consumo(provedor, None, "TIMEOUT" if erro.tipo == "TIMEOUT" else "ERRO", erro))
        # A primeira resposta tinha número sem fonte e a correção não veio: ela não sai
        auditoria = _auditoria("SUBSTITUIDA", conferencia, primeira, texto_modelo) if primeira else None
        if (pronto := coletor.ultimo_texto()) is not None:
            return Rodada(pronto, coletor.blocos, CONTINGENCIA, ctx.memoria, coletor.execucoes, consumos, auditoria=auditoria)
        ctx.origem = CONTINGENCIA
        executor = _Executor(ctx, assistente.ferramentas, coletor)
        rodada = assistente.regras(texto, ctx, executor)
        return Rodada(
            rodada.texto,
            executor.blocos + rodada.blocos,
            CONTINGENCIA,
            ctx.memoria,
            coletor.execucoes,
            consumos,
            falhou=rodada.falhou,
            auditoria=auditoria,
        )
    if not conferencia.ok:
        # Errou de novo: sai o texto pronto das consultas (determinístico) ou "não consegui confirmar"
        prontos = coletor.textos()
        texto_final = "\n\n".join(prontos) or SEM_CONFIRMACAO[assistente.tipo]
        auditoria = _auditoria("SUBSTITUIDA", conferencia, primeira, texto_modelo) | {"semFonteDepois": conferencia.sem_fonte}
        return Rodada(
            texto_final, coletor.blocos, LLM, ctx.memoria, coletor.execucoes, consumos, falhou=not prontos, auditoria=auditoria
        )
    auditoria = _auditoria("CONFERIDA" if primeira is None else "REESCRITA", conferencia, primeira, texto_modelo)
    if resposta_final.strip():
        return Rodada(resposta_final.strip(), coletor.blocos, LLM, ctx.memoria, coletor.execucoes, consumos, auditoria=auditoria)
    pronto = coletor.ultimo_texto()
    texto_final = pronto or SEM_RESPOSTA[assistente.tipo]
    return Rodada(
        texto_final, coletor.blocos, LLM, ctx.memoria, coletor.execucoes, consumos, falhou=pronto is None, auditoria=auditoria
    )


class _Executor:
    """O executar que as regras usam: o mesmo coletor (auditoria e memória), com a lista completa de
    ferramentas (a permissão é conferida em cada chamada)."""

    def __init__(self, ctx: Contexto, ferramentas: list[Ferramenta], coletor: Coletor | None = None):
        self.coletor = coletor or Coletor(ctx, registro_de(ferramentas))
        self.coletor.registro = registro_de(ferramentas)

    def __call__(self, nome: str, argumentos: dict | None = None) -> Execucao:
        return self.coletor(nome, argumentos)

    @property
    def blocos(self) -> list[dict]:
        return self.coletor.blocos


def responder(
    assistente: Assistente, texto: str, ctx: Contexto, historico: list[tuple[str, str]], contexto_dinamico: Callable[[], str]
) -> Rodada:
    """historico: (papel, texto) das mensagens anteriores, sem a atual."""
    executor = _Executor(ctx, assistente.ferramentas)
    if settings.IA_RESPOSTAS_DIRETAS:
        ctx.origem = REGRAS
        direta = assistente.direta(texto, ctx, executor)
        if direta is not None:
            return Rodada(
                direta.texto,
                executor.blocos + direta.blocos,
                REGRAS,
                ctx.memoria,
                executor.coletor.execucoes,
                falhou=direta.falhou,
            )
    provedor = ia.provedor()
    if provedor is None:
        ctx.origem = REGRAS
        rodada = assistente.regras(texto, ctx, executor)
        return Rodada(
            rodada.texto, executor.blocos + rodada.blocos, REGRAS, ctx.memoria, executor.coletor.execucoes, falhou=rodada.falhou
        )
    ctx.origem = LLM
    return _com_modelo(provedor, assistente, texto, ctx, historico, contexto_dinamico())
