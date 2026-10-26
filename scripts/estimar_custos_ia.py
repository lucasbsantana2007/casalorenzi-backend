"""Estimativa de custo mensal dos assistentes de IA (docs/custos_ia.md). Não chama API nenhuma.

    python scripts/estimar_custos_ia.py
    python scripts/estimar_custos_ia.py --conversas 1000 5000 10000 --modelo claude-sonnet-5-5
    python scripts/estimar_custos_ia.py --mensagens 6 --diretas 0.3 --saida 400

O que é medido e o que é premissa:
- MEDIDO (26/10/2026, montando as requisições reais do sistema numa conversa típica): o tamanho em
  caracteres das instruções fixas, das ferramentas, do contexto e do histórico de cada chamada;
- ESTIMADO: tokens = caracteres ÷ 3,5 (português e JSON; sem chave da API não dá para usar o
  count_tokens), tokens de saída por chamada e a fração das chamadas que lê o cache;
- PREMISSA (ajuste pelos parâmetros): conversas por mês, mensagens por conversa, mensagens resolvidas
  pelas regras (sem modelo) e uso do copiloto pela equipe.
Preços: página oficial da Anthropic consultada em 26/10/2026 (US$ por milhão de tokens).
"""

import argparse

# (entrada, escrita no cache de 5 min, leitura do cache, saída), US$ por milhão de tokens.
# Haiku 5.5: prompts de até 100 mil tokens (os daqui ficam bem abaixo disso)
PRECOS = {
    "claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50),
    "claude-sonnet-5-5": (2.00, 2.50, 0.10, 10.00),
    "claude-opus-5-5": (4.00, 5.00, 0.20, 20.00),
}
CARACTERES_POR_TOKEN = 3.5
# Prompt de sistema que a API acrescenta quando há ferramentas (tabela de preços da Anthropic)
TOKENS_SISTEMA_FERRAMENTAS = 286

# MEDIDO: caracteres por chamada ao modelo (média de uma conversa típica)
SITE = {"fixo": 2884 + 5041, "variavel": 625 + 721}  # instruções + ferramentas | contexto + histórico
COPILOTO = {"fixo": 1837 + 10234, "variavel": 898 + 1342}


def custo_por_chamada(perfil: dict, modelo: str, saida: int, fracao_cache: float) -> float:
    entrada, escrita, leitura, preco_saida = PRECOS[modelo]
    fixo = perfil["fixo"] / CARACTERES_POR_TOKEN + TOKENS_SISTEMA_FERRAMENTAS
    variavel = perfil["variavel"] / CARACTERES_POR_TOKEN
    # Parte fixa: lida do cache numa fração das chamadas, escrita (1,25x) nas outras
    fixo_custo = fixo * (fracao_cache * leitura + (1 - fracao_cache) * escrita)
    return (fixo_custo + variavel * entrada + saida * preco_saida) / 1_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--conversas", type=int, nargs="+", default=[1000, 5000, 10000], help="conversas do site por mês")
    parser.add_argument("--modelo", choices=sorted(PRECOS), default="claude-haiku-5-5")
    parser.add_argument("--mensagens", type=float, default=5, help="mensagens do cliente por conversa")
    parser.add_argument("--diretas", type=float, default=0.2, help="fração respondida pelas regras, sem modelo")
    parser.add_argument("--chamadas", type=float, default=2, help="chamadas ao modelo por mensagem (consulta + resposta)")
    parser.add_argument("--saida", type=int, default=250, help="tokens de saída por chamada (com o raciocínio)")
    parser.add_argument("--cache", type=float, default=0.85, help="fração das chamadas que lê a parte fixa do cache")
    parser.add_argument(
        "--perguntas-equipe", type=int, default=3520, help="perguntas ao copiloto por mês (20 pessoas x 8/dia x 22 dias)"
    )
    parser.add_argument("--cambio", type=float, default=None, help="R$ por US$ (opcional; informe o câmbio do dia)")
    args = parser.parse_args()

    chamadas_por_conversa = args.mensagens * (1 - args.diretas) * args.chamadas
    por_conversa = chamadas_por_conversa * custo_por_chamada(SITE, args.modelo, args.saida, args.cache)
    # Copiloto: resultados maiores e equipe espalhada no dia (cache lido em metade das chamadas)
    por_pergunta = args.chamadas * custo_por_chamada(COPILOTO, args.modelo, args.saida + 50, 0.5)
    copiloto = args.perguntas_equipe * por_pergunta

    def dinheiro(valor: float) -> str:
        texto = f"US$ {valor:,.2f}"
        return texto + (f" (R$ {valor * args.cambio:,.2f})" if args.cambio else "")

    print(f"Modelo: {args.modelo} | {chamadas_por_conversa:.1f} chamadas por conversa do site")
    print(f"Custo por conversa do site: US$ {por_conversa:.5f} | por pergunta do copiloto: US$ {por_pergunta:.5f}")
    print(f"Copiloto ({args.perguntas_equipe} perguntas/mês): {dinheiro(copiloto)}")
    for conversas in args.conversas:
        site = conversas * por_conversa
        total = site + copiloto
        linha = f"{conversas:>6} conversas/mês: site {dinheiro(site)} | site + copiloto {dinheiro(total)}"
        print(f"{linha} | tudo em dobro {dinheiro(2 * total)}")


if __name__ == "__main__":
    main()
