"""Produto na vitrine: a coleção (gênero) define em qual página ele aparece (Masculino ou
Feminino) e a estação filtra dentro dela. Peça atemporal aparece em qualquer estação.
Espelha os filtros de src/pages/ColecaoPage.jsx do frontend.

Situação de cada variação (SKU) no catálogo. Dentro de um mesmo modelo, uma cor pode sair de linha
enquanto as outras continuam:
- ATIVO: à venda;
- DESCONTINUADO: saiu da coleção, mas o estoque que sobrou continua vendável (candidata a liquidação);
- FORA_DO_CATALOGO: peça de lista antiga que ainda vende ou tem estoque (Vulto: lista de 2024, decisão 39);
- SO_HISTORICO: código que só existe para o histórico de vendas, sem estoque nem venda nova
  (Vulto: "DIVERSO", a peça não identificada no PDV, decisão 37).

EAN que começa com 2 é de circulação restrita (faixa 200–299 da GS1): é um código interno
provisório, que precisa ser trocado pelo oficial antes de vender em outros canais."""

GENEROS = ("Masculino", "Feminino")
ESTACOES = ("Inverno", "Verão", "Atemporal")
ESTACAO_PADRAO = "Atemporal"

STATUS_VARIACAO = ("ATIVO", "DESCONTINUADO", "FORA_DO_CATALOGO", "SO_HISTORICO")
STATUS_VARIACAO_PADRAO = "ATIVO"
# Situações em que a peça ainda pode ser vendida (as que entram no estoque vendável)
STATUS_VENDAVEIS = ("ATIVO", "DESCONTINUADO", "FORA_DO_CATALOGO")


def ean_interno(ean: str | None) -> bool:
    return bool(ean) and ean.startswith("2")
