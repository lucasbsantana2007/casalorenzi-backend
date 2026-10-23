# Banco pronto para a união com a Vulto

A migração `f060e5b0d838` (`alembic/versions/2026_10_21_1700-…`) prepara o banco da Casa Lorenzi para
receber os dados da Vulto. **Ela não carrega nenhum dado da Vulto:** muda só a estrutura. O que já existe
continua funcionando igual e passa a ser da marca `LORENZI`.

A fonte da carga é o repositório `copy.vulto-legado-back` (branch `main`):

- `data/vulto_corrigido.db`: o banco da Vulto consertado (vendas, itens, pontos, estoque em 01/10, entradas);
- tabelas `*_padronizadas` do `data/vulto.db`: o que não existe no banco consertado (catálogo, clientes,
  atendimentos, histórico do estoque, registro de decisões).

As decisões tomadas na preparação (66 a 72), que fecham as pendências das planilhas, estão em
[registro_decisoes_uniao.md](registro_decisoes_uniao.md).

## O que mudou, em uma frase por tabela

**De 23 para 27 tabelas.** Nenhuma tabela foi apagada: todas as 23 da Casa Lorenzi continuam com papel
na plataforma unificada, e cada domínio da Vulto (catálogo, estoque, vendas, clientes, atendimento) cabe
nelas com colunas novas. Só o Vulto+ e o controle da migração precisaram de tabelas novas. Não há tabela
de pendências: cada pendência das planilhas virou uma decisão (66 a 72).

### Tabelas novas (4)

| Tabela | Para quê |
| --- | --- |
| `fornecedores` | Um registro por fornecedor (as notas da Vulto escrevem o mesmo de vários jeitos: "serra azul", "MALHARIA SERRA AZUL LTDA") |
| `movimentos_pontos` | Extrato do Vulto+: cada crédito, resgate, estorno, ajuste e vencimento, com o saldo resultante (nunca negativo). O saldo do cliente é o do último movimento; o passivo é a soma dos saldos |
| `decisoes_migracao` | O registro de decisões, com as colunas pedidas pela diretoria (o que, onde, quantos, o que decidimos, por quê, impacto), tipo e situação (`A_DECIDIR` para as decisões 40 e 41) |
| `de_para` | De onde veio cada registro migrado (`vulto_corrigido.db:vendas` + id → `pedidos` + id). Rastreio e proteção contra carga em dobro |

### Tabelas alteradas (12)

| Tabela | O que entrou | Por quê (dado da Vulto que pede isso) |
| --- | --- | --- |
| `lojas` | `marca` (LORENZI, VULTO), `tipo` (LOJA, CD) | O CD Cajamar guarda estoque, mas não atende o público. Site e app **não** viram lojas (eram as "lojas" 5 e 6 de estoque fantasma, decisão 32) |
| `produtos` | `marca`, `codigo_modelo`, `colecao`, `fornecedor_id`, `fornecedor_estimado` | Catálogo da Vulto por modelo e coleção. O código do modelo não é único: a Vulto reaproveitou MOL-002 e TRI-001 em peças diferentes |
| `variacoes` | `ean` (único, 13 dígitos), `codigo_cd` (único), `preco` (preço próprio do SKU), `custo_estimado`, `status` (ATIVO, DESCONTINUADO, FORA_DO_CATALOGO, SO_HISTORICO), `observacao` | Código do CD e EAN de cada SKU (31 EAN internos, que começam com 2: decisão 71); 30 custos sem nota, estimados (decisão 70); peças de 2024 com o último preço vendido por SKU (decisão 39); o "DIVERSO" só de histórico (decisão 37) |
| `clientes` | e-mail opcional e **não único**; `canal_cadastro`, `aceita_marketing`, `atualizar_cadastro`, `observacao` | 765 clientes sem e-mail; 20 e-mails usados por 2 pessoas da mesma família (decisão 53); consentimento LGPD (decisão 20); CPF inválido obriga a atualizar o cadastro no próximo login (decisão 52) |
| `pedidos` | canal `App`; `cliente_id` opcional; `tipo` (VENDA, TROCA); `desconto`; `status_origem`; `vendedor_nome`; `cliente_contato`; `observacao`; o banco confere `total = subtotal − desconto + frete` | Venda de balcão sem cliente ("consumidor"); troca não é receita (decisão 16); "Sem status" conta como venda (decisão 15); vendedor ambíguo "Rafael Lima ou Rafaela Couto" (decisão 13) |
| `itens_pedido` | quantidade > 0 e preço ≥ 0 | A devolução da Vulto era item negativo; aqui ela vai para `devolucoes` |
| `pagamentos` | forma `NAO_INFORMADO`, status `CHARGEBACK` | A Vulto só registrou a forma de pagamento na planilha manual da Batel; 38 chargebacks |
| `devolucoes` | `variacao_id` (a peça que voltou, preenchida nas devoluções que já existiam); pedido, item e usuário opcionais | Só 91 das 201 devoluções da Vulto citam a venda original (decisão 12) |
| `estoques` | quantidade nunca negativa | O "estoque de ficção" da diretoria; o estoque consertado da Vulto não tem negativo |
| `movimentacoes` | tipos `SALDO_INICIAL`, `INVENTARIO`, `AVARIA`; `pedido_id`, `nota_fiscal`, `custo_unitario`, `estimado`; saldo nunca negativo | O histórico reconstruído da Vulto (decisões 44, 45 e 54): saldo inicial estimado, ajuste da contagem física, avaria contada e estimada |
| `atendimentos` | `marca`, `canal` (SITE, WHATSAPP, INSTAGRAM, EMAIL), `contato`, `contato_nome`, `pedido_citado`; cliente e loja opcionais | 765 atendimentos sem cliente identificado; 216 citam um pedido que não existe; os sem venda ficam no SAC central (sem loja) |
| `mensagens` | `autor_nome` | Atendentes da ferramenta da Vulto (Júlia, Renata, Marcos, Time Insta) não são usuários da plataforma |

As listas de valores ficam em `src/entities` (`marca.py`, `loja.py`, `pedido.py`, `pagamento.py`,
`produto.py`, `estoque.py`, `atendimento.py`, `fidelidade.py`, `migracao.py`) e o banco só aceita esses
valores (`CheckConstraint`).

## De/para: de onde vem cada dado da Vulto

### Lojas (`vulto_corrigido.db:lojas`)

| Vulto | Plataforma |
| --- | --- |
| 1 Pinheiros, 2 Eldorado (SP), 3 Savassi (MG), 4 Batel (PR) | `lojas`, marca VULTO, tipo LOJA (a UF vem da cidade) |
| 5 E-commerce, 6 App | não viram loja: são o `canal` do pedido (`E-commerce`, `App`) |
| 7 CD Cajamar (SP) | `lojas`, marca VULTO, tipo CD |

### Catálogo (`vulto.db:produtos_padronizados`, 867 linhas)

| Vulto | Plataforma |
| --- | --- |
| `categoria` | `categorias` (Acessórios, Saias, Tricô e Vestidos já existem; entram as outras 7) |
| `fornecedor` | `fornecedores` (6) |
| um produto por (`modelo`, `produto`) — 176 | `produtos`: `nome`, `codigo_modelo`, `colecao`, `fornecedor_id`, marca VULTO; `preco_base` = preço do modelo; `estacao` pela coleção (Verão 26 → Verão, Atemporais → Atemporal) |
| um SKU por linha — 866 + `DIVERSO` | `variacoes`: `sku`, `tamanho`, `cor`, `preco_custo` (custo), `ean`, `codigo_cd`, `status`, `observacao` (obs); `preco` só quando difere do produto |
| obs "Custo estimado / de referência" | com nota do próprio SKU em `vulto_corrigido.db:entradas_estoque` (96): `preco_custo` = último custo de nota; sem nota (30): o estimado, com `custo_estimado = true` (decisão 70) |
| preço de ACE-004, CAL-008, CAL-020 e CMS-003 | R$ 10 a mais em todo o modelo, para a margem mínima de 50% com o custo de nota (decisão 70) |
| obs "Código CD provisório" | o código vale como está: já era usado nas vendas e na contagem (decisão 69) |
| obs "Fornecedor estimado" | `produtos.fornecedor_estimado = true` |
| status Ativo / Descontinuado / Fora do catálogo 2026 / Só histórico | ATIVO / DESCONTINUADO / FORA_DO_CATALOGO / SO_HISTORICO |

### Clientes (`vulto.db:clientes_padronizados`, 3.142)

| Vulto | Plataforma |
| --- | --- |
| `cpf` (000.000.000-00) | `clientes.cpf` (só dígitos). **Mesmo CPF da Casa Lorenzi = o mesmo cliente** (um registro só) |
| `nome`, `e_mail`, `telefone` | `nome`, `email` (vazio → nulo), `telefone` |
| `data_de_cadastro` | `cliente_desde` (sem data: a do primeiro movimento de pontos) |
| `loja_de_cadastro` | Pinheiros/Eldorado/Savassi/Batel → `loja_preferida_id` + `canal_cadastro` = Loja física; Site → E-commerce; App → App |
| `aceita_mensagem` = Sim | `aceita_marketing = true` |
| origem "CPF inválido" ou nome "(sem cadastro na planilha)" | `atualizar_cadastro = true` |
| `obs` | `observacao` |
| `categoria` | não é gravada: sai do saldo (`categoria_pelo_saldo` em `src/entities/fidelidade.py`) |
| "Dados válidos" (Sim/Não) | não é gravado: sai do CPF, do e-mail e do telefone (`dadosValidos` e `problemasCadastro` na API; decisão 72) |

### Vendas (`vulto_corrigido.db:vendas` + `itens_venda`; tipo e status de `vulto.db:vendas_padronizadas`)

| Vulto | Plataforma |
| --- | --- |
| `pedido_externo` (S…, APP-…), `BATEL-n` ou o id da loja | `pedidos.numero` (ex.: `S100234`, `APP-7001205`, `BATEL-12`, `VLT-1343`) |
| `cliente_ref` | `cliente_id` pelo CPF (ou pelo e-mail único); sem cadastro, o texto vai para `cliente_contato` |
| `loja_id` 1–4 | a loja da Vulto; 5 e 6 → CD Cajamar (obs "SFS PIN" → Pinheiros) |
| canal pela loja | Loja física / E-commerce / App |
| tipo Troca | `tipo = TROCA` (fora da receita) |
| status Concluída, Sem status | `ENTREGUE` (pagamento APROVADO) |
| status Cancelada, Aguardando pagamento, Estornada | `CANCELADO` (pagamento ESTORNADO) |
| status Chargeback | `CANCELADO` (pagamento CHARGEBACK) |
| status como veio | `status_origem` |
| `total`, `desconto`, `frete` | `subtotal` (soma dos itens), `desconto`, `frete_valor`, `total` |
| `vendedor`, `obs` | `vendedor_nome`, `observacao` |
| itens | `itens_pedido` (SKU do catálogo → `variacao_id`) |
| tipo Devolução (201) | **não vira pedido**: uma linha em `devolucoes` por peça, com `variacao_id`, a loja, o valor, `pedido_id`/`item_pedido_id` da venda original quando a obs cita o número. As 22 devoluções com status Estornada não contam no faturamento (decisão a registrar na carga) |
| forma de pagamento | `pagamentos.metodo = NAO_INFORMADO`; Batel manual: Pix → PIX, Crédito/Crédito 2x → CARTAO (1x/2x), Débito → DEBITO, Dinheiro → DINHEIRO |

Pedidos de teste, gravações duplicadas e relançamentos da Batel já não estão no banco consertado.

### Estoque

| Vulto | Plataforma |
| --- | --- |
| `vulto_corrigido.db:estoque` (posição de 01/10/2026) | `estoques` (loja + variação); `quantidade_min = 2` (`config.estoque_minimo`) |
| `vulto.db:estoque_historico` (59.781 movimentos) | `movimentacoes`, com `saldo_resultante` e `criado_em` = data do movimento |
| Saldo inicial (reconstruído) | `SALDO_INICIAL`, `estimado = true` |
| Venda / Troca (peça nova) | `VENDA` com `pedido_id` |
| Devolução | `DEVOLUCAO` |
| Compra (NF) | `ENTRADA` com `nota_fiscal` e `custo_unitario` (de `entradas_estoque`) |
| Envio p/ … / Recebido de … | `TRANSFERENCIA_SAIDA` / `TRANSFERENCIA_ENTRADA` |
| Ajuste de inventário (contagem física) | `INVENTARIO` |
| Ajuste: vendeu mais que o contado | `AJUSTE` |
| Avaria (contada na Pinheiros) / Avaria estimada | `AVARIA` (a estimada com `estimado = true`) |

### Vulto+ (`vulto_corrigido.db:pontos_mov`, 15.018)

| Vulto | Plataforma (`movimentos_pontos`) |
| --- | --- |
| `cpf` | `cliente_id` |
| C (crédito) | `CREDITO`, `vence_em` = 12 meses depois |
| D (resgate, gravado positivo) | `RESGATE`, quantidade negativa; `valor_desconto` = o desconto da venda do cliente no dia, quando ela existe; sem venda, o lançado na aba Resgates (decisão 68) |
| E (estorno) | `ESTORNO` |
| AJ "saldo da planilha congelado em 01/01/2025" | `SALDO_INICIAL` |
| AJ "pontos vencidos em 01/10/2026" | `VENCIMENTO` |
| outros AJ (cortesia, bônus, resgate maior que o saldo) | `AJUSTE` |
| `compra_id` | `pedido_id` (pela venda ligada à compra) |
| saldo | `saldo_resultante`, acumulado por cliente em ordem de data e, **no mesmo instante, entradas antes das saídas**: o ajuste "resgate maior que o saldo" tem o mesmo horário do resgate, e na ordem do id o saldo ficaria negativo por um instante em 36 movimentos (31 clientes), o que o banco recusa |
| resgates sem cliente (aba Pendências) | não entram no extrato de ninguém: decisões 66 e 67 (o passivo não muda) |

### Atendimento (`vulto.db:atendimentos_padronizados`, 1.647)

| Vulto | Plataforma |
| --- | --- |
| `id` | `protocolo` (ex.: `VLT-40001`) |
| `canal` | WHATSAPP / INSTAGRAM / EMAIL; `marca = VULTO` |
| `cliente_cpf` | `cliente_id` |
| `contato`, `nome` | `contato`, `contato_nome` ("Não informado" → nulo) |
| `pedido` / `id_venda` | `pedido_citado` sempre; `pedido_id` só quando a venda confere (decisão 43) |
| `loja_id` | 1–4 → a loja; 5 e 6 → a loja da venda ligada, ou nenhuma (SAC central) |
| `status` | Aberto / Em andamento / Aguardando cliente / Resolvido → ABERTO / EM_ANDAMENTO / AGUARDANDO_CLIENTE / CONCLUIDO |
| `assunto` | `tipo_solicitacao_id`: Troca, Devolução, Entrega e rastreio, Produto e estoque → os tipos que já existem; Vulto+ (pontos), Pagamento, Cancelamento, Lojas físicas, Spam / teste → tipos novos |
| `mensagem_cliente` | `mensagens` CLIENTE |
| `resposta_atendente` + `atendente` | `mensagens` ATENDENTE com `autor_nome` ("Bot Vulto" → SISTEMA) |

### O que não vem

- `funcionarios`: as senhas estão em texto puro e não há e-mail. O nome do vendedor fica no pedido
  (`vendedor_nome`); quem for usar a plataforma é cadastrado pelo painel (convite por e-mail).
- `config.senha_master`: falha de segurança, não é copiada.
- `compras`: só serve para ligar os pontos às vendas.

## Os três números, direto do banco (depois da carga)

```sql
-- 1. Faturamento da Vulto por mês, loja e canal: vendas (não trocas, não canceladas) menos devoluções
SELECT date_trunc('month', p.criado_em AT TIME ZONE 'America/Sao_Paulo') AS mes, l.nome, p.canal, SUM(p.total)
FROM pedidos p JOIN lojas l ON l.id = p.loja_id
WHERE l.marca = 'VULTO' AND p.tipo = 'VENDA' AND p.status <> 'CANCELADO'
GROUP BY 1, 2, 3;
-- menos SUM(valor_devolvido) das devoluções nas lojas da Vulto, pelo mês de criada_em
-- (canal da devolução: loja física → Loja física; CD Cajamar → E-commerce)

-- 2. Estoque em 01/10/2026 por loja/CD e produto
SELECT l.nome, v.sku, e.quantidade FROM estoques e
JOIN lojas l ON l.id = e.loja_id JOIN variacoes v ON v.id = e.variacao_id
WHERE l.marca = 'VULTO';

-- 3. Passivo do Vulto+ em 01/10/2026: o último saldo de cada cliente até a data
SELECT SUM(saldo_resultante) AS pontos, SUM(saldo_resultante) * 0.05 AS reais FROM (
  SELECT DISTINCT ON (cliente_id) saldo_resultante FROM movimentos_pontos
  WHERE criado_em < '2026-10-02 00:00-03' ORDER BY cliente_id, criado_em DESC, id DESC
) ultimo;
```

A carga está certa quando esses números baterem com os do banco consertado: **R$ 6.498.071,30**,
**15.033 peças** e **3.373.251 pontos (R$ 168.662,55)**.

**Carga de teste (21/10/2026).** Os dados reais da Vulto foram carregados num banco temporário com
este schema e o de/para acima, para provar que a estrutura os recebe. Nenhuma restrição recusou dado
(fora a ordem dos pontos, já descrita na tabela do Vulto+), e as três consultas deram exatamente
R$ 6.498.071,30, 15.033 peças e 3.373.251 pontos. As telas de pedidos, atendimentos, clientes, estoque,
posição em data, devoluções, dashboard e financeiro responderam sem erro com os dados carregados.

## A carga (`python -m src.migracao_vulto`)

O código está em `src/migracao_vulto/carga.py` e segue o de/para acima, com as decisões 66 a 77 aplicadas.
Precisa do repositório da Vulto na máquina e do `openpyxl` (`pip install -r requirements-dev.txt`).

```bash
python -m src.migracao_vulto --origem ../copy.vulto-legado-back --simular   # roda, confere e desfaz
python -m src.migracao_vulto --origem ../copy.vulto-legado-back             # grava, se tudo bater
# no banco do Render: DATABASE_URL="<External Database URL>" python -m src.migracao_vulto --origem ...
```

- Uma transação só. Antes de gravar, confere os três números e as contagens contra a origem; se algo não
  bater, desfaz tudo e diz o quê.
- Roda uma vez só: com registros da Vulto no `de_para`, recusa.
- Grava em lote, até mil linhas por comando: cerca de 16 segundos no banco local e 2 minutos no do Render.

**Conferido no banco local (21/10/2026):** as 130 combinações de mês × loja × canal do faturamento são
iguais às da origem (Loja física R$ 3.891.612,41 · E-commerce R$ 1.682.985,19 · App R$ 923.473,70); as
3.388 combinações de loja × SKU do estoque em 01/10 também, e a posição em data passada bate com o histórico;
o saldo de pontos de cada um dos 3.142 clientes é o da origem.

**Devolução por canal:** o canal da devolução é o da loja em que ela foi registrada (loja física → Loja
física; CD Cajamar → E-commerce), a mesma regra da Vulto (decisão 7). As 26 devoluções do site não citam a
venda e ficam no CD; o app não teve devolução.

**Depois da carga:** `python -m src.database.seed --recriar` apaga tudo, inclusive a Vulto. Não rode no banco
com os dados reais.

## O que já mudou na plataforma

- **Um site, uma vitrine por marca:** a Casa Lorenzi fica no início e a Vulto em `/vulto`. A vitrine e a
  página Lojas pedem a marca (`/produtos?marca=VULTO`, `/lojas?marca=VULTO`); sem ela, o visitante
  recebe a Lorenzi, e a equipe logada, as duas. A página da peça abre as duas marcas. Sacola, login,
  checkout e Vulto+ são compartilhados; a peça sai de uma loja (ou do CD) da marca dela.
- **Estoque zerado automático só dentro da marca:** produto novo nasce nas lojas da marca dele; loja nova,
  com as peças da marca dela.
- **Financeiro com a regra da diretoria:** receita = total dos pedidos de venda não cancelados (itens −
  desconto + frete); troca não é receita; devolução sem pedido de origem entra pela loja em que foi
  registrada; `receitaLiquida` = receita − devoluções. Só com as lojas da Vulto, de jan/2025 a set/2026, a
  tela dá R$ 6.498.071,30 (Loja física R$ 3.891.612,41 · E-commerce R$ 1.682.985,19 · App R$ 923.473,70).
- **Login com e-mail ou CPF** (decisão 53), sempre com a senha. E-mail usado por mais de um cliente não
  entra: essas pessoas entram pelo CPF. O "esqueci a senha" também aceita o CPF e manda o link para o
  e-mail da conta. Quem não tem e-mail (747 clientes que vieram só do sistema de pontos) ganha acesso pelo
  atendimento: `POST /clientes/{cpf}/acesso` cadastra o e-mail e manda o link para criar a senha.
- O número dos pedidos do site continua na sequência `CL-` com `APP-7001205` no banco; e-mail de mais de um
  cliente não entra nem é reaproveitado em conta nova; pedido e atendimento sem cliente aparecem no painel
  e na busca; o checkout cobra o preço próprio do SKU.

## O que fica para depois

- **Tela de "atualizar cadastro" no primeiro login** (decisão 52): o banco já marca quem precisa
  (`clientes.atualizar_cadastro`) e a API mostra o motivo (`problemasCadastro`); falta a tela no site.
- **Desempenho:** a lista de pedidos e o financeiro carregam todos os pedidos na memória; com os 18 mil
  da Vulto, levam cerca de 3 segundos. Vale filtrar e somar no banco.
- **Branch `feat/resgate-pontos-vulto-mais`:** cria a mesma tabela `movimentos_pontos` e a coluna
  `pedidos.desconto`. Antes de juntar, a migração dela sai e o código passa a usar as desta.
