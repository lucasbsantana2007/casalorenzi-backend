"""Respostas do assistente do site sem modelo de linguagem.

Entende por regras as perguntas mais comuns e responde com as mesmas ferramentas do modelo. É o modo usado
sem ANTHROPIC_API_KEY e a contingência quando o modelo está fora do ar. A memória curta da conversa (peça
em foco, peças mostradas, última busca, loja em foco e o que o assistente acabou de oferecer) resolve as
continuações: "M", "e na outra loja?", "a segunda", "pode adicionar".
"""

import re

from src.database.connection import SessionLeitura
from src.entities.busca import PedidoBusca, interpretar_busca
from src.use_cases.assistente import catalogo
from src.use_cases.assistente.ferramentas import Contexto
from src.use_cases.assistente.orquestrador import Rodada
from src.use_cases.assistente.prompts import APRESENTACAO, BOAS_VINDAS
from src.utils.texto import normalizar

SAUDACAO = re.compile(r"^(oi+|ola+|opa|bom dia|boa tarde|boa noite|e ai|eai|hey|hello|hi|salve)( (tudo bem|tudo bom|como vai))?$")
AGRADECIMENTO = re.compile(r"^(muito )?(obrigad[oa]|valeu|vlw|brigad[oa]|agradeco|obg|show|perfeito|otimo|blz|beleza)\b")
DESPEDIDA = re.compile(r"^(tchau|ate mais|ate logo|falou|flw|so isso|era isso)\b")
HUMANO = re.compile(
    r"\b(atendente|humano|pessoa de verdade|alguem da (equipe|loja)|falar com (a equipe|alguem|um vendedor|o vendedor|uma pessoa)|"
    r"vendedor|vendedora|suporte|reclamacao|reclamar|sac)\b"
)
# "Quem é você?", "você é um robô?": a Lúcia diz que é uma assistente virtual (decisões 89 e 92)
QUEM_E = re.compile(
    r"\b(qual (e |eh )?(o )?seu nome|como (voce|vc) se chama|quem (e|eh) (voce|vc)|"
    r"(voce|vc) (e|eh) (um |uma )?(robo|bot|humana?|pessoa|ia|inteligencia artificial|de verdade))\b"
)
PONTOS = re.compile(r"(\blupe\b|vulto\+|vulto mais|vultomais|\bpontos?\b|\bfidelidade\b|\bcashback\b)")
SALDO_PONTOS = re.compile(r"\b(quantos|meus|meu|saldo|tenho|vencem|vence|vencer|vencimento|categoria|subir|falta|faltam|nivel)\b")
REGRAS_PONTOS = re.compile(
    r"\b(como (funciona|ganho|ganhar|uso|usar|resgato|resgatar|junto|acumulo)|regras?|quanto vale|vale quanto|"
    r"quantos pontos (eu )?(ganho|ganharia|vou ganhar))\b"
)
PEDIDOS = re.compile(
    r"\b(meu pedido|meus pedidos|minha compra|minhas compras|rastreio|rastrear|rastreamento|status do pedido|chegou|comprei)\b"
)
FRETE = re.compile(r"\b(frete|frete gratis|entrega gratis|prazo de entrega|envio|entregam|entrega)\b")
TROCAS = re.compile(r"\b(troca|trocas|trocar|devolucao|devolucoes|devolver|reembolso)\b")
PAGAMENTO = re.compile(r"\b(pagamento|pagar|parcela|parcelas|parcelar|parcelado|pix|cartao|boleto|credito|debito)\b")
INFO_LOJA = re.compile(
    r"\b(endereco|horario|horarios|abre|abrem|fecha|fecham|funciona|funcionamento|telefone|onde fica|onde ficam|lojas fisicas|loja fisica|unidades)\b"
)
SIM = re.compile(
    r"^(sim|s|quero|quero sim|pode|pode sim|pode ser|isso|isso mesmo|claro|ok|okay|beleza|bora|manda|fechado|"
    r"por favor|sim por favor|com certeza|aham|uhum|yes|perfeito|show)$"
)
NAO = re.compile(r"^(nao|n|agora nao|deixa|deixa pra la|nao quero|nem|nao obrigad[oa]|nao precisa|nao valeu)$")
ADICIONAR = re.compile(
    r"\b(adiciona\w*|coloca\w*|bota\w*|sacola|vou levar|quero comprar|comprar|levar|quero (essa|esse|esta|este|a|o)|gostei|essa mesmo|esse mesmo)\b"
)
OUTRA_LOJA = re.compile(
    r"\b(outra loja|outras lojas|outra unidade|demais lojas|nas lojas|em qual loja|quais lojas|alguma loja|na loja fisica|nas lojas fisicas)\b"
)
NA_LOJA = re.compile(
    r"\b(na loja|nessa loja|no shopping|na unidade|tem em|tem no|tem na|disponivel em|disponivel no|disponivel na|encontro em|encontro no|encontro na)\b"
)
DEMONSTRATIVO = re.compile(r"\b(dessa|desse|essa|esse|esta|este|nessa|nesse|aquela|aquele|daquela|daquele)\b")
ORDINAL = re.compile(
    r"\b(primeir[ao]|segund[ao]|terceir[ao]|quart[ao]|quint[ao]|sext[ao]|ultim[ao])\b|\b(?:opcao|numero|n)\s*(\d)\b"
)
ORDINAIS = {"primeir": 0, "segund": 1, "terceir": 2, "quart": 3, "quint": 4, "sext": 5, "ultim": -1}
PALAVRAS_DO_NOME = {"de", "da", "do", "das", "dos", "e", "com", "a", "o", "par"}

SUGESTOES = ["Camisa azul tamanho M", "Calça preta até R$ 300", "Lojas em São Paulo", "Quantos pontos Lupe+ eu tenho?"]


def _limpo(texto: str) -> str:
    return re.sub(r"[!?.;:]+", " ", normalizar(texto)).strip()


def _sugestoes(itens: list[str] | None = None) -> dict:
    return {"tipo": "sugestoes", "itens": itens or SUGESTOES}


def _do_resultado(execucao, padrao: str) -> str:
    if execucao.sucesso and execucao.resultado and execucao.resultado.texto:
        return execucao.resultado.texto
    return _texto_do_erro(execucao.erro) or padrao


def _texto_do_erro(erro: str | None) -> str | None:
    """O erro das ferramentas tem um código para o modelo; para o cliente, só a explicação."""
    if not erro:
        return None
    if erro.startswith("LOGIN_NECESSARIO"):
        return "Para ver isso, entre na sua conta aqui mesmo, logo abaixo. Assim que você entrar, eu respondo."
    if erro.startswith("BANCO_INDISPONIVEL") or erro.startswith("FALHA_INTERNA"):
        return "Não consegui consultar agora. Tente de novo em instantes."
    return erro.split(":", 1)[1].strip() if ":" in erro else erro


def _peca_citada(texto: str, memoria: dict) -> dict | None:
    """'a segunda', 'a de linho', 'a Camisa Linho Bolso' entre as peças mostradas."""
    mostrados = memoria.get("produtosMostrados") or []
    if not mostrados:
        return None
    if achado := ORDINAL.search(texto):
        if achado.group(1):
            indice = next(v for k, v in ORDINAIS.items() if achado.group(1).startswith(k))
        else:
            indice = int(achado.group(2)) - 1
        if -len(mostrados) <= indice < len(mostrados):
            return mostrados[indice]
    palavras = set(re.findall(r"[a-z0-9]+", texto)) - PALAVRAS_DO_NOME
    notas = []
    for peca in mostrados:
        do_nome = set(re.findall(r"[a-z0-9]+", normalizar(peca["nome"]))) - PALAVRAS_DO_NOME
        notas.append((len(palavras & do_nome), peca))
    maior = max(nota for nota, _ in notas)
    melhores = [peca for nota, peca in notas if nota == maior]
    # A palavra precisa separar uma peça das outras ("camisa" em todas não escolhe nenhuma)
    return melhores[0] if maior > 0 and len(melhores) == 1 else None


def _lojas_citadas(texto: str, marca: str | None) -> list:
    with SessionLeitura() as db:
        return [(loja.id, loja.nome) for loja in catalogo.encontrar_lojas(db, texto, marca=marca)]


def _marca_da_peca(memoria: dict) -> str | None:
    foco = memoria.get("produtoEmFoco")
    if not foco:
        return None
    with SessionLeitura() as db:
        produto = catalogo.produto_ativo(db, foco["id"])
        return produto.marca if produto else None


def direta(texto: str, ctx: Contexto, executar) -> Rodada | None:
    """Mensagens simples que dispensam o modelo (economia): saudação, agradecimento, despedida e pedido de atendente."""
    n = _limpo(texto)
    if not n or SAUDACAO.match(n):
        return Rodada(BOAS_VINDAS["CLIENTE"], [_sugestoes()])
    if AGRADECIMENTO.match(n) and len(n.split()) <= 4:
        return Rodada("Por nada! Se precisar de mais alguma peça ou informação, é só chamar.")
    if DESPEDIDA.match(n):
        return Rodada("Até mais! Quando quiser, estou por aqui.")
    # "Você é uma pessoa de verdade?" é pergunta sobre a Lúcia; "quero falar com uma pessoa" é pedido de atendente
    if QUEM_E.search(n) and "falar" not in n.split():
        return Rodada(APRESENTACAO)
    if HUMANO.search(n):
        execucao = executar("solicitar_atendimento_humano", {"motivo": texto.strip()[:300]})
        return Rodada(_do_resultado(execucao, "Posso chamar alguém da equipe para você."))
    return None


def responder(texto: str, ctx: Contexto, executar) -> Rodada:
    n = _limpo(texto)
    memoria = ctx.memoria
    oferta = memoria.get("oferta")
    foco = memoria.get("produtoEmFoco")

    if (rapida := direta(texto, ctx, executar)) is not None:
        return rapida

    # "Quero esta" num card: a peça já está em foco; mostra tamanhos e disponibilidade (ou prepara a
    # sacola, se o tamanho e a cor já são conhecidos), sem tratar o nome da peça como busca nova
    if ctx.acao and ctx.acao.get("tipo") == "FOCAR_PRODUTO" and foco:
        _cor_unica(memoria)  # peça de uma cor só: a cor já fica escolhida
        return _ver(executar, memoria, foco)

    # Lupe+: as regras do programa ou o saldo do cliente logado
    if PONTOS.search(n) and not PEDIDOS.search(n):
        if REGRAS_PONTOS.search(n) and not re.search(r"\b(quantos|meus|tenho|saldo)\b", n):
            return Rodada(
                _do_resultado(
                    executar("politicas_da_loja", {"assunto": "vulto_mais"}), "Não consegui consultar as regras do Lupe+ agora."
                )
            )
        if REGRAS_PONTOS.search(n) and re.search(r"\b(ganho|ganharia|ganhar)\b", n):
            return Rodada(
                _do_resultado(
                    executar("politicas_da_loja", {"assunto": "vulto_mais"}), "Não consegui consultar as regras do Lupe+ agora."
                )
            )
        if SALDO_PONTOS.search(n) or len(n.split()) <= 3:
            return Rodada(_do_resultado(executar("consultar_meus_pontos", {}), "Não consegui consultar seus pontos agora."))
    if PEDIDOS.search(n):
        return Rodada(_do_resultado(executar("consultar_meus_pedidos", {}), "Não consegui consultar seus pedidos agora."))
    pedido = interpretar_busca(texto)
    pergunta_de_peca = bool(pedido.tipos) or foco is not None

    # Respostas curtas a uma oferta do assistente ("Quer que eu prepare para a sacola?" -> "sim")
    curta = len(n.split()) <= 3
    if curta and SIM.match(n) and not pedido.tipos:
        if oferta == "SACOLA" and foco:
            return _preparar_sacola(executar, memoria)
        if oferta == "CONFIRMAR_SACOLA":
            return Rodada(
                "É só tocar em “Adicionar à sacola”, logo acima, para confirmar. A peça só entra na sacola quando você toca no botão."
            )
        if oferta == "ATENDIMENTO":
            return Rodada("É só tocar em “Falar com a equipe”, logo acima, para eu abrir a solicitação.")
    if curta and NAO.match(n) and oferta in ("SACOLA", "ATENDIMENTO", "CONFIRMAR_SACOLA"):
        memoria["oferta"] = None
        return Rodada("Tudo bem! Posso procurar outra peça ou ajudar com outra coisa?", [_sugestoes()])

    if FRETE.search(n) and not pedido.tipos:
        return Rodada(_do_resultado(executar("politicas_da_loja", {"assunto": "frete"}), "Não consegui consultar o frete agora."))
    if TROCAS.search(n):
        return Rodada(
            _do_resultado(
                executar("politicas_da_loja", {"assunto": "trocas"}), "Não consegui consultar a política de trocas agora."
            )
        )
    if PAGAMENTO.search(n) and not pedido.tipos:
        return Rodada(
            _do_resultado(
                executar("politicas_da_loja", {"assunto": "pagamento"}), "Não consegui consultar as formas de pagamento agora."
            )
        )

    # Escolha entre as peças mostradas ("a segunda", "a de linho"), só em mensagens curtas
    if len(n.split()) <= 6 and (citada := _peca_citada(n, memoria)):
        memoria["produtoEmFoco"] = citada
        foco = citada
        if not pedido.tipos and not pedido.cor:
            return _ver(executar, memoria, foco)

    # Disponibilidade numa loja: "tem na loja do shopping?", "e na outra loja?"
    outra = bool(OUTRA_LOJA.search(n))
    if outra or NA_LOJA.search(n) or (not INFO_LOJA.search(n) and _cita_loja(n, memoria)):
        if foco and not pedido.tipos:
            return _na_loja(executar, memoria, n, outra)
        if pedido.tipos or memoria.get("busca"):
            return _buscar_na_loja(executar, memoria, pedido, n)

    if INFO_LOJA.search(n) or re.search(r"\b(lojas?)\b", n) and not pergunta_de_peca:
        return Rodada(
            _do_resultado(
                executar("informacoes_lojas", {"busca": texto[:80]} if _cita_loja(n, memoria) else {}),
                "Não consegui consultar as lojas agora.",
            )
        )

    # "Gostei dessa camisa": o tipo só nomeia a peça já mostrada (não é uma busca nova)
    referencia = bool(DEMONSTRATIVO.search(n)) and (foco is not None or memoria.get("produtosMostrados"))
    # Quer a peça em foco: mostra detalhes/tamanhos ou prepara a sacola
    if ADICIONAR.search(n) and (not pedido.tipos or referencia):
        if foco is None:
            mostrados = memoria.get("produtosMostrados") or []
            if len(mostrados) > 1:
                memoria["oferta"] = "ESCOLHA_PRODUTO"
                nomes = "; ".join(f"{i}) {p['nome']}" for i, p in enumerate(mostrados, 1))
                return Rodada(f"Qual delas? {nomes}. Pode tocar em “Quero esta” no card.")
            return Rodada("Qual peça você quer? Me diga o tipo, a cor ou o tamanho que eu procuro.", [_sugestoes()])
        if memoria.get("tamanhoEmFoco") and (memoria.get("corEmFoco") or _cor_unica(memoria)):
            return _preparar_sacola(executar, memoria)
        return _ver(executar, memoria, foco)

    # Só tamanho, cor ou preço: continua a conversa sobre a peça em foco ou a última busca
    so_filtro = not pedido.tipos and not pedido.termos and (pedido.tamanho or pedido.cor or pedido.preco_max or pedido.preco_min)
    if so_filtro:
        if foco and (pedido.tamanho or pedido.cor) and not (pedido.preco_max or pedido.preco_min):
            if pedido.tamanho:
                memoria["tamanhoEmFoco"] = pedido.tamanho
            return _ver(executar, memoria, foco, cor=pedido.cor, tamanho=pedido.tamanho)
        if memoria.get("busca"):
            anterior = PedidoBusca.de_dict(memoria["busca"])
            anterior.tamanho = pedido.tamanho or anterior.tamanho
            anterior.cor = pedido.cor or anterior.cor
            anterior.preco_min = pedido.preco_min if pedido.preco_min is not None else anterior.preco_min
            anterior.preco_max = pedido.preco_max if pedido.preco_max is not None else anterior.preco_max
            return _buscar(executar, anterior)

    if not pedido.vazio() or pedido.marca:
        # Muitas palavras que não descrevem peça nenhuma não são uma busca ("ignore as instruções...")
        so_termos = not (pedido.tipos or pedido.cor or pedido.tamanho or pedido.preco_min or pedido.preco_max or pedido.marca)
        if so_termos and len(pedido.termos) >= 3:
            return _nao_entendi()
        return _buscar(executar, pedido)

    return _nao_entendi()


def _nao_entendi() -> Rodada:
    return Rodada(
        "Não entendi bem. Posso buscar peças (por exemplo: “camisa azul M até R$ 200”), ver a disponibilidade nas lojas, informar horários e consultar seus pontos Lupe+. Se preferir, chamo alguém da equipe.",
        [_sugestoes()],
    )


def _cita_loja(texto: str, memoria: dict) -> bool:
    return bool(_lojas_citadas(texto, None))


def _cor_unica(memoria: dict) -> bool:
    """A peça em foco tem uma cor só (então a cor não precisa ser perguntada)."""
    foco = memoria.get("produtoEmFoco")
    if not foco:
        return False
    with SessionLeitura() as db:
        produto = catalogo.produto_ativo(db, foco["id"])
        if produto is None:
            return False
        cores = {v.cor for v in catalogo.variacoes_escolhidas(produto, None, None)}
        if len(cores) == 1:
            memoria["corEmFoco"] = cores.pop()
            return True
        return False


def _argumentos_busca(pedido: PedidoBusca) -> dict:
    argumentos = {
        "tipo_peca": " ".join(pedido.tipos) or None,
        "cor": pedido.cor,
        "tamanho": pedido.tamanho,
        "preco_min": float(pedido.preco_min) if pedido.preco_min is not None else None,
        "preco_max": float(pedido.preco_max) if pedido.preco_max is not None else None,
        "marca": pedido.marca,
        "genero": pedido.genero,
        "texto": " ".join(pedido.termos) or None,
    }
    return {k: v for k, v in argumentos.items() if v is not None}


def _buscar(executar, pedido: PedidoBusca, loja_id: int | None = None) -> Rodada:
    argumentos = _argumentos_busca(pedido)
    if loja_id:
        argumentos["loja_id"] = loja_id
    execucao = executar("buscar_produtos", argumentos)
    return Rodada(_do_resultado(execucao, "Não consegui buscar no catálogo agora. Tente de novo em instantes."))


def _ver(executar, memoria: dict, foco: dict, cor: str | None = None, tamanho: str | None = None) -> Rodada:
    argumentos = {"produto_id": foco["id"]}
    if cor or memoria.get("corEmFoco"):
        argumentos["cor"] = cor or memoria.get("corEmFoco")
    if tamanho or memoria.get("tamanhoEmFoco"):
        argumentos["tamanho"] = tamanho or memoria.get("tamanhoEmFoco")
    execucao = executar("ver_produto", argumentos)
    return Rodada(_do_resultado(execucao, "Não consegui consultar essa peça agora."))


def _preparar_sacola(executar, memoria: dict) -> Rodada:
    foco = memoria["produtoEmFoco"]
    argumentos = {"produto_id": foco["id"], "tamanho": memoria.get("tamanhoEmFoco") or ""}
    if memoria.get("corEmFoco"):
        argumentos["cor"] = memoria["corEmFoco"]
    if not argumentos["tamanho"]:
        return _ver(executar, memoria, foco)
    execucao = executar("preparar_sacola", argumentos)
    return Rodada(_do_resultado(execucao, "Não consegui preparar a peça agora."))


def _na_loja(executar, memoria: dict, texto: str, outra: bool) -> Rodada:
    """Disponibilidade da peça em foco nas lojas citadas (ou nas outras, com 'outra loja')."""
    foco = memoria["produtoEmFoco"]
    marca = _marca_da_peca(memoria)
    citadas = [] if outra else _lojas_citadas(texto, marca)
    execucao = executar(
        "ver_produto",
        {
            k: v
            for k, v in {
                "produto_id": foco["id"],
                "cor": memoria.get("corEmFoco"),
                "tamanho": memoria.get("tamanhoEmFoco"),
            }.items()
            if v
        },
    )
    if not execucao.sucesso or execucao.resultado is None:
        return Rodada(_texto_do_erro(execucao.erro) or "Não consegui consultar essa peça agora.")
    lojas = execucao.resultado.dados["lojas"]
    em_foco = memoria.get("lojaEmFocoNome")
    if citadas:
        nomes = {nome for _, nome in citadas}
        lojas = [loja for loja in lojas if loja["loja"] in nomes]
        if len(citadas) == 1:
            memoria["lojaEmFoco"], memoria["lojaEmFocoNome"] = citadas[0]
    elif outra and em_foco:
        lojas = [loja for loja in lojas if loja["loja"] != em_foco]
    if not lojas:
        return Rodada(
            f"A {foco['nome']} não é vendida nessa loja (cada marca tem as suas lojas). Abaixo está a disponibilidade nas lojas da marca dela."
        )
    escolha = ", ".join(
        x for x in (memoria.get("corEmFoco"), memoria.get("tamanhoEmFoco") and f"tamanho {memoria['tamanhoEmFoco']}") if x
    )
    peca = f"{foco['nome']}{f' ({escolha})' if escolha else ''}"
    partes = []
    for loja in lojas:
        if loja["situacao"] == "indisponível":
            partes.append(f"{loja['loja']}: indisponível")
        else:
            tamanhos = (
                f" (tamanhos {', '.join(loja['tamanhos'])})" if loja["tamanhos"] and not memoria.get("tamanhoEmFoco") else ""
            )
            partes.append(f"{loja['loja']}: {loja['situacao']}{tamanhos}")
    texto_resposta = f"{peca} — " + "; ".join(partes) + "."
    if memoria.get("oferta") == "SACOLA":
        texto_resposta += " Se preferir comprar pelo site, posso preparar para a sacola."
    return Rodada(texto_resposta)


def _buscar_na_loja(executar, memoria: dict, pedido: PedidoBusca, texto: str) -> Rodada:
    """Busca (a pedida ou a última) só com o que está disponível na loja citada."""
    base = pedido if pedido.tipos else PedidoBusca.de_dict(memoria.get("busca"))
    citadas = _lojas_citadas(texto, base.marca)
    if len(citadas) != 1:
        if not citadas:
            return Rodada("Qual loja? Temos lojas em São Paulo, Rio de Janeiro, Brasília, Curitiba e Belo Horizonte.")
        return Rodada(f"Qual delas: {', '.join(nome for _, nome in citadas)}?")
    loja_id, nome = citadas[0]
    memoria["lojaEmFoco"], memoria["lojaEmFocoNome"] = loja_id, nome
    return _buscar(executar, base, loja_id)
