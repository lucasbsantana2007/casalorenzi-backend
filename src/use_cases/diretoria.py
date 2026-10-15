"""Os números da diretoria sobre a Vulto: três respostas, cada uma com a explicação, as decisões aplicadas e
a margem de erro, em JSON e em CSV (para o time montar a apresentação).

1. Faturamento de jan/2025 a set/2026 por mês, loja e canal, sem frete (como o financeiro da Casa Lorenzi,
   aprovado), e a ponte "relatório do sistema da Vulto → nosso número", passo a passo.
2. Estoque em 01/10/2026 por loja/CD e por produto: o que foi contado, o que foi reconstruído e o que é
   estimado.
3. Passivo do Vulto+ em 01/10/2026, em pontos e R$, na faixa de cenários.
"""

import csv
import io
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from src.entities import fidelidade as regra
from src.entities.marca import VULTO
from src.migracao_vulto import lojas as lojas_vulto
from src.migracao_vulto.estoque import CONTAGENS
from src.migracao_vulto.vendas import ORIGEM_VENDAS
from src.repositories import diretoria_repository
from src.use_cases import estoque, faturamento, fidelidade
from src.utils.datas import agora, inicio_do_dia, ler_data
from src.utils.erros import DadosInvalidos

DE, ATE = faturamento.INICIO_PADRAO, faturamento.FIM_PADRAO
DATA_ESTOQUE = regra.DATA_VIRADA

PASSOS = {
    "centavos": "Centavos do app lidos como reais",
    "cancelados": "Cancelados e estornos",
    "aguardando": "Aguardando pagamento",
    "trocas": "Trocas",
    "devolucoes": "Devoluções",
    "testes": "Vendas de teste",
    "duplicatas": "Duplicatas do app",
    "batel": "Batel março (planilha manual)",
    "fuso": "Fuso horário",
    "outros": "Outros (não explicado)",
}
EXPLICACAO_FRETE = "Frete cobrado do cliente: repasse à transportadora, fora do faturamento (como na Casa Lorenzi)."

DECISOES_FATURAMENTO = [
    "Receita = vendas não canceladas e com pagamento que não está só pendente, pelo valor sem frete (como o "
    "financeiro da Casa Lorenzi), menos as devoluções na data em que aconteceram.",
    "Total e itens gravados em centavos pelo app foram detectados pelo preço do catálogo e convertidos.",
    "Venda com o status vazio conta como paga (o PDV deixava em branco o que era pago).",
    "Troca lançada como venda nova não é receita: a venda original já contou.",
    "Batel em março (PDV fora do ar de 02 a 22/03/2026): vale a planilha manual, menos o que foi relançado no "
    "sistema, que volta para a data real.",
    "Datas em UTC (site, app e o PDV do Eldorado depois da troca do servidor em fev/26) foram convertidas para Brasília.",
    "Vendas de teste da TI/QA e duplicatas do app ficam de fora.",
]
DECISOES_ESTOQUE = [
    "A tabela de estoque da Vulto (sem histórico, com saldos negativos, e o CD inflado porque as vendas online "
    "baixavam das 'lojas' 5 e 6) não entra: o estoque é reconstruído movimento a movimento.",
    "Entradas: as notas fiscais de fornecedor. Transferências anotadas pelos dois lados contam uma vez.",
    "Vendas online baixam do CD; o ship from store, de Pinheiros. Cancelados e pagamento pendente não baixam.",
    "A contagem de set/26 é a âncora: no dia da contagem, o saldo é o contado (o CD usa o saldo do WMS).",
    "A abertura em 01/01/2025, desconhecida, é a menor que deixa o histórico sem saldo negativo.",
]
DECISOES_PASSIVO = [
    "Saldo inicial: a coluna Pontos da planilha, congelada em 01/01/2025; depois, os movimentos do sistema "
    "corrigidos (bug do app v3.4, créditos antes do pagamento, vendas canceladas sem estorno).",
    "Categoria pela regra (pontos do ano): Bronze até 1.999, Prata até 4.999, Ouro 5.000+.",
    "Validade de 12 meses (Ouro 18, o combinado), os pontos mais antigos saem primeiro; saldo nunca negativo.",
    "Valor vigente do ponto: R$ 0,05 (desde mar/2025). O sistema seguiu dando R$ 0,10 nos resgates.",
]


def _reais(valor) -> float:
    return float(Decimal(str(valor or 0)).quantize(Decimal("0.01")))


def _moeda(valor) -> str:
    texto = f"{Decimal(str(valor)).quantize(Decimal('0.01')):,.2f}"
    return "R$ " + texto.replace(",", "_").replace(".", ",").replace("_", ".")


def _milhar(numero: int) -> str:
    return f"{numero:,}".replace(",", ".")


# ---------- 1. Faturamento ----------


def _somar(linhas: list[dict], chave: str) -> list[dict]:
    soma: dict[str, dict] = defaultdict(lambda: {"pedidos": 0, "semFrete": Decimal(0)})
    for linha in linhas:
        soma[linha[chave]]["pedidos"] += linha["pedidos"]
        soma[linha[chave]]["semFrete"] += Decimal(str(linha["liquidoSemFrete"]))
    return [{chave: k, "pedidos": v["pedidos"], "semFrete": _reais(v["semFrete"])} for k, v in sorted(soma.items())]


def _ponte(bloco: dict) -> list[dict]:
    """Sistema da Vulto → nosso número sem frete. A soma dos passos fecha (o teste confere)."""
    passos = [
        {"passo": "Relatório do sistema da Vulto", "chave": "sistemaVulto", "valor": bloco["sistemaVulto"], "explicacao": ""}
    ]
    for chave, nome in PASSOS.items():
        passos.append({"passo": nome, "chave": chave, "valor": bloco["ajustes"][chave], "explicacao": faturamento.AJUSTES[chave]})
    passos.append({"passo": "Frete", "chave": "frete", "valor": -bloco["frete"], "explicacao": EXPLICACAO_FRETE})
    passos.append(
        {"passo": "Nosso faturamento (sem frete)", "chave": "nossoSemFrete", "valor": bloco["nossoSemFrete"], "explicacao": ""}
    )
    return passos


def resposta_faturamento(db: Session) -> dict:
    receita = faturamento.faturamento(db, DE, ATE, VULTO)
    comparativo = faturamento.comparativo_vulto(db, DE, ATE)
    total = receita["total"]
    vazio_n, vazio_valor = diretoria_repository.vendas_da_ocorrencia(db, "STATUS_VAZIO_COMO_PAGO", ORIGEM_VENDAS)
    batel_n, batel_valor = diretoria_repository.ocorrencia(db, "vendas", "BATEL_VENDA_MANUAL")
    desde, ate = inicio_do_dia(ler_data(DE)), inicio_do_dia(ler_data(ATE) + timedelta(days=1))
    pendentes_n, pendentes_valor = diretoria_repository.aguardando_pagamento(db, desde, ate, VULTO)
    nosso = Decimal(str(total["liquidoSemFrete"]))
    minimo = nosso - vazio_valor - batel_valor
    maximo = nosso + pendentes_valor
    return {
        "pergunta": "Quanto a Vulto faturou de jan/2025 a set/2026, por mês, loja e canal, e por que o número é diferente "
        "do relatório do sistema da Vulto?",
        "resposta": f"{_moeda(nosso)} sem frete ({_moeda(total['liquidoComFrete'])} com frete), em {_milhar(total['pedidos'])} "
        f"vendas. O relatório do sistema da Vulto dizia {_moeda(comparativo['total']['sistemaVulto'])}: a diferença é quase toda "
        "o valor em centavos do app somado como reais.",
        "periodo": {"de": receita["de"], "ate": receita["ate"]},
        "total": {
            "semFrete": _reais(nosso),
            "frete": total["frete"],
            "comFrete": total["liquidoComFrete"],
            "devolucoes": total["devolucoes"],
            "pedidos": total["pedidos"],
        },
        "porMes": _somar(receita["linhas"], "mes"),
        "porLoja": _somar(receita["linhas"], "loja"),
        "porCanal": _somar(receita["linhas"], "canal"),
        "linhas": receita["linhas"],
        "ponte": _ponte(comparativo["total"]),
        "ponteMensal": [{"mes": mes["mes"], "passos": _ponte(mes)} for mes in comparativo["meses"]],
        "decisoes": DECISOES_FATURAMENTO,
        "margem": {
            "itens": [
                {
                    "item": "Status vazio lido como pago",
                    "registros": vazio_n,
                    "valor": _reais(vazio_valor),
                    "efeito": "Se alguma dessas vendas não foi paga, o faturamento é menor.",
                },
                {
                    "item": "Batel março pela planilha manual",
                    "registros": batel_n,
                    "valor": _reais(batel_valor),
                    "efeito": "Anotada à mão com o PDV fora do ar: se algo foi anotado errado, o faturamento é menor.",
                },
                {
                    "item": "Vendas aguardando pagamento",
                    "registros": pendentes_n,
                    "valor": _reais(pendentes_valor),
                    "efeito": "Fora do número; se forem pagas, o faturamento é maior.",
                },
            ],  # fmt: skip
            "minimo": _reais(minimo),
            "maximo": _reais(maximo),
            "explicacao": "O que não se explica na ponte ('outros') é zero. A faixa vai do número sem as vendas de status "
            "vazio e da planilha da Batel ao número com as vendas que aguardam pagamento.",
        },
    }


# ---------- 2. Estoque ----------


def resposta_estoque(db: Session) -> dict:
    itens = estoque.posicao_em_data(db, DATA_ESTOQUE.isoformat(), marca=VULTO)
    composicao = diretoria_repository.composicao_do_estoque(db, VULTO, inicio_do_dia(DATA_ESTOQUE + timedelta(days=1)))
    contagem_por_loja = {}
    for id_legado, (_, dia, estimada) in CONTAGENS.items():
        loja = lojas_vulto.loja_da_vulto(db, id_legado)
        if loja is not None:
            contagem_por_loja[loja.id] = {"data": dia.isoformat(), "dataEstimada": estimada}

    lojas: dict[int, dict] = {}
    produtos: dict[int, dict] = {}
    negativos = 0
    for item, quantidade in itens:
        loja = item.loja
        if loja.id not in lojas:
            lojas[loja.id] = {"lojaId": loja.id, "loja": loja.nome, "tipo": loja.tipo, "itens": 0, "saldo": 0}
        lojas[loja.id]["saldo"] += quantidade
        lojas[loja.id]["itens"] += quantidade != 0
        negativos += quantidade < 0
        produto = item.variacao.produto
        linha = produtos.setdefault(
            produto.id,
            {"produtoId": produto.id, "produto": produto.nome, "categoria": produto.categoria.nome, "colecao": produto.colecao,
             "porLoja": defaultdict(int), "total": 0},
        )  # fmt: skip
        linha["porLoja"][loja.nome] += quantidade
        linha["total"] += quantidade
    parcelas = ("abertura", "entradas", "transferencias", "vendas", "devolucoes", "ajusteContagem", "outros")
    for loja_id, dados in lojas.items():
        dados.update({parcela: composicao.get(loja_id, {}).get(parcela, 0) for parcela in parcelas})
        dados["contagem"] = contagem_por_loja.get(loja_id)
    total = sum(dados["saldo"] for dados in lojas.values())

    savassi_n, savassi_pecas = diretoria_repository.ocorrencia(db, "estoque", "SAVASSI_CONTAGEM_POR_MODELO")
    batel_n, _ = diretoria_repository.ocorrencia(db, "estoque", "BATEL_CONTAGEM_INCOMPLETA")
    ilegiveis_n, ilegiveis = diretoria_repository.ocorrencia(db, "estoque", "CONTAGEM_SKU_ILEGIVEL")
    _, abertura = diretoria_repository.ocorrencia(db, "estoque", "ABERTURA_ESTIMADA")
    _, legado = diretoria_repository.ocorrencia(db, "estoque", "ESTOQUE_DO_LEGADO_SO_COMPARACAO")
    sem_data = [lojas[i]["loja"] for i, c in contagem_por_loja.items() if c["dataEstimada"] and i in lojas]
    return {
        "pergunta": "Quanto estoque a Vulto tem em 01/10/2026, por loja/CD e por produto, e quanto disso é contado e quanto "
        "é estimado?",
        "resposta": f"{_milhar(total)} peças em {_milhar(sum(d['itens'] for d in lojas.values()))} itens com saldo "
        "(loja × peça). "
        "O saldo em 01/10/2026 é a contagem de set/26 mais os movimentos depois dela; o sistema da Vulto dizia "
        f"{_milhar(total - int(legado))} peças.",
        "data": DATA_ESTOQUE.isoformat(),
        "total": total,
        "porLoja": sorted(lojas.values(), key=lambda d: d["loja"]),
        "porProduto": [
            {**p, "porLoja": dict(sorted(p["porLoja"].items()))}
            for p in sorted(produtos.values(), key=lambda p: (-p["total"], p["produto"]))
        ],
        "decisoes": DECISOES_ESTOQUE,
        "estimado": [
            f"Data da contagem de {', '.join(sem_data)}: a planilha não diz; usamos 30/09/2026.",
            f"Savassi contou por modelo ({int(savassi_pecas)} peças em {savassi_n} modelos): o total da loja é exato; a cor "
            "e o tamanho foram rateados.",
            f"Abertura em 01/01/2025 ({_milhar(int(abertura))} peças): a menor que deixa o histórico sem negativo. Afeta a "
            "posição antes da contagem (que é um piso), não o saldo de 01/10/2026.",
        ],
        "margem": {
            "itens": [
                {
                    "item": "Contagem da Batel incompleta ('faltou contar provador', 'recontar')",
                    "registros": batel_n,
                    "pecas": None,
                    "efeito": "O contado pode estar abaixo do real; a quantidade que faltou não foi anotada.",
                },
                {
                    "item": "SKU ilegível na contagem",
                    "registros": ilegiveis_n,
                    "pecas": -int(ilegiveis),
                    "efeito": "Peças contadas que não dá para saber quais são: ficaram de fora.",
                },
                {
                    "item": "Itens negativos depois da contagem",
                    "registros": negativos,
                    "pecas": None,
                    "efeito": "Venderam mais do que o contado: contagem ou venda errada.",
                },
            ],  # fmt: skip
            "minimo": total,
            "maximo": total - int(ilegiveis),
            "explicacao": "O total da contagem é exato onde a contagem é. A faixa soma as peças de SKU ilegível; a Batel "
            "pode ter mais peças (provador), sem número anotado.",
        },
    }


# ---------- 3. Passivo ----------


def resposta_passivo(db: Session) -> dict:
    passivo = fidelidade.passivo(db, None)
    faixa = passivo["faixa"]
    return {
        "pergunta": "Quanto a Vulto deve em pontos do Vulto+ em 01/10/2026, em pontos e em reais?",
        "resposta": f"{_milhar(faixa['vigente']['pontos'])} pontos = {_moeda(faixa['vigente']['valor'])} pela regra "
        f"vigente, numa faixa de {_moeda(faixa['minimo']['valor'])} a {_moeda(faixa['maximo']['valor'])}.",
        **passivo,
        "decisoes": DECISOES_PASSIVO,
        "margem": {
            "minimo": faixa["minimo"],
            "maximo": faixa["maximo"],
            "explicacao": "A faixa combina a validade do Ouro (12 ou 18 meses), o valor do ponto (R$ 0,05 da regra ou R$ 0,10 "
            "que o sistema dava), os resgates anotados sem CPF (no mínimo) e o que o sistema nunca aplicou (dobro do online "
            "e bônus Ouro, no máximo).",
        },
    }


def numeros(db: Session) -> dict:
    return {
        "geradoEm": agora().isoformat(timespec="seconds"),
        "faturamento": resposta_faturamento(db),
        "estoque": resposta_estoque(db),
        "passivo": resposta_passivo(db),
    }


# ---------- CSV (Excel em português: ";", vírgula decimal, UTF-8 com BOM) ----------

SECOES_CSV = ("faturamento", "ponte", "estoque-lojas", "estoque-produtos", "passivo")


def _celula(valor) -> str:
    if isinstance(valor, bool) or valor is None:
        return "" if valor is None else ("sim" if valor else "não")
    if isinstance(valor, float | Decimal):
        return f"{Decimal(str(valor)).quantize(Decimal('0.01'))}".replace(".", ",")
    return str(valor)


def _tabela(secao: str, dados: dict) -> tuple[list[str], list[list]]:
    if secao == "faturamento":
        cabecalho = ["mes", "loja", "canal", "pedidos", "sem_frete", "frete", "com_frete", "devolucoes", "liquido_sem_frete"]
        linhas = [
            [li["mes"], li["loja"], li["canal"], li["pedidos"], li["semFrete"], li["frete"], li["comFrete"], li["devolucoes"],
             li["liquidoSemFrete"]]
            for li in dados["faturamento"]["linhas"]
        ]  # fmt: skip
        return cabecalho, linhas
    if secao == "ponte":
        cabecalho = ["mes", "passo", "valor", "explicacao"]
        linhas = [["total", p["passo"], p["valor"], p["explicacao"]] for p in dados["faturamento"]["ponte"]]
        for mes in dados["faturamento"]["ponteMensal"]:
            linhas += [[mes["mes"], p["passo"], p["valor"], p["explicacao"]] for p in mes["passos"]]
        return cabecalho, linhas
    if secao == "estoque-lojas":
        campos = [
            "loja",
            "tipo",
            "abertura",
            "entradas",
            "transferencias",
            "vendas",
            "devolucoes",
            "ajusteContagem",
            "outros",
            "saldo",
        ]
        linhas = [
            [*(loja[c] for c in campos), (loja["contagem"] or {}).get("data"), (loja["contagem"] or {}).get("dataEstimada")]
            for loja in dados["estoque"]["porLoja"]
        ]
        return [*campos, "data_contagem", "data_estimada"], linhas
    if secao == "estoque-produtos":
        lojas = sorted({nome for p in dados["estoque"]["porProduto"] for nome in p["porLoja"]})
        linhas = [
            [p["produto"], p["categoria"], p["colecao"], *(p["porLoja"].get(nome, 0) for nome in lojas), p["total"]]
            for p in dados["estoque"]["porProduto"]
        ]
        return ["produto", "categoria", "colecao", *lojas, "total"], linhas
    if secao == "passivo":
        passivo = dados["passivo"]
        linhas = []
        for c in passivo["cenarios"]:
            gravado = "gravado nas contas" if c["gravado"] else ""
            linhas.append([f"Ouro {c['validadeOuroMeses']} meses", c["pontos"], 0.05, c["valorVigente"], gravado])
            linhas.append([f"Ouro {c['validadeOuroMeses']} meses", c["pontos"], 0.10, c["valorAntigo"], gravado])
        for nome, faixa in passivo["faixa"].items():
            linhas.append([f"faixa {nome}", faixa["pontos"], faixa["valorPonto"], faixa["valor"], faixa["criterio"]])
        return ["cenario", "pontos", "valor_do_ponto", "valor", "observacao"], linhas
    raise DadosInvalidos(f"Seção inválida. Use: {', '.join(SECOES_CSV)}.")


def csv_da_secao(dados: dict, secao: str) -> str:
    cabecalho, linhas = _tabela(secao, dados)
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(cabecalho)
    escritor.writerows([[_celula(v) for v in linha] for linha in linhas])
    return "﻿" + saida.getvalue()
