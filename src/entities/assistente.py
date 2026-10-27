"""Assistentes de IA: o de atendimento do site (CLIENTE) e o copiloto gerencial do painel (GERENCIAL).

O modelo de linguagem nunca é a fonte dos dados. Ele escolhe uma ferramenta (consulta com parâmetros
tipados); o backend confere a permissão, executa a consulta com as regras que já existem na plataforma
e devolve o resultado. Os números que aparecem na tela saem do resultado da ferramenta, não do texto
do modelo. Sem a chave da API, ou com o modelo fora do ar, as mesmas ferramentas respondem por regras
determinísticas (docs/assistente_ia.md).
"""

from decimal import Decimal

CLIENTE = "CLIENTE"
GERENCIAL = "GERENCIAL"
TIPOS_ASSISTENTE = (CLIENTE, GERENCIAL)

# ATIVA → ENCERRADA (o cliente começou outra, ou ficou parada além da validade)
# ATIVA → ENCAMINHADA (virou um chamado de atendimento humano; a conversa continua)
ATIVA = "ATIVA"
ENCERRADA = "ENCERRADA"
ENCAMINHADA = "ENCAMINHADA"
STATUS_CONVERSA = (ATIVA, ENCERRADA, ENCAMINHADA)

USUARIO = "USUARIO"
ASSISTENTE = "ASSISTENTE"
SISTEMA = "SISTEMA"
PAPEIS_MENSAGEM = (USUARIO, ASSISTENTE, SISTEMA)

# Como a resposta foi produzida
LLM = "LLM"  # o modelo de linguagem, com as ferramentas
REGRAS = "REGRAS"  # regras determinísticas (sem chave da API, ou mensagem simples)
CONTINGENCIA = "CONTINGENCIA"  # o modelo falhou (fora do ar, tempo esgotado): as regras responderam
MODOS_RESPOSTA = (LLM, REGRAS, CONTINGENCIA)

# Resultado de cada chamada ao modelo (consumo_ia)
STATUS_CONSUMO = ("OK", "ERRO", "TIMEOUT", "RECUSA")

# Tamanho máximo da mensagem do usuário
TEXTO_MAXIMO = {CLIENTE: 800, GERENCIAL: 1500}

# Limites de uso (máximo de mensagens, janela em segundos), contra abuso e custo descontrolado
LIMITE_POR_CONVERSA = {CLIENTE: (30, 600), GERENCIAL: (60, 600)}
LIMITE_POR_IP = (60, 600)
LIMITE_CONVERSAS_POR_IP = (20, 3600)

# Mensagens devolvidas ao abrir uma conversa (o resto fica no banco)
MENSAGENS_NO_HISTORICO = 50

# ---------- Custo ----------

# Preço de referência, em dólares por milhão de tokens (entrada, saída): página de preços da Anthropic
# (platform.claude.com/docs/en/about-claude/pricing) consultada em 26/10/2026 (docs/custos_ia.md).
# Modelo fora da tabela: custo não estimado.
PRECOS_MTOK = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
}
# O Haiku 5.5 cobra outra tabela quando o prompt passa de 100 mil tokens (nunca acontece aqui: o histórico
# é limitado), conferida mesmo assim para o custo não sair subestimado
PRECOS_PROMPT_LONGO_MTOK = {"claude-haiku-5-5": (Decimal("0.50"), Decimal("2.50"))}
LIMITE_PROMPT_LONGO = 100_000
# Cache do prompt: leitura a 0,1× o preço de entrada (Opus 5.5 e Sonnet 5.5: 0,05×); escrita (cache de 5
# minutos) a 1,25×
FATOR_CACHE_LEITURA = {"claude-opus-5-5": Decimal("0.05"), "claude-sonnet-5-5": Decimal("0.05")}
FATOR_CACHE_LEITURA_PADRAO = Decimal("0.1")
FATOR_CACHE_ESCRITA = Decimal("1.25")


def custo_estimado(modelo: str, entrada: int, saida: int, cache_leitura: int = 0, cache_escrita: int = 0) -> Decimal | None:
    """Custo em dólares de uma chamada ao modelo, pelos tokens que a API informou."""
    precos = PRECOS_MTOK.get(modelo)
    if precos is None:
        return None
    if entrada + cache_leitura + cache_escrita > LIMITE_PROMPT_LONGO:
        precos = PRECOS_PROMPT_LONGO_MTOK.get(modelo, precos)
    preco_entrada, preco_saida = precos
    leitura = preco_entrada * FATOR_CACHE_LEITURA.get(modelo, FATOR_CACHE_LEITURA_PADRAO)
    escrita = preco_entrada * FATOR_CACHE_ESCRITA
    total = entrada * preco_entrada + saida * preco_saida + cache_leitura * leitura + cache_escrita * escrita
    return (total / Decimal(1_000_000)).quantize(Decimal("0.000001"))


# ---------- Definições das métricas (aparecem em cada resposta do copiloto) ----------

DEFINICOES = {
    "faturamento": (
        "Faturamento (regra da diretoria): total dos pedidos de venda não cancelados criados no período "
        "(itens − desconto + frete), menos o valor das devoluções registradas no período. Troca não é receita."
    ),
    "receita_bruta": (
        "Receita de vendas: total dos pedidos de venda não cancelados (itens − desconto + frete), sem descontar as devoluções."
    ),
    "receita_categoria": (
        "Receita em itens da categoria: preço × quantidade das peças vendidas (sem frete e antes do desconto do pedido)."
    ),
    "cancelamentos": (
        "Pedidos de venda com status CANCELADO criados no período (na Vulto, inclui cancelada, estornada, "
        "chargeback e aguardando pagamento). Não entram no faturamento."
    ),
    "mais_vendidos": (
        "Peças de pedidos de venda não cancelados no período (trocas não contam). Valor = preço de cada item × "
        "quantidade, sem frete e antes do desconto do pedido."
    ),
    "estoque_baixo": (
        "Item de estoque (loja + SKU) com saldo menor ou igual ao mínimo do item (zerado incluso), só de peças "
        "ativas e vendáveis. 'Com demanda': a peça vendeu naquele local nos últimos dias da janela."
    ),
    "estoque_parado": (
        "Item de estoque (loja + SKU) com saldo e sem saída por venda naquele local há N dias ou mais (última "
        "movimentação VENDA). Sem venda registrada no local, conta desde a primeira movimentação do item."
    ),
    "valor_estoque": "Valor do estoque: peças × preço de venda do produto (a mesma conta do dashboard).",
    "avarias": "Movimentações de AVARIA (peça com defeito que saiu do estoque vendável); 'estimada' quando não foi contada.",
    "transferencias": (
        "Sugestão para análise humana: a origem tem peças livres acima do dobro do mínimo; o destino está no "
        "mínimo ou zerado e vendeu a peça na janela. Nada é transferido automaticamente."
    ),
    "pontos": (
        "Pontos Helo válidos: o que sobrou de cada entrada que ainda não venceu (validade de 12 meses), gastando "
        "primeiro as mais antigas. 100 pontos = R$ 5,00. Categoria pelo saldo válido."
    ),
}

# ---------- Alertas operacionais (automações) ----------

ALERTA_ESTOQUE_BAIXO = "ESTOQUE_BAIXO"
ALERTA_ESTOQUE_PARADO = "ESTOQUE_PARADO"
ALERTA_TRANSFERENCIA = "SUGESTAO_TRANSFERENCIA"
ALERTA_PONTOS = "PONTOS_A_VENCER"
TIPOS_ALERTA = (ALERTA_ESTOQUE_BAIXO, ALERTA_ESTOQUE_PARADO, ALERTA_TRANSFERENCIA, ALERTA_PONTOS)

# Quem vê cada tipo de alerta: o módulo de src/entities/papeis.py que já dá acesso àquele assunto. Os pontos
# a vencer mostram o passivo do Helo em reais: ficam com quem vê o financeiro
MODULO_DO_ALERTA = {
    ALERTA_ESTOQUE_BAIXO: "estoque",
    ALERTA_ESTOQUE_PARADO: "estoque",
    ALERTA_TRANSFERENCIA: "transferencias",
    ALERTA_PONTOS: "financeiro",
}

ABERTO = "ABERTO"
RESOLVIDO = "RESOLVIDO"
DESCARTADO = "DESCARTADO"
STATUS_ALERTA = (ABERTO, RESOLVIDO, DESCARTADO)
SEVERIDADES = ("ALTA", "MEDIA", "BAIXA")

# Automações (python -m src.automacoes): cada uma é idempotente e roda uma de cada vez
AUTOMACOES = (
    "estoque_baixo",
    "estoque_parado",
    "sugestoes_transferencia",
    "pontos_a_vencer",
    "aviso_pontos",
    "limpeza_conversas",
)
STATUS_EXECUCAO = ("EM_ANDAMENTO", "SUCESSO", "ERRO", "IGNORADA")
# Execução terminada há menos que isso não roda de novo (dois cliques ou dois agendadores)
INTERVALO_MINIMO_SEGUNDOS = 60
