"""Duas falhas seguidas → pessoa (decisão 102).

A dor (atendimento, no kickoff): o cliente repete a pergunta, o robô repete que não entendeu, e o cliente desiste ou
chega irritado no atendimento humano. Regra: quando a Lúcia falha duas vezes seguidas na mesma conversa, ela mesma
oferece passar para alguém da equipe, com o resumo, sem o cliente precisar pedir.

Sinais de falha em cada mensagem:
- da Lúcia: não entendeu, não conseguiu responder ou não confirmou um número (Rodada.falhou), ou disse ao cliente,
  com as palavras do modelo, que não entendeu ou não tem a informação;
- do cliente: disse que a resposta anterior não serviu ("não foi isso que eu perguntei", "você não entendeu") ou
  mandou de novo a mesma pergunta (as mesmas palavras; "camisa M" depois de "camisa G" é outra pergunta).
Mensagem sem sinal zera a contagem. Na segunda falha seguida, a resposta ganha os botões de falar com a equipe (os
mesmos de solicitar_atendimento_humano) e a contagem recomeça. Se a resposta já tem os botões, não oferece de
novo; se a conversa já foi encaminhada, lembra o protocolo em vez de abrir outro.
"""

import re

from src.use_cases.assistente.ferramentas import Contexto
from src.use_cases.assistente.orquestrador import Rodada
from src.utils.texto import normalizar

FALHAS_PARA_OFERECER = 2
OFERTA = "Parece que eu não estou conseguindo te ajudar com isso, e não quero te fazer repetir."

# O cliente dizendo que a resposta não serviu (frases inteiras: um "não" sozinho não conta)
FRUSTRACAO = re.compile(
    r"\b(nao (foi|e|era) (isso|bem isso|o que (eu )?(perguntei|pedi|quis dizer|falei))|nao entendeu|"
    r"(voce|vc) nao (entende|entendeu|esta entendendo|ta entendendo)|nao (me )?(ajudou|ajuda|resolveu|resolve)|"
    r"nao adianta|ja (te )?(falei|disse|expliquei|perguntei)|de novo isso|continua errad[oa]|(esta|ta) errad[oa]|"
    r"resposta errada|nada a ver|inutil|robo burro|que saco)\b"
)
# A Lúcia dizendo, com as palavras do modelo, que não conseguiu. O modelo varia a frase ("continuo sem entender",
# "me conta em outras palavras"): cada variação vista na avaliação com o Claude entra aqui e no teste
NAO_CONSEGUIU = re.compile(
    r"\b(nao entendi|nao consegui entender|(continuo |ainda |fiquei )?sem entender|nao (estou|to) entendendo|"
    r"nao compreendi|nao ficou claro|nao reconheci|(pode|poderia|consegue) (reformular|reescrever|explicar melhor)|"
    r"em outras palavras|mensagem (parece |ficou |veio )?(incompleta|confusa|cortada)|"
    r"nao consegui (responder|confirmar|consultar)|nao tenho (essa|esta) informacao|"
    r"nao tenho como (saber|ver|consultar|responder))\b"
)
BLOCOS_DE_ATENDIMENTO = {"acao_atendimento", "atendimento_aberto"}
# Palavras que não mudam a pergunta ("o frete pra Manaus" e "frete para Manaus?" são a mesma)
_VAZIAS = set(
    "o a os as um uma de da do das dos e pra para pro por com em no na nos nas que eu me mim voce vc ai la so entao ne ta eh "
    "qual quais quanto quanta quantos quantas como onde tem ter sobre isso isto ja".split()
)


def _palavras(texto: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalizar(texto))) - _VAZIAS


def repetiu(texto: str, anterior: str | None) -> bool:
    """A mesma pergunta de novo: as mesmas palavras (pelo menos duas), tirando as que não mudam o sentido."""
    if not anterior:
        return False
    agora, antes = _palavras(texto), _palavras(anterior)
    if len(agora) < 2 or len(antes) < 2:
        return False
    return len(agora & antes) / len(agora | antes) >= 0.8


def sinal_do_cliente(texto: str, historico: list[tuple[str, str]]) -> str | None:
    if FRUSTRACAO.search(normalizar(texto)):
        return "FRUSTRACAO"
    anterior = next((t for papel, t in reversed(historico) if papel == "USUARIO"), None)
    return "REPETICAO" if repetiu(texto, anterior) else None


def lucia_falhou(rodada: Rodada) -> bool:
    return rodada.falhou or bool(NAO_CONSEGUIU.search(normalizar(rodada.texto)))


def aplicar(rodada: Rodada, texto: str, ctx: Contexto, historico: list[tuple[str, str]], executar) -> Rodada:
    """Conta as falhas seguidas da conversa e, na segunda, oferece a equipe (passo final do assistente do site)."""
    falhou = lucia_falhou(rodada)
    sinal = sinal_do_cliente(texto, historico)
    sinais = int(falhou) + int(sinal is not None)
    falhas = int(ctx.memoria.get("falhasSeguidas") or 0) + sinais if sinais else 0
    auditoria = dict(rodada.auditoria or {})
    if falhou:
        auditoria["falhou"] = True
    if sinal:
        auditoria["sinalDoCliente"] = sinal

    if any(bloco.get("tipo") in BLOCOS_DE_ATENDIMENTO for bloco in rodada.blocos):
        falhas = 0  # a resposta já oferece a equipe (pedido de atendente, cliente irritado...)
    elif falhas >= FALHAS_PARA_OFERECER:
        falhas = 0
        auditoria["ofereceuPessoa"] = True
        if ctx.atendimento_protocolo:
            complemento = (
                f"A sua solicitação {ctx.atendimento_protocolo} já está com a nossa equipe, que recebeu o resumo desta "
                "conversa e continua o atendimento por lá."
            )
            blocos = []
        else:
            motivo = f"A Lúcia não conseguiu resolver depois de duas tentativas. Última mensagem: {texto.strip()}"
            execucao = executar("solicitar_atendimento_humano", {"motivo": motivo[:300]})
            resultado = execucao.resultado if execucao.sucesso else None
            complemento = resultado.texto if resultado and resultado.texto else "Posso chamar alguém da equipe para você."
            blocos = resultado.blocos if resultado else []
        oferta = f"{OFERTA} {complemento}"
        # A resposta que falhou ("não entendi") não ajuda: sai só a oferta. A que respondeu fica, com a oferta depois
        rodada.texto = oferta if rodada.falhou else f"{rodada.texto}\n\n{oferta}"
        rodada.blocos = [*rodada.blocos, *blocos]

    ctx.memoria["falhasSeguidas"] = falhas or None
    rodada.memoria = ctx.memoria
    rodada.auditoria = auditoria or None
    return rodada
