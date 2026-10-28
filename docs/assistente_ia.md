# Entrega 4 — Assistentes de IA da plataforma Casa Lorenzi + Vulto

Dois assistentes integrados à plataforma existente, mais automações operacionais:

1. **Assistente do site, a Lúcia** (clientes; decisão 89): busca peças no catálogo real, mostra a disponibilidade no site e em
   cada loja, mantém o contexto da conversa, consulta pontos Lupe+ e pedidos do cliente logado, prepara a
   peça para a sacola (o cliente confirma no botão) e encaminha para o atendimento humano com o resumo da conversa.
2. **Copiloto gerencial** (equipe): "Inteligência de Negócios — Assistente IA" no painel. Responde perguntas
   sobre vendas, estoque, transferências e Lupe+ com consultas controladas, sempre com período, filtros,
   definição da métrica e a data dos dados.
3. **Automações**: alertas de estoque baixo, estoque parado, sugestões de transferência e pontos a vencer,
   idempotentes, com log de execução; mais a limpeza das conversas pela política de retenção.
4. **Copiloto no Claude** (decisões 106, 114 e 115): as ferramentas do copiloto no claude.ai (login OAuth), no
   Claude Code, no Claude Desktop ou no n8n (token pessoal), para toda a equipe com acesso ao Assistente IA,
   cada um com as permissões do próprio perfil e só leitura. Detalhes em [mcp.md](mcp.md).

Custos e escolha do modelo: [custos_ia.md](custos_ia.md). Roteiro para a banca: [roteiro_demonstracao.md](roteiro_demonstracao.md).

## O princípio: o modelo não é a fonte dos dados

O modelo de linguagem (Claude, da Anthropic) só **escolhe** consultas e **explica** os resultados. Ele nunca
escreve SQL, nunca recebe um id de cliente e nunca decide permissão:

```
Usuário ─► API (token: quem é, que papel, que marca)
            │
            ├─► mensagem simples ("oi", "obrigado", "quero falar com alguém")? ─► resposta direta, sem modelo
            │
            ├─► com ANTHROPIC_API_KEY: modelo ─► pede uma ferramenta (nome + parâmetros)
            │        │                               │
            │        │       backend valida: a ferramenta existe? foi oferecida a este perfil?
            │        │       parâmetros batem com o contrato (Pydantic, sem campo extra)?
            │        │       o papel/marca/login permitem? ─► consulta (sessão READ ONLY, com tempo máximo)
            │        │                               │      usando as regras que já existem (financeiro,
            │        │                               │      estoque, Lupe+, vitrine)
            │        ◄──────── resultado (valores já formatados) ◄┘
            │        └─► texto final (no máximo 4 idas e voltas e 6 consultas por mensagem)
            │                 └─► verificador: todo número do texto tem fonte? senão, refaz uma vez ou troca
            │
            └─► sem chave, ou modelo fora do ar: as mesmas ferramentas, escolhidas por regras
                                          ▼
               Resposta = texto + blocos (cards, tabelas, gráficos, fonte), montados pelo backend
                          a partir do resultado das ferramentas, não do texto do modelo
```

Por isso os números da tela (preço, estoque, faturamento, pontos) são sempre os do banco: mesmo que o modelo
errasse ao escrever, os cards, tabelas e gráficos vêm do resultado da consulta. E os números do **texto** também são
conferidos antes de sair (verificador, decisão 101, abaixo).

## Modos de resposta

Cada resposta registra o modo (`mensagens_assistente.modo`):

| Modo | Quando | Custo |
| --- | --- | --- |
| `LLM` | Há `ANTHROPIC_API_KEY` e o modelo respondeu | Tokens (ver custos) |
| `REGRAS` | Sem chave, ou mensagem simples (saudação, agradecimento, pedido de atendente) | Zero |
| `CONTINGENCIA` | O modelo falhou (tempo esgotado, sem conexão, 5xx, resposta inválida): as regras respondem com as mesmas ferramentas; se uma consulta já tinha dado certo, usa o resultado dela | Zero após a falha |

A resposta pronta de agradecimento ou despedida só vale quando a mensagem é **só isso** ("obrigada!", "valeu, tchau").
Com uma pergunta junto ("valeu, tem no G?", "perfeito, e na cor preta?"), a mensagem segue para o modelo; sem modelo,
as regras tiram o agradecimento do começo e respondem a pergunta (`so_cortesia` em `regras_cliente.py`, usada também
pelo copiloto).

As regras (`src/use_cases/assistente/regras_*.py`) entendem as perguntas mais comuns: tipo de peça, cor,
tamanho, faixa de preço, marca, loja ("loja do shopping", "em BH"), continuações ("M", "e na outra loja?",
"a segunda", "sim"), períodos ("hoje", "nesta semana", "em setembro", "últimos 30 dias", "de 01/09 a 15/09").
Assim a demonstração funciona mesmo sem chave, e uma queda do provedor não derruba o atendimento.

## Qualidade das respostas (decisões 101 a 105)

| O quê | Como funciona | Onde |
| --- | --- | --- |
| Verificador de números (101) | Todo número da resposta do modelo (R$, pontos, %, parcelas, prazos, datas, horários, códigos e qualquer número de 11 para cima) precisa ter fonte: as consultas da rodada, o contexto do sistema ou as respostas anteriores. O que o cliente disse vale só para tamanho, quantidade, data e código. Sem fonte, o modelo refaz uma vez (pode consultar o que faltou); se errar de novo, sai o texto pronto das consultas ou "não consegui confirmar". Sem chamada a mais quando a resposta está certa. | `verificacao.py`, `orquestrador._com_modelo` |
| Duas falhas seguidas → pessoa (102) | Falha da Lúcia (não entendeu, não respondeu, número não confirmado) ou do cliente ("não foi isso", a mesma pergunta de novo). Na segunda seguida, a resposta ganha os botões de falar com a equipe; resposta sem falha zera a contagem. | `escalonamento.py` (passo final do assistente do site) |
| Saudação personalizada (103) | Cliente logado: pontos que vencem em 30 dias, pedido em andamento e atalho do tipo de peça que ele mais compra no tamanho que costuma levar. Busca sem tamanho sugere esse tamanho. Só lê. | `perfil_cliente.py`, `conversas.abrir_cliente` |
| "Ajudou?" (104) | 👍/👎 na última resposta, com o que faltou no 👎. O Uso da IA mostra a qualidade por assistente. | `POST /assistente/conversas/{id}/mensagens/{id}/avaliacao`, `conversas.metricas` |
| Bateria como portão (105) | 38 casos difíceis com o que cada resposta precisa ter. Sem o Claude no pytest; com o Claude em `scripts/avaliar_lucia.py`. | `tests/bateria_lucia.py`, `docs/avaliacao_lucia.md` |

A auditoria de cada resposta fica em `mensagens_assistente.auditoria` (JSON): `verificacao` (CONFERIDA, REESCRITA ou
SUBSTITUIDA), `numeros`, `semFonte`, `textoModelo` (o que o modelo tinha escrito), `falhou`, `sinalDoCliente` e
`ofereceuPessoa`. O teste com pessoas de fora tem roteiro em `docs/teste_com_pessoas.md` e relatório em
`scripts/relatorio_lucia.py`.

## Onde está cada parte

### Backend (`casalorenzi-backend`)

| Arquivo | Responsabilidade |
| --- | --- |
| `src/integrations/ia.py` | Cliente do modelo pelo SDK oficial (`anthropic`), erros mapeados (`ErroIA`), troca do provedor nos testes |
| `src/entities/assistente.py` | Tipos, limites de uso, preços e custo estimado, definições das métricas, tipos de alerta e quem os vê |
| `src/entities/busca.py` | Vocabulário da busca: cores e famílias de cor, tipos de peça, tamanhos, faixa de preço (sem banco) |
| `src/entities/periodo.py` | Períodos em datas do fuso da plataforma (`FUSO_HORARIO`) |
| `src/use_cases/assistente/ferramentas.py` | Contrato das ferramentas, checagem de permissão, execução isolada e auditável |
| `src/use_cases/assistente/ferramentas_cliente.py`, `ferramentas_conta.py` | As 16 ferramentas do site (catálogo, lojas, políticas, sacola, atendimento; conta do cliente e ações com confirmação) |
| `src/use_cases/assistente/ferramentas_gerenciais.py` | As 14 ferramentas do copiloto |
| `src/use_cases/assistente/catalogo.py` | Busca no catálogo e disponibilidade por loja (regras da vitrine) |
| `src/use_cases/assistente/orquestrador.py` | Uma rodada: resposta direta, modelo com ferramentas ou regras; limites e contingência |
| `src/use_cases/assistente/regras_cliente.py`, `regras_gerenciais.py` | Respostas sem modelo |
| `src/use_cases/assistente/prompts.py` | Instruções fixas (vão para o cache do modelo) e o contexto de cada rodada |
| `src/use_cases/assistente/conversas.py` | Dono da conversa, envio com trava e deduplicação, sacola, encaminhamento, retenção, métricas |
| `src/use_cases/analises.py` | Análises da operação (copiloto e automações), só leitura |
| `src/use_cases/automacoes.py`, `src/automacoes/` | Automações e a linha de comando `python -m src.automacoes` |
| `src/routers/assistente.py`, `copiloto.py`, `alertas.py` | Rotas da API |
| `src/use_cases/assistente/canal_whatsapp.py`, `src/routers/canais.py` | A Lúcia no WhatsApp: o n8n chama a API e entrega a resposta (decisão 108, [whatsapp.md](whatsapp.md)) |
| `src/use_cases/assistente/servidor_mcp.py`, `src/use_cases/tokens_mcp.py`, `src/routers/mcp.py` | Servidor MCP do copiloto e os tokens pessoais (decisão 106, [mcp.md](mcp.md)) |
| `src/repositories/assistente_repository.py`, `alerta_repository.py`, `analise_repository.py` | Consultas (SQLAlchemy, sempre com parâmetros) |
| `src/models/conversa_assistente.py` e outros 5 | Tabelas novas (ver "Banco de dados") |
| `scripts/estimar_custos_ia.py` | Estimativa de custo mensal |

### Frontend (`casalorenzi-frontend`)

| Arquivo | Responsabilidade |
| --- | --- |
| `src/components/assistente/ChatWidget.jsx` | Botão flutuante (vitrine Casa Lorenzi, vitrine Vulto e área do cliente; some no checkout) |
| `src/components/assistente/PainelChat.jsx`, `BlocosChat.jsx` | Janela do chat (carregada só ao abrir) e os blocos: peças, disponibilidade, lojas, pontos, pedidos, sacola, atendimento |
| `src/hooks/useAssistente.js` | Conversa no navegador (id + chave), nova conversa ao trocar de conta, reenvio sem duplicar, conversa vencida |
| `src/pages/admin/InteligenciaPage.jsx` | Página `/inteligencia`: Assistente, Alertas, Conectar ao Claude e Uso e custo da IA (Administrador) |
| `src/components/copiloto/*` | Indicadores, tabelas, gráficos (recharts, já usado no Financeiro), fonte, alertas e uso |
| `src/services/assistenteService.js`, `copilotoService.js` | Chamadas à API (a chave do modelo nunca passa pelo navegador) |

Nenhuma biblioteca nova no frontend. No backend, uma: o SDK oficial `anthropic` (2.3.0).

## As ferramentas

### Site

| Ferramenta | O que faz | Exige | Reaproveita |
| --- | --- | --- | --- |
| `buscar_produtos` | Peças por tipo, cor, tamanho, preço, marca, gênero, loja e palavras livres; afrouxa um filtro por vez e avisa | — | `produtos.listar`, `disponiveis_na_rede`, `livres_por_loja` |
| `ver_produto` | Detalhes e situação no site e em cada loja física, na cor e tamanho pedidos | — | os mesmos |
| `informacoes_lojas` | Endereço, telefone e horários cadastrados | — | tabela `lojas` |
| `politicas_da_loja` | Frete, trocas e devoluções, pagamento, regras do Lupe+ | — | `frete.condicoes`, `tipos_solicitacao`, `entities/fidelidade.py` |
| `consultar_meus_pontos` | Saldo, valor, categoria, vencimentos e quanto falta para a próxima categoria | login de cliente | `fidelidade.resumo` (a mesma conta da página Lupe+) |
| `consultar_meus_pedidos` | 5 pedidos mais recentes, status e rastreio | login de cliente | `pedido_repository.do_cliente` |
| `colocar_na_sacola` | Confere peça, cor, tamanho, preço e disponibilidade; o chat coloca a peça na sacola na hora, com Desfazer e Finalizar compra (decisão 94) | — | preço vigente do SKU e disponível da vitrine |
| `solicitar_atendimento_humano` | Mostra "Falar com a equipe" (chamado no site, com login) e "Continuar no WhatsApp" (com o protocolo, sem login; decisão 81) | — | módulo de Atendimento |
| `ver_pedido` | Detalhe de um pedido: peças, valores, frete, pagamento, rastreio, histórico, devoluções e se ainda cancela ou devolve | login de cliente | `pedido_repository`, `pedidos_cliente` |
| `consultar_reembolsos` | Devoluções registradas (com o valor reembolsado), pedidos cancelados com estorno e solicitações de devolução ou troca em análise | login de cliente | `devolucoes`, `pagamentos`, `atendimentos` |
| `consultar_extrato_pontos` | Os últimos movimentos de pontos (compras, resgates, estornos, vencimentos) | login de cliente | `fidelidade.resumo` |
| `consultar_minhas_solicitacoes` | As 5 solicitações mais recentes com a equipe e a situação de cada uma | login de cliente | `atendimento_repository.do_cliente` |
| `calcular_frete` | Valor e prazo (Padrão e Expresso) para um CEP | — | `frete.opcoes` |
| `trocar_meu_email` | Prepara o cartão de troca de e-mail; o cliente confirma com a senha (decisão 95) | login de cliente | `PUT /api/conta` |
| `cancelar_pedido` | Prepara o cartão de cancelamento de pedido em separação (decisão 96) | login de cliente | `POST /api/conta/pedidos/{numero}/cancelamento` |
| `solicitar_devolucao` | Prepara o cartão de devolução (pedido recebido há até 30 dias; peças e motivo; decisão 97) | login de cliente | `POST /api/conta/pedidos/{numero}/devolucao` |

O cliente vê a **situação** (disponível, últimas unidades, indisponível), não a quantidade exata. Na loja,
vale o que está na prateleira e livre: `min(saldo físico, saldo livre)`. No site, o disponível oficial da
vitrine (saldo + a caminho − reservas).

**A Lúcia faz as tarefas do cliente (decisão 93), em quatro níveis:**

| Nível | Exemplos | Como funciona |
| --- | --- | --- |
| Consulta | pedido, rastreio, reembolso, extrato, solicitações, frete por CEP | Responde na hora, com os dados do cliente do token |
| Ação leve | colocar na sacola | Acontece na hora, com Desfazer; sacola não é compra |
| Ação sensível | trocar e-mail, cancelar pedido, pedir devolução | A ferramenta só prepara o cartão; a ação acontece na rota da conta quando o cliente confirma. A senha vai direto para `/api/conta`, nunca para a conversa nem para o modelo |
| Nunca pelo chat | pagamento e cartão, trocar senha, excluir conta | A Lúcia leva à página certa |

O cancelamento é o mesmo do painel (`pedidos.cancelar`): estorna o pagamento, tira os pontos ganhos, devolve os
usados e cancela as transferências que não saíram; só para pedido ainda em separação. A devolução abre a
solicitação "Devolução e reembolso" ligada ao pedido; a equipe confere a peça, registra a devolução e faz o estorno:
dinheiro de volta sempre passa por uma pessoa. Depois da confirmação, o cartão fica concluído na conversa
(`ACAO_CONCLUIDA`) e a Lúcia lembra o que foi feito.

**Atendimento humano:** o canal real é o atendimento da plataforma (tabela `atendimentos`). Com login,
"Falar com a equipe" abre um chamado de "Dúvida sobre produto" com o resumo da conversa (motivo, peça em foco,
última busca, últimas mensagens), que aparece no painel de Atendimento e em Minha conta > Solicitações. Com ou sem
login, "Continuar no WhatsApp" abre o chamado (canal WHATSAPP) e o WhatsApp do atendimento com o protocolo já
escrito. Chamar de novo devolve o mesmo chamado.

### Copiloto

| Ferramenta | Módulo exigido | Reaproveita |
| --- | --- | --- |
| `consultar_faturamento` (com quebra por marca, loja, canal, categoria ou tempo) | financeiro | `financeiro.resumo` |
| `consultar_mais_vendidos` | financeiro | itens de pedidos de venda não cancelados (mesmas regras do financeiro) |
| `consultar_cancelamentos` | financeiro | pedidos de venda com status CANCELADO, por motivo de origem e canal |
| `consultar_estoque_baixo` | estoque | `status_estoque` (quantidade × mínimo) + vendas recentes |
| `consultar_estoque_parado` | estoque | última movimentação VENDA de cada item |
| `consultar_estoque_por_loja` | estoque | peças e valor (mesma conta do dashboard) |
| `consultar_maiores_estoques` | estoque | estoque por produto |
| `consultar_avarias` | estoque | movimentações AVARIA (contadas e estimadas) |
| `sugerir_transferencias` | transferencias | `livres_por_loja`, mínimo de cada loja, vendas recentes |
| `consultar_fidelidade` | financeiro | lotes do Lupe+ (`fidelidade.lotes_em_aberto`), só números agregados |
| `consultar_alertas` | dashboard (cada tipo pede o seu módulo) | tabela `alertas` |

**Faturamento:** é a regra da diretoria que já estava no Financeiro (decisões da união com a Vulto): vendas não
canceladas, itens − desconto + frete, troca fora, menos as devoluções do período, no fuso America/Sao_Paulo, com
valores em reais (`Numeric(12,2)`, sem conversão de centavos). Para quebrar por loja e canal sem refazer a conta,
`financeiro.resumo` passou a devolver também as devoluções e o faturamento líquido de cada loja e de cada canal
(campos novos; os existentes não mudaram). Conferido no banco local: a Vulto de jan/2025 a set/2026 continua em
R$ 6.498.071,30, e as somas por loja e por canal fecham com o total.

**Definições** que aparecem em cada resposta (bloco "Fonte"), em `src/entities/assistente.py` (`DEFINICOES`):

- *Faturamento*: vendas não canceladas (itens − desconto + frete) − devoluções do período. Troca não é receita.
- *Receita de vendas*: o mesmo, sem descontar devoluções. *Receita em itens* (por categoria): preço × quantidade.
- *Cancelamentos*: pedidos de venda com status CANCELADO criados no período (cancelada, estornada, chargeback,
  aguardando pagamento).
- *Estoque baixo*: item (loja + SKU) com saldo ≤ mínimo do item; "com demanda" = vendeu no local nos últimos 60 dias.
- *Estoque parado*: item com saldo e sem saída por venda no local há N dias (sem venda no local: desde a primeira
  movimentação do item). Referência: hoje.
- *Pontos válidos*: o que sobrou das entradas ainda não vencidas (12 meses), gastando primeiro as mais antigas.

## Segurança

| Risco | Como está tratado |
| --- | --- |
| Ver dados de outro cliente | Ferramentas pessoais não têm parâmetro de cliente: usam o cliente do **token**. Parâmetro a mais (ex.: `cliente_id`) é recusado (`extra="forbid"`). |
| Conversa de outra pessoa | Id não sequencial (uuid). Sem login, só com a chave da conversa (no banco, só o hash, comparado em tempo constante). Com login, só o dono. Fora disso: 404. |
| Operador vendo financeiro | O modelo nem recebe as ferramentas que o perfil não pode usar; se pedir mesmo assim, a execução recusa (permissão conferida a cada chamada, pela tabela `ACESSO` existente). |
| Equipe de uma marca vendo a outra | A marca vem do token (`escopo_marca`, o mesmo do painel). Pedir a outra marca responde SEM_PERMISSAO; loja de outra marca, LOJA_NAO_ENCONTRADA. |
| SQL vindo do chat | Não existe ferramenta de SQL. Toda consulta é SQLAlchemy com parâmetros. Texto do usuário é só texto. |
| Alterar estoque ou comprar pelo chat | Não existe ferramenta que grave nada disso. O copiloto e as consultas do site rodam em transação **READ ONLY** (o Postgres recusa INSERT/UPDATE/DELETE) com tempo máximo (`CONSULTA_TIMEOUT_MS`). Opcionalmente, `DATABASE_URL_LEITURA` aponta para um usuário só com SELECT. A única exceção é a consulta de pontos, que lança o vencimento como a página Lupe+ já fazia. |
| Prompt injection (do usuário ou no cadastro da peça) | Resultados de ferramenta são dados; as instruções dizem isso; a autorização não depende do modelo. Pedido para revelar o prompt cai nas regras e não revela. |
| Chave da API | Só no backend (`ANTHROPIC_API_KEY`). Não vai para o frontend, para o banco nem para os logs; os erros do provedor viram mensagens sem a chave. |
| Abuso e custo | Por conversa: 30 mensagens/10 min (site), 60/10 min (copiloto); por IP: 60/10 min; 20 conversas novas/h por IP (429). Mensagem de até 800 caracteres (site) e 1.500 (copiloto). Até 4 idas e voltas e 6 consultas por mensagem; histórico de 12 mensagens. |
| Repetição e simultaneidade | Reenvio com o mesmo `idCliente` devolve a resposta já dada (sem novo custo). Uma mensagem por vez em cada conversa (trava `FOR UPDATE NOWAIT`; a segunda recebe 409). |
| Rastreabilidade | `chamadas_ferramenta`: cada consulta, parâmetros, sucesso, erro e duração, inclusive as recusadas. `consumo_ia`: tokens, custo estimado e status de cada chamada ao modelo. Logs com `request_id`. |

## Memória da conversa e retenção

- O modelo recebe as **12 últimas mensagens** (`IA_HISTORICO_MENSAGENS`) e uma **memória curta** estruturada
  (`conversas_assistente.contexto`): última busca, peças mostradas, peça em foco (com cor e tamanho), loja em foco,
  o que o assistente acabou de oferecer e os últimos eventos (ex.: "adicionou à sacola"). Isso resolve "e no M?",
  "e na outra loja?", "a segunda" sem mandar a conversa inteira.
- Conversa parada há mais de **24 h** (`IA_CONVERSA_EXPIRA_HORAS`) encerra: o site começa outra sozinho.
- **Retenção:** conversas sem atividade há mais de **90 dias** (`IA_RETENCAO_DIAS`) são apagadas pela automação
  `limpeza_conversas` (mensagens e auditoria vão junto; o consumo fica, sem a conversa, para o histórico de custo).
  O chamado de atendimento aberto pelo assistente segue a política do atendimento.
- Dados guardados: o texto que o usuário escreveu e as respostas. O assistente nunca pede CPF, senha ou cartão.

## Banco de dados

Migração `948372ce2329` (`alembic upgrade head`): seis tabelas novas, nenhuma alteração nas existentes.

| Tabela | Para quê |
| --- | --- |
| `conversas_assistente` | Conversa (site ou copiloto), dono, hash da chave, memória curta, status, validade |
| `mensagens_assistente` | Mensagens (usuário, assistente, sistema), blocos da tela, modo, `idCliente` (único por conversa) |
| `chamadas_ferramenta` | Auditoria de cada consulta |
| `consumo_ia` | Tokens, custo estimado, duração e status de cada chamada ao modelo |
| `alertas` | Alertas das automações (uma situação = no máximo um alerta aberto, índice único parcial) |
| `execucoes_automacao` | Log de cada execução das automações |

Ajustes pequenos em código existente: `financeiro.resumo` (campos novos por loja e canal), `fidelidade.lotes_em_aberto`
(leitura dos lotes, sem gravar), `papeis.ACESSO` (módulo `inteligencia`, toda a equipe), o seed (pula tabelas
com id que não é inteiro ao ajustar as sequências) e o teste que conta as tabelas da união (agora soma as seis).

## Automações e alertas

| Automação | Regra | Quem vê |
| --- | --- | --- |
| `estoque_baixo` | Item no mínimo ou zerado que vendeu no local nos últimos `ALERTA_ESTOQUE_BAIXO_JANELA_DIAS` (60). Sem venda recente não alerta: a Vulto tem 2,3 mil itens no mínimo, a maioria sem giro. | estoque |
| `estoque_parado` | Por loja: itens com saldo e sem venda há `ALERTA_ESTOQUE_PARADO_DIAS` (90), com os 10 de maior valor | estoque |
| `sugestoes_transferencia` | Sobra livre acima do dobro do mínimo num local; falta com venda recente em loja da mesma marca. Só sugestão. | transferencias |
| `pontos_a_vencer` | Pontos que vencem em `ALERTA_PONTOS_DIAS` (30), agregados, com quantos clientes aceitam marketing. **Nenhuma mensagem é enviada**: não há canal com consentimento configurado. | financeiro |
| `limpeza_conversas` | Retenção das conversas | — |

Garantias: trava por automação no Postgres (`pg_try_advisory_xact_lock`, vale entre servidores); intervalo mínimo de
1 minuto entre execuções; alerta da mesma situação nunca duplica e é **resolvido sozinho** quando a situação acaba;
alerta descartado pela equipe não volta por 7 dias; log de cada execução com o erro resumido.

Como rodar: `python -m src.automacoes` (todas, para um agendador), `python -m src.automacoes estoque_baixo`, ou o
botão "Atualizar alertas agora" (Administrador) na aba Alertas. No banco local, todas juntas levam cerca de 1,4 s.

## Variáveis de ambiente (backend)

| Variável | Padrão | Uso |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | vazio | Chave da API. Vazio: modo regras |
| `IA_MODELO` | `claude-haiku-5-5` | Modelo (ex.: `claude-sonnet-5-5`, `claude-opus-5-5`) |
| `IA_ESFORCO` | `low` | Quanto o modelo raciocina (low, medium, high) |
| `IA_MAX_TOKENS` | 2048 | Teto de saída por chamada |
| `IA_TIMEOUT_SEGUNDOS` / `IA_MAX_TENTATIVAS` | 25 / 1 | Tempo máximo e novas tentativas do SDK |
| `IA_HISTORICO_MENSAGENS` | 12 | Mensagens anteriores enviadas ao modelo |
| `IA_MAX_RODADAS` / `IA_MAX_FERRAMENTAS` | 4 / 6 | Limites por mensagem |
| `IA_CONVERSA_EXPIRA_HORAS` / `IA_RETENCAO_DIAS` | 24 / 90 | Memória e retenção |
| `IA_RESPOSTAS_DIRETAS` | true | Mensagens simples sem modelo |
| `MCP_TOKEN_VALIDADE_DIAS` / `MCP_TOKENS_POR_USUARIO` | 90 / 5 | Tokens do servidor MCP (decisão 106) |
| `CANAL_WHATSAPP_SEGREDO` / `CANAL_WHATSAPP_MARCA` | vazio / `LORENZI` | A Lúcia no WhatsApp pelo n8n (decisão 108, [whatsapp.md](whatsapp.md)). Vazio: rota desligada |
| `N8N_ENVIO_URL` / `WHATSAPP_CICLO_HORAS` | vazio / 4 | Resposta da equipe pelo WhatsApp e fim do ciclo sem resposta (decisão 117). Vazio: a resposta fica só no painel |
| `DATABASE_URL_LEITURA` | = `DATABASE_URL` | Usuário só leitura (opcional) |
| `CONSULTA_TIMEOUT_MS` | 8000 | Tempo máximo de cada consulta das análises |
| `ALERTA_ESTOQUE_BAIXO_JANELA_DIAS` / `ALERTA_ESTOQUE_PARADO_DIAS` / `ALERTA_PONTOS_DIAS` | 60 / 90 / 30 | Automações |

O frontend não tem variável nova (usa `VITE_API_URL`). Com `VITE_USE_MOCKS=true`, o chat e a página avisam que
precisam da API.

Usuário só leitura no Postgres (opcional, para `DATABASE_URL_LEITURA`):

```sql
CREATE ROLE assistente_leitura LOGIN PASSWORD '<senha forte>';
GRANT CONNECT ON DATABASE casalorenzi TO assistente_leitura;
GRANT USAGE ON SCHEMA public TO assistente_leitura;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO assistente_leitura;
```

## Como rodar e testar

```bash
pip install -r requirements-dev.txt      # inclui o SDK anthropic
alembic upgrade head                     # cria as 6 tabelas
uvicorn src.app:app --reload --port 8000
python -m src.automacoes                 # gera os alertas (uma vez, ou num agendador)
pytest                                   # sem chamar a API do modelo (provedor falso)
pytest tests/test_bateria_lucia.py       # a bateria da Lúcia sem o Claude (decisão 105)
python scripts/avaliar_lucia.py          # a mesma bateria com o Claude de verdade: placar em docs/avaliacao_lucia.md
python scripts/relatorio_lucia.py --desde "2026-10-28 14:00"   # relatório de uma sessão de teste com pessoas
```

Para ligar o modelo: `ANTHROPIC_API_KEY=...` no `.env` do backend (e reiniciar). Sem ela tudo funciona pelas regras.

Testes dos assistentes: `tests/test_assistente_busca.py`, `test_assistente_site.py`, `test_copiloto.py`,
`test_automacoes.py` e `test_ia_provedor.py` (o SDK contra um transporte HTTP simulado, sem rede).

## Deploy

1. **Render (API):** o start command já roda `alembic upgrade head`; o deploy cria as tabelas sozinho.
   Em **Environment**, acrescente `ANTHROPIC_API_KEY` (e, se quiser, `IA_MODELO`). O `render.yaml` não foi alterado
   (mudança de configuração de produção depende de autorização): se a equipe preferir, acrescente lá
   `- key: ANTHROPIC_API_KEY` com `sync: false`.
2. **Vercel (site):** só o deploy do frontend; nenhuma variável nova.
3. **Automações:** o plano grátis do Render não tem cron. Opções: um *Cron Job* do Render (mínimo de US$ 1/mês)
   com `python -m src.automacoes`, um agendamento no GitHub Actions apontando para o mesmo `DATABASE_URL`, ou o
   botão do Administrador.
4. **Conferir:** `GET /api/health`; abrir o site e o chat; no painel, `/inteligencia` (aba Uso mostra o modo LLM e o modelo).

O CORS não muda (as rotas novas são da mesma API). O limite de mensagens fica na memória do processo, como o do
"esqueci a senha": vale para uma instância (com várias, levar para o banco ou um Redis).

## Contas de teste

As do README (Helena: Administradora do grupo; Otávio: Administrador Casa Lorenzi; Paula: Administradora Vulto;
Rafael: Lojista; Diego: Operador; clientes como mariana.costa@gmail.com). A senha de demonstração está em
`src/database/seed/dados.py` (`SENHA_DEMO`). Não use essas contas em produção.

## Limitações conhecidas

- **Verificador de números:** lê algarismos ("1.200", "R$ 60,00", "12/11", "10h") e números por extenso com unidade
  ("mil pontos"); um número escrito de outro jeito ("um milhão e meio") não é conferido, e o prompt pede algarismos.
  Número sem unidade numa fonte (o "300" de um campo) vale para qualquer unidade na resposta.
- **Dados até 03/10/2026** no banco local: "quanto faturamos hoje" responde R$ 0,00 e diz até quando vão os dados.
- **Passivo do Lupe+ no banco local:** a consulta oficial dá 3.373.251 pontos em 01/10/2026; a documentação da
  união fala em 4.015.759. A carga local parece anterior à correção do passivo; o copiloto mostra o que está no banco.
- O entendimento pelas regras cobre as perguntas comuns, não linguagem livre; com o modelo ligado, as regras viram
  só contingência e respostas diretas.
- Disponibilidade por loja é "disponível / últimas unidades / indisponível"; reserva em loja não existe (o
  atendimento tem o tipo "Reserva em outra loja").
- Notificações externas (e-mail/WhatsApp de pontos a vencer) não foram ligadas: falta canal com consentimento.
- Limite de mensagens por IP na memória do processo (uma instância).
- O chamado aberto pelo assistente entra como Casa Lorenzi quando não há pedido (regra existente do atendimento).

## Próximos passos (P2)

WhatsApp (Cloud API) reaproveitando o mesmo orquestrador; previsão de demanda para as transferências; busca
semântica (embeddings) se o catálogo crescer muito além das ~190 peças; envio dos avisos de pontos com consentimento.
