# Números da diretoria — Vulto

Gerados a partir do banco com a migração da Vulto carregada (`python -m src.migracao_vulto --tudo`).
Os CSVs abrem direto no Excel em português (separador `;`, vírgula decimal, UTF-8 com BOM).

| Arquivo | O que tem |
|---|---|
| `numeros.json` | As três respostas completas: pergunta, resposta, decisões aplicadas e margem de erro |
| `faturamento.csv` | Faturamento de jan/2025 a set/2026 por mês × loja × canal (sem frete, frete, com frete, devoluções, líquido) |
| `ponte.csv` | Do relatório do sistema da Vulto ao nosso número, passo a passo: no total e mês a mês |
| `estoque_lojas.csv` | Estoque em 01/10/2026 por loja/CD, com a composição (abertura, entradas, transferências, vendas, devoluções, ajuste da contagem) e a data da contagem |
| `estoque_produtos.csv` | Estoque em 01/10/2026 por produto e loja |
| `passivo.csv` | Passivo do Vulto+ em 01/10/2026: cenários (Ouro 12/18 meses × R$ 0,05/0,10) e a faixa |

**Gerar de novo** (depois da migração em produção, por exemplo):

```bash
python -m src.relatorios.diretoria --saida docs/numeros_diretoria
```

Os mesmos números saem pela API (administrador): `GET /api/diretoria/numeros` e
`GET /api/diretoria/numeros/{faturamento|ponte|estoque-lojas|estoque-produtos|passivo}.csv`.
