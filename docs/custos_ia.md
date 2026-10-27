# Custos dos assistentes de IA

Legenda usada em todo o documento:

- **[MEDIDO]** saiu do sistema rodando (tamanho das requisições, tempo das consultas, testes).
- **[ESTIMADO]** conta feita a partir de algo medido, com um fator que não deu para medir (ex.: tokens).
- **[PREMISSA]** hipótese de uso, para ajustar com dados reais.

Os números podem ser refeitos com outras premissas: `python scripts/estimar_custos_ia.py --help`.

## Resumo

Com o modelo padrão (**Claude Haiku 5.5**), o custo de IA fica em **dezenas de dólares por mês** mesmo em 10 mil
conversas, porque as mensagens simples não chamam o modelo, as instruções fixas vão para o cache e o modelo é o
mais barato da família que faz chamadas de ferramenta.

| Cenário [PREMISSA] | Só o site | Site + copiloto | Volume em dobro |
| --- | --- | --- | --- |
| 1.000 conversas/mês | US$ 1,86 | US$ 5,14 | US$ 10,29 |
| 5.000 conversas/mês | US$ 9,32 | US$ 12,60 | US$ 25,20 |
| 10.000 conversas/mês | US$ 18,64 | US$ 21,92 | US$ 43,84 |

[ESTIMADO] Haiku 5.5, 5 mensagens por conversa, 20% respondidas sem modelo, 2 chamadas por mensagem, 85% das
chamadas lendo a parte fixa do cache; copiloto com 3.520 perguntas/mês (20 pessoas × 8 por dia × 22 dias).
Pior caso (sem cache, nenhuma resposta direta, saída de 400 tokens): US$ 55,72 por 10 mil conversas.

Para converter em reais, use o câmbio do dia: `python scripts/estimar_custos_ia.py --cambio <R$ por US$>`.

## 1. Modelo escolhido e alternativas

O pedido foi um modelo **econômico e confiável com chamada de ferramentas**. As três opções atuais da Anthropic,
com preços da página oficial (platform.claude.com/docs/en/about-claude/pricing), consultada em **26/10/2026**:

| | Claude Haiku 5.5 (padrão) | Claude Sonnet 5.5 | Claude Opus 5.5 |
| --- | --- | --- | --- |
| Entrada / saída (US$ por milhão de tokens) | 0,10 / 0,50 (prompts até 100 mil tokens) | 2,00 / 10,00 | 4,00 / 20,00 |
| Escrita no cache (5 min) / leitura do cache | 0,125 / 0,01 | 2,50 / 0,10 | 5,00 / 0,20 |
| Custo por conversa do site [ESTIMADO] | US$ 0,0019 | US$ 0,036 | US$ 0,071 |
| 10 mil conversas + copiloto [ESTIMADO] | US$ 21,92 | US$ 419,69 | US$ 839,39 |
| Seguir instruções e chamar ferramentas | Bom para tarefas curtas com poucas ferramentas (é o perfil aqui); a doc da Anthropic recomenda Haiku para alto volume e baixa latência | Melhor em perguntas abertas e várias etapas | O mais capaz; exagero para este uso |
| Latência | A menor das três | Intermediária | A maior |
| Disponibilidade | API da Anthropic, AWS (Bedrock e Claude Platform), Google Cloud e Microsoft Foundry | Idem | Idem |
| Integração | O mesmo código: troca por `IA_MODELO` | Idem | Idem |

Por que o Haiku 5.5 como padrão:

1. **Custo**: 20× mais barato que o Sonnet 5.5 na entrada e na saída.
2. **A tarefa é estreita**: o modelo escolhe entre 8 ferramentas (site) ou 11 (copiloto) com parâmetros tipados e
   explica um resultado já formatado. Não faz conta nem decide permissão, porque o backend faz isso.
3. **O erro é contido**: os números da tela vêm das ferramentas, não do texto do modelo; parâmetro inválido volta
   como erro para o modelo corrigir; sem resposta, as regras assumem.
4. **Trocar é configuração**: `IA_MODELO=claude-sonnet-5-5` no ambiente, sem mudar código. O custo de cada chamada
   fica em `consumo_ia` com o modelo usado, então dá para comparar os dois com tráfego real.

O que não foi comparado: modelos de outros fornecedores. Não havia preço verificado e atualizado para eles neste
trabalho, e não inventamos valores. A integração está isolada em `src/integrations/ia.py` (o resto do sistema só
conhece `RespostaIA` e `ErroIA`), então um outro provedor seria uma classe nova nesse arquivo.

Não verificado ainda: a qualidade das respostas do Haiku 5.5 nas nossas perguntas. Sem chave da API neste trabalho,
os testes usaram um modelo simulado. O primeiro passo com a chave é rodar o [roteiro](roteiro_demonstracao.md) e
olhar a aba "Uso e custo da IA".

## 2. Tokens por conversa

**[MEDIDO]** Tamanho, em caracteres, do que o sistema manda ao modelo em cada chamada (média de uma conversa
típica montada pelo próprio backend, 26/10/2026):

| Parte da requisição | Site | Copiloto |
| --- | --- | --- |
| Instruções fixas (com cache) | 2.884 | 1.837 |
| Definição das ferramentas (com cache) | 5.041 | 10.234 |
| Contexto da rodada (data, quem, memória, lojas) | 625 | 898 |
| Histórico + resultados das consultas (média) | 721 | 1.342 |
| **Total por chamada** | **~9.300** | **~14.300** |

**[ESTIMADO]** Tokens = caracteres ÷ 3,5 (português e JSON). Sem chave da API não dá para medir com o
`count_tokens`; a conta real fica em `consumo_ia` assim que a chave estiver ligada.
A API ainda acrescenta 286 tokens de sistema quando há ferramentas (tabela de preços da Anthropic).

| Por chamada [ESTIMADO] | Site | Copiloto |
| --- | --- | --- |
| Parte fixa (cacheável) | ~2.550 tokens | ~3.740 tokens |
| Parte variável | ~385 tokens | ~640 tokens |
| Saída (com o raciocínio em esforço `low`) | ~250 tokens | ~300 tokens |

**[PREMISSA]** Uma conversa do site tem 5 mensagens do cliente; 1 em cada 5 é simples (saudação, agradecimento,
pedido de atendente) e responde sem modelo; as outras usam 2 chamadas (consulta + resposta). São **8 chamadas por
conversa** — exatamente o que acontece no fluxo "camisa azul → M → a primeira → adicionar".

## 3. Cenários mensais

`python scripts/estimar_custos_ia.py --modelo <modelo>`:

| Conversas/mês | Haiku 5.5 (site + copiloto) | Sonnet 5.5 | Opus 5.5 |
| --- | --- | --- | --- |
| 1.000 | US$ 5,14 | US$ 99,85 | US$ 199,70 |
| 5.000 | US$ 12,60 | US$ 242,00 | US$ 484,01 |
| 10.000 | US$ 21,92 | US$ 419,69 | US$ 839,39 |
| 20.000 (volume em dobro de 10 mil, copiloto também em dobro) | US$ 43,84 | US$ 839,38 | US$ 1.678,78 |

O custo cresce em linha reta com o volume (não há custo fixo de IA).

## 4. Infraestrutura

O assistente roda dentro da API e do site que já existem: **nenhum serviço novo é obrigatório**.

| Item | Situação | Custo |
| --- | --- | --- |
| API (Render, web service) | Já existe | Plano grátis [MEDIDO na documentação do Render]: dorme após 15 minutos sem tráfego (o primeiro acesso leva ~1 minuto) e tem 750 horas por mês. Para produção, o plano pago: valor a confirmar em render.com/pricing (a página não mostrou os preços na consulta) |
| Banco (Render Postgres) | Já existe; +6 tabelas | Grátis expira em **30 dias** e tem **1 GB**. Para produção, plano pago: a confirmar em render.com/pricing. Volume novo: resposta do site ~0,7 KB em média (até 2 KB) e do copiloto ~2,2 KB (até 5,8 KB) [MEDIDO]; 10 mil conversas × ~4 KB ≈ 40 MB por mês, mais índices e auditoria, limitado pela retenção de 90 dias [ESTIMADO] |
| Site (Vercel) | Já existe | Sem mudança (o chat é carregado só ao abrir: +11 KB) |
| Automações | Opcional | Cron Job do Render: mínimo de US$ 1 por mês [MEDIDO na documentação do Render], cobrado por segundo de execução (as 5 rodam em ~1,4 s no banco local); ou GitHub Actions; ou o botão do Administrador |

## 5. Custos adicionais de ferramentas

Nenhum. Não usamos banco vetorial, embeddings, filas nem serviços de terceiros além do modelo: a busca é textual
com vocabulário de moda e filtros (o catálogo tem ~190 peças), e a memória da conversa fica no Postgres.

## 6. Estratégias de redução de custo (implementadas)

1. **Modelo econômico por padrão** (Haiku 5.5) e esforço `low`.
2. **Respostas diretas sem modelo** para saudação, agradecimento, despedida e pedido de atendente.
3. **Cache do prompt**: instruções e ferramentas (~2.550 tokens no site) são lidas do cache a 10% do preço.
4. **Histórico limitado** (12 mensagens) + memória curta estruturada, em vez da conversa inteira.
5. **Limites por mensagem**: 4 idas e voltas, 6 consultas, 2.048 tokens de saída.
6. **Limites de uso** por conversa, por IP e por usuário (429), contra abuso.
7. **Reenvio não paga duas vezes** (`idCliente`), e uma mensagem por vez por conversa.
8. **Valores já formatados** nos resultados: o modelo copia, não precisa raciocinar sobre contas.
9. **Contingência sem custo**: se o modelo falha, as regras respondem.
10. **Medição**: `consumo_ia` registra tokens e custo de cada chamada; a aba "Uso e custo da IA" mostra por dia,
    por modelo, latência e falhas.

Próximas, se o volume crescer: a API de lotes (50% mais barata) para tarefas que não precisam de resposta na hora,
como resumos noturnos; cache de 1 hora em horários de pouco tráfego; rotear perguntas difíceis do copiloto para o
Sonnet 5.5 só quando a avaliação mostrar ganho.

## 7. Benefícios operacionais esperados [PREMISSA]

Não medidos: dependem de dados de atendimento e vendas que ainda não existem com o assistente no ar.

| Benefício | Como medir | Conta de referência |
| --- | --- | --- |
| Menos perguntas simples para a equipe (horário, disponibilidade, pontos, status do pedido) | Conversas que terminam sem chamado aberto | Se 1.000 conversas/mês evitarem 30% de contatos de 4 minutos: 1.000 × 0,30 × 4 min = 20 horas/mês |
| Venda assistida | Botões "Adicionar à sacola" confirmados × pedidos com essas peças | Taxa de conversão do chat |
| Menos ruptura | Alertas de estoque baixo resolvidos antes de zerar | Itens zerados com demanda antes e depois |
| Capital parado | Alertas de estoque parado (hoje 2,1 mil itens sem venda há 90+ dias no banco local [MEDIDO]) | Valor parado que virou ação comercial ou transferência |
| Retenção do Helo | Clientes com pontos a vencer contatados (com consentimento) | No banco local, 522 clientes e 281.401 pontos (R$ 14.070,05) vencem em 30 dias [MEDIDO] |
| Gestão mais rápida | Perguntas ao copiloto × tempo para montar o mesmo número no Financeiro | Respostas medidas em até 0,4 s por consulta de mês [MEDIDO] |

## 8. Limitações e riscos

- **Custo real ainda não medido**: falta a chave da API; as contas usam caracteres ÷ 3,5. O primeiro dia com a chave
  dá o número real em `consumo_ia`.
- **Preço pode mudar**: a tabela de `src/entities/assistente.py` (`PRECOS_MTOK`) é a referência do custo estimado;
  revisar ao trocar de modelo.
- **Haiku 5.5 acima de 100 mil tokens** de prompt custa 5×: impossível aqui (o histórico é limitado), mas o cálculo
  já considera.
- **Qualidade**: o Haiku pode escolher mal uma ferramenta em perguntas ambíguas. Mitigação: as regras do backend, os
  limites e o modelo trocável.
- **Infraestrutura grátis** não serve para produção (banco expira em 30 dias, API dorme).
- **Câmbio**: os valores estão em dólares; a conversão depende do dia.
