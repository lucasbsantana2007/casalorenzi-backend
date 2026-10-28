"""Respostas do copiloto gerencial sem modelo de linguagem.

Lê na pergunta o assunto (faturamento, mais vendidos, cancelamentos, estoque baixo, parado, por loja,
avarias, transferências, Lupe+, alertas), o período ("hoje", "nesta semana", "em setembro", "últimos 30
dias", "de 01/09 a 15/09"), a marca, a loja e o canal, e chama a mesma ferramenta que o modelo chamaria.
A permissão é conferida pela ferramenta: a regra não decide quem vê o quê.
"""

import re
from datetime import date, timedelta

from src.database.connection import SessionLeitura
from src.entities.periodo import MESES
from src.repositories import cadastro_repository
from src.use_cases.assistente.ferramentas import Contexto
from src.use_cases.assistente.orquestrador import Rodada
from src.use_cases.assistente.regras_cliente import so_cortesia
from src.utils.datas import hoje
from src.utils.texto import normalizar

SUGESTOES = [
    "Quanto faturamos em setembro?",
    "Qual marca vendeu mais no mês passado?",
    "Quais foram os produtos mais vendidos nos últimos 30 dias?",
    "Quantas vendas foram canceladas em setembro?",
    "Qual loja teve o maior faturamento em setembro?",
    "Quais produtos estão com estoque baixo?",
    "Quais produtos estão parados há mais de 60 dias?",
    "Quais lojas concentram mais estoque?",
    "Quais produtos têm avarias?",
    "Que transferências você sugere?",
    "Quantos clientes têm pontos vencendo nos próximos 30 dias?",
]

_DATA = r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?"


def _ano(texto: str | None, padrao: int) -> int:
    if not texto:
        return padrao
    ano = int(texto)
    return ano + 2000 if ano < 100 else ano


def extrair_periodo(texto: str, referencia: date) -> dict:
    """{periodo, de, ate} da pergunta (vazio: o padrão da ferramenta)."""
    if achado := re.search(rf"\b(?:de|entre)?\s*{_DATA}\s*(?:a|ate|e)\s*{_DATA}", texto):
        d1, m1, a1, d2, m2, a2 = achado.groups()
        try:
            inicio = date(_ano(a1, referencia.year), int(m1), int(d1))
            fim = date(_ano(a2 or a1, referencia.year), int(m2), int(d2))
            return {"periodo": "personalizado", "de": inicio.isoformat(), "ate": fim.isoformat()}
        except ValueError:
            pass
    if re.search(r"\bhoje\b", texto):
        return {"periodo": "hoje"}
    if re.search(r"\bontem\b", texto):
        return {"periodo": "ontem"}
    if re.search(r"\bsemana passada\b|\bultima semana\b", texto):
        return {"periodo": "semana_passada"}
    if re.search(r"\b(esta|nesta|essa|nessa|desta|dessa) semana\b|\bsemana atual\b|\bna semana\b|\bda semana\b", texto):
        return {"periodo": "semana_atual"}
    if re.search(r"\bmes passado\b|\bultimo mes\b|\bmes anterior\b", texto):
        return {"periodo": "mes_passado"}
    if achado := re.search(r"\bultimos (\d{1,3}) dias\b", texto):
        dias = int(achado.group(1))
        if dias in (7, 30, 90):
            return {"periodo": f"ultimos_{dias}_dias"}
        dias = max(1, min(dias, 400))
        return {
            "periodo": "personalizado",
            "de": (referencia - timedelta(days=dias - 1)).isoformat(),
            "ate": referencia.isoformat(),
        }
    if re.search(r"\bano passado\b|\bultimo ano\b", texto):
        return {"periodo": "ano_passado"}
    for numero, nome in enumerate(MESES, start=1):
        if achado := re.search(rf"\b{nome}(?:\s+(?:de\s+)?(\d{{4}}))?\b", texto):
            ano = (
                int(achado.group(1))
                if achado.group(1)
                else (referencia.year if numero <= referencia.month else referencia.year - 1)
            )
            inicio = date(ano, numero, 1)
            fim = (inicio.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            return {
                "periodo": "personalizado",
                "de": inicio.isoformat(),
                "ate": min(fim, referencia).isoformat() if fim > referencia >= inicio else fim.isoformat(),
            }
    if achado := re.search(r"\b(?:em|de|no ano de)\s+(20\d{2})\b", texto):
        ano = int(achado.group(1))
        fim = min(date(ano, 12, 31), referencia)
        return {"periodo": "personalizado", "de": date(ano, 1, 1).isoformat(), "ate": fim.isoformat()}
    if re.search(r"\b(este|neste|esse|nesse|deste|desse) ano\b|\bano atual\b|\bno ano\b", texto):
        return {"periodo": "ano_atual"}
    if re.search(r"\b(este|neste|esse|nesse|deste|desse) mes\b|\bmes atual\b|\bno mes\b|\bdo mes\b|\bmensal\b", texto):
        return {"periodo": "mes_atual"}
    return {}


def _marca(texto: str) -> str | None:
    if re.search(r"\bvulto\b", texto) and not re.search(r"\blorenzi\b", texto):
        return "VULTO"
    if re.search(r"\blorenzi\b", texto) and not re.search(r"\bvulto\b", texto):
        return "LORENZI"
    return None


def _canal(texto: str) -> str | None:
    if re.search(r"\b(app|aplicativo)\b", texto):
        return "App"
    if re.search(r"\b(e-?commerce|site|online|internet)\b", texto):
        return "E-commerce"
    if re.search(r"\b(loja fisica|lojas fisicas|presencial|balcao)\b", texto):
        return "Loja física"
    return None


def _loja(texto: str, marca: str | None) -> int | None:
    """Loja ou CD citado pelo nome ('Pinheiros', 'Oscar Freire', 'CD Cajamar')."""
    palavras = set(re.findall(r"[a-z]{4,}", texto)) - {"vulto", "loja", "lojas", "shopping", "casa", "lorenzi"}
    if not palavras:
        return None
    with SessionLeitura() as db:
        candidatas = []
        for loja in cadastro_repository.lojas(db, somente_ativas=True, marca=marca):
            do_nome = set(re.findall(r"[a-z]{4,}", normalizar(loja.nome))) - {"vulto", "shopping"}
            if palavras & do_nome:
                candidatas.append(loja.id)
        return candidatas[0] if len(candidatas) == 1 else None


def _categoria(texto: str) -> str | None:
    with SessionLeitura() as db:
        for nome in cadastro_repository.nomes_categorias(db):
            chave = normalizar(nome)
            if len(chave) >= 4 and re.search(rf"\b{re.escape(chave)}\b", texto):
                return nome
    return None


def _do_resultado(execucao, padrao: str) -> str:
    if execucao.sucesso and execucao.resultado and execucao.resultado.texto:
        return execucao.resultado.texto
    erro = execucao.erro or ""
    if erro.startswith("SEM_PERMISSAO"):
        motivo = erro.split(":", 1)[1].strip()
        return "Seu perfil não tem acesso a essa informação: " + motivo[:1].lower() + motivo[1:]
    if erro.startswith("BANCO_INDISPONIVEL") or erro.startswith("FALHA_INTERNA"):
        return "Não consegui consultar agora. Tente de novo em instantes."
    return erro.split(":", 1)[1].strip() if ":" in erro else (erro or padrao)


def _consultar(executar, nome: str, argumentos: dict) -> Rodada:
    execucao = executar(nome, {k: v for k, v in argumentos.items() if v is not None})
    return Rodada(_do_resultado(execucao, "Não consegui consultar agora."))


def direta(texto: str, ctx: Contexto, executar) -> Rodada | None:
    n = normalizar(texto).strip(" !?.")
    if not n or re.match(
        r"^(oi+|ola+|bom dia|boa tarde|boa noite|e ai|ajuda|help|o que voce faz\??|o que posso perguntar\??)$", n
    ):
        return Rodada(
            "Posso consultar vendas e faturamento, produtos mais vendidos, cancelamentos, estoque baixo e parado, concentração de estoque, avarias, sugestões de transferência, alertas e os números do Lupe+. Escolha uma pergunta ou escreva a sua.",
            [{"tipo": "sugestoes", "itens": SUGESTOES[:6]}],
        )
    # Só agradecimento: "perfeito, e por loja?" traz pergunta e vai para o modelo
    if so_cortesia(texto) is not None:
        return Rodada("Por nada! Se quiser, aprofundo por loja, marca ou período.")
    return None


def responder(texto: str, ctx: Contexto, executar) -> Rodada:
    if (rapida := direta(texto, ctx, executar)) is not None:
        return rapida
    n = normalizar(texto)
    periodo = extrair_periodo(n, hoje())
    marca = _marca(n)
    canal = _canal(n)
    loja_id = _loja(n, marca)
    escopo = {"marca": marca, "loja_id": loja_id}

    if re.search(r"\balertas?\b", n):
        return _consultar(executar, "consultar_alertas", {})
    if re.search(r"\btransfer", n):
        return _consultar(executar, "sugerir_transferencias", {"marca": marca})
    if re.search(r"\bavari|\bdefeito|\bdanificad", n):
        return _consultar(executar, "consultar_avarias", {**escopo, **periodo})
    if re.search(r"\bparad|\bencalhad|\bsem venda|\bsem giro|\bnao vend|\bsem vender|\bgiro baixo", n):
        dias = re.search(r"(\d{1,3})\s*dias", n)
        return _consultar(
            executar, "consultar_estoque_parado", {**escopo, "dias": max(7, min(int(dias.group(1)), 365)) if dias else 30}
        )
    if re.search(
        r"\bconcentra|\bestoque por loja|\bdistribui|\bqual loja tem mais (estoque|pecas)|\blojas? (com|que tem) mais (estoque|pecas)",
        n,
    ):
        return _consultar(executar, "consultar_estoque_por_loja", {"marca": marca})
    if re.search(r"\bmais unidades|\bmaior(es)? estoques?|\bmais pecas em estoque|\bmais (estoque|disponiv)", n):
        return _consultar(executar, "consultar_maiores_estoques", escopo)
    if re.search(
        r"\bestoque baixo|\bacabando|\bruptura|\bzerad|\bsem estoque|\brepor\b|\breposicao|\bem falta|\bfaltando|\bminimo", n
    ):
        return _consultar(executar, "consultar_estoque_baixo", {**escopo, "categoria": _categoria(n)})
    if re.search(
        r"(\blupe\b|vulto\+|vulto mais|\bpontos\b|\bfidelidade\b|\bpassivo\b|\bcategorias? de clientes?\b|\bclientes?\b.*\bcategorias?\b)",
        n,
    ):
        dias = re.search(r"(\d{1,3})\s*dias", n)
        return _consultar(
            executar, "consultar_fidelidade", {"dias_a_vencer": max(1, min(int(dias.group(1)), 180)) if dias else 30}
        )
    if re.search(r"\bcancel", n):
        return _consultar(executar, "consultar_cancelamentos", {**escopo, **periodo})
    quer_marca = re.search(r"\bmarcas?\b", n) and re.search(r"\bvend|\bfatur|\breceita|\bmelhor|\bmais\b", n)
    quer_loja = re.search(r"\blojas?\b", n) and re.search(r"\bvend|\bfatur|\breceita|\bmelhor|\bmaior", n)
    quer_canal = re.search(r"\bcana(l|is)\b|\bpor canal\b", n)
    quer_categoria = re.search(r"\bcategorias?\b", n) and re.search(r"\bvend|\bfatur|\breceita", n)
    if re.search(r"\bmais vendid|\btop\b|\bcampe|\bbest|\branking|\bque mais vend|\bprodutos? (que )?mais", n) and not (
        quer_marca or quer_loja
    ):
        ordenar = "valor" if re.search(r"\bvalor|\bfatur|\breceita|\bdinheiro", n) else "pecas"
        return _consultar(
            executar,
            "consultar_mais_vendidos",
            {**escopo, **periodo, "canal": canal, "categoria": _categoria(n), "ordenar_por": ordenar},
        )
    if (
        re.search(r"\bfatur|\breceita|\bvend|\bticket|\bquanto (ganhamos|entrou|faturou|vendeu)|\bdesempenho|\bresultado", n)
        or quer_marca
        or quer_loja
    ):
        agrupar = (
            "marca" if quer_marca else "loja" if quer_loja else "canal" if quer_canal else "categoria" if quer_categoria else None
        )
        comparar = "periodo_anterior" if re.search(r"\bcompar|\banterior\b|\bcresc|\bvs\b|\bversus\b|\bvariacao", n) else None
        if re.search(r"\bano anterior\b|\bmesmo periodo do ano", n):
            comparar = "ano_anterior"
        if agrupar is None and re.search(r"\bpor dia\b|\bdiari", n):
            agrupar = "dia"
        elif agrupar is None and re.search(r"\bpor semana\b|\bsemanal", n):
            agrupar = "semana"
        elif agrupar is None and re.search(r"\bpor mes\b|\bmes a mes\b", n):
            agrupar = "mes"
        return _consultar(
            executar, "consultar_faturamento", {**escopo, **periodo, "canal": canal, "agrupar_por": agrupar, "comparar": comparar}
        )
    return Rodada(
        "Não entendi a pergunta. Posso consultar vendas e faturamento, mais vendidos, cancelamentos, estoque baixo ou parado, concentração de estoque, avarias, transferências, alertas e Lupe+.",
        [{"tipo": "sugestoes", "itens": SUGESTOES[:6]}],
    )
