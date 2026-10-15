# Registro de Decisões — Migração Vulto → Casa Lorenzi

Cada problema encontrado nos dados ou nas regras da Vulto, o que decidimos e quanto isso muda o número final.
Gerado por `python -m src.relatorios.registro_decisoes` a partir da tabela `migracao_ocorrencias` (cada
registro problemático da migração tem uma ocorrência) e dos números da diretoria; não edite à mão.

## Os três números

- **Faturamento da Vulto (jan/2025 a set/2026):** R$ 6.444.100,77 sem frete (R$ 6.499.349,47 com frete), em 17.018 vendas. O relatório do sistema da Vulto dizia R$ 94.580.496,26: a diferença é quase toda o valor em centavos do app somado como reais. Margem: R$ 6.106.229,55 a R$ 6.551.482,11.
- **Estoque em 01/10/2026:** 15.248 peças em 3.433 itens com saldo (loja × peça). O saldo em 01/10/2026 é a contagem de set/26 mais os movimentos depois dela; o sistema da Vulto dizia 33.608 peças. Margem: 15.248 a 15.292 peças.
- **Passivo do Vulto+ em 01/10/2026:** 3.352.597 pontos = R$ 167.629,85 pela regra vigente, numa faixa de R$ 160.602,65 a R$ 425.863,10.

## Problemas nos dados

Fizemos X por causa de Y, e isso muda o número em Z: cada linha diz o que encontramos, onde, quantos registros
afeta, o que decidimos, por quê e o impacto. Os códigos entre colchetes levam ao apêndice.

| # | O que encontramos | Onde (arquivo / tabela / campo) | Quantos registros afeta | O que decidimos fazer | Por quê | Impacto no número final |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Valores em centavos × reais, e vírgula decimal [`VALOR_EM_CENTAVOS`, `CREDITO_INFLADO_BUG_APP`] | `vulto.db`: `vendas.total`, `itens_venda.preco_unit`, `compras.valor` (app); planilhas com "1.234,56" | 2.288 vendas em centavos; 15.269 valores com vírgula decimal | Centavos detectados pela razão com o preço do catálogo e convertidos; vírgula decimal e milhar com ponto lidos por `normalizacao.dinheiro`. | O app grava em centavos ("19081" = R$ 190,81) e o sistema somava como reais; o preço do catálogo diz qual escala é a certa. | Faturamento: −R$ 87.514.831,80 na ponte (o relatório da Vulto estava inflado). Pontos: −1.553.967 pontos em 31 créditos do bug do app v3.4. |
| 2 | Datas em vários formatos, inclusive UTC com `Z` | `vendas.criado_em`, `compras.criado_em`, `pontos_mov.criado_em`, `atendimentos.csv:data_hora`, aba Resgates | 10 formatos diferentes; 22.296 datas em UTC (`Z`) | Uma função (`normalizacao.data_hora`) lê todos (ISO com e sem `Z`, dd/mm/aaaa, dd/mm/aa, "set/23", número de série do Excel); sem fuso = Brasília; `Z` = UTC, convertido para Brasília. | Site e app gravam em UTC: somar pelo dia sem converter joga a venda das 21h às 24h para o dia (e às vezes o mês) seguinte. | Faturamento: +R$ 529,70 na ponte (vendas que mudam de mês). |
| 3 | Canal com várias grafias; texto do canal × loja da venda [`CANAL_TEXTO_DIVERGE`, `LOJA_VIRTUAL_VIRA_CANAL`] | `vendas.canal` × `vendas.loja_id` (lojas 5 = site e 6 = app no legado) | 13 grafias; 218 vendas com o texto contradizendo a loja | Canal pela loja do legado (1 a 4 loja física, 5 E-commerce, 6 App); site e app viraram canais, não lojas, e expedem do CD Cajamar. | A loja é preenchida pelo sistema; o texto é digitado e varia. | Nenhum no total: muda a divisão por canal dessas 218 vendas. |
| 4 | Status com várias grafias, inclusive vazio [`STATUS_VAZIO_COMO_PAGO`] | `vendas.status` | 10 grafias; 949 vendas com status vazio | Status mapeado para o da plataforma; vazio = pago. | As vendas com status vazio são de lojas físicas (jan–fev/25), com itens e conta fechando: o PDV deixava em branco o que era pago. | Faturamento: as 918 vendas com status vazio somam R$ 315.404,23; se alguma não foi paga, o número cai (é o principal item da margem). |
| 5 | Trocas lançadas como venda nova [`TROCA_FORA_DA_RECEITA`] | `vendas` (obs "troca", valor cheio) | 328 trocas | Viram pedido `TROCA`: baixam o estoque da peça nova, mas ficam fora da receita. | A venda original já contou; somar a troca conta a mesma receita duas vezes. | Faturamento: −R$ 74.447,20 na ponte. |
| 6 | Devoluções com valor negativo [`DEVOLUCAO_REFERENCIA`, `DEVOLUCAO_CLIENTE`, `DEVOLUCAO_SEM_ORIGEM`] | `vendas` com total negativo | 90 ligadas pela obs, 87 pela última compra do cliente, 24 sem origem | Viram `devolucoes` ligadas à venda (a citada na obs; senão, a última compra do mesmo cliente com a mesma peça; senão, sem origem) e devolvem a peça ao estoque. | Devolução não é venda negativa: é a saída da receita na data em que aconteceu. | Faturamento líquido: −R$ 38.821,85 de devoluções na data em que aconteceram; na ponte, R$ 0,00 (o relatório da Vulto já descontava). |
| 7 | Frete: receita ou repasse [`FRETE_EMBUTIDO_NO_TOTAL`] | `vendas.frete` (e o app somando o frete no total sem gravar na coluna) | 780 vendas com o frete embutido no total | Frete separado do total; o faturamento oficial é sem frete (aprovado), com o frete como um passo da ponte. | É assim que o financeiro da Casa Lorenzi já calcula a receita (pelos itens): o frete é repasse à transportadora. | Faturamento: −R$ 55.248,70 na ponte (R$ 6.444.100,77 sem frete; R$ 6.499.349,47 com frete). |
| 8 | Batel sem PDV (02 a 22/03/2026), com relançamento parcial [`BATEL_VENDA_MANUAL`, `BATEL_JA_RELANCADA`, `BATEL_RELANCADA_REDATADA`, `BATEL_DATA_INVERTIDA`, `BATEL_RELANCADA_SEM_PAR`, `BATEL_TOTAL_DA_PLANILHA`, `BATEL_PIX_FALTANDO`] | `vendas_batel_MANUAL_marco.xlsx` × `vulto.db:vendas` | 59 vendas só na planilha; 13 já relançadas; 26 com dia e mês trocados | Entra a planilha manual menos o que foi relançado no sistema (mesmo CPF e valor); a relançada volta para a data real; datas com dia e mês trocados pelo Excel, destrocadas. | Sem isso, março da Batel some do sistema; com os dois, conta em dobro. | Faturamento: +R$ 22.466,99 na ponte; a planilha manual é parte da margem. |
| 9 | Servidor do PDV do Eldorado trocado (fev/26) [`ELDORADO_SERVIDOR_TROCADO`] | `vendas.criado_em` da loja 2 | 32 vendas que o sistema da Vulto contava no dia seguinte | Desde a troca, as datas do Eldorado vêm em UTC (`Z`): convertidas para Brasília. | O servidor novo grava em UTC; as vendas da noite caíam no dia seguinte. | Faturamento: entra no passo de fuso horário (+R$ 529,70). |
| 10 | Ship from store baixando o estoque do site [`SHIP_FROM_STORE`] | `vendas` do site com obs "sfs pinheiros" | 56 pedidos | Pedido do site que saiu de Pinheiros: a loja de expedição é Pinheiros (baixa de lá), o canal continua E-commerce. | O sistema da Vulto baixava da "loja" site, que não tem estoque físico. | Estoque: as peças saem de Pinheiros, não do CD. Faturamento: nenhum. |
| 11 | Estoque da Vulto com 1.156 linhas negativas [`ESTOQUE_DO_LEGADO_SO_COMPARACAO`, `ESTOQUE_DAS_LOJAS_VIRTUAIS`] | `vulto.db:estoque` | 7.130 linhas, 1.156 negativas; 12.694 peças nas "lojas" 5 e 6 | A tabela não entra: o estoque é reconstruído movimento a movimento e a tabela só serve de comparação. | Sem histórico e com negativos, não dá para confiar no saldo; as vendas online baixavam das lojas 5 e 6. | Estoque em 01/10/2026: 15.248 peças (o sistema da Vulto dizia 33.608). |
| 12 | Estoque sem histórico [`ABERTURA_ESTIMADA`, `CONTAGEM_DIFERE_DO_RECONSTRUIDO`, `TRANSFERENCIA_DOS_DOIS_LADOS`, `TRANSFERENCIA_ENTRE_LOJAS`, `CONTAGEM_SEM_DATA`, `SALDO_NEGATIVO_DEPOIS_DA_CONTAGEM`] | `vulto.db:entradas_estoque`, vendas, contagem de set/26 | 2.830 itens com contagem diferente do reconstruído; 5.290 peças de transferências anotadas dos dois lados | Histórico reconstruído (notas de entrada, transferências contadas uma vez, vendas e devoluções); a contagem de set/26 é a âncora; a abertura em 01/01/2025 é a menor que deixa o histórico sem negativo. | É o único jeito de ter o saldo em qualquer data; a contagem é o dado mais confiável. | Estoque: abertura estimada de 20.911 peças; ajuste da contagem de +4.790 peças. O saldo de 01/10/2026 é o contado mais os movimentos depois. |
| 13 | Contagem da Savassi por modelo [`SAVASSI_CONTAGEM_POR_MODELO`, `SAVASSI_MODELO_SEM_PRODUTO`] | `contagem_inventario_set26.xlsx:savassi_por_modelo` | 161 modelos | O total de cada modelo foi rateado entre as variações pelo mix de entradas e vendas. | Sem a cor e o tamanho, não dá para saber qual variação foi contada. | Estoque: 2.114 peças na Savassi — total exato, cor e tamanho estimados. |
| 14 | SKU em vários formatos e código reaproveitado entre coleções [`CODIGO_REAPROVEITADO`, `GRAFIA_DE_SKU_ILEGIVEL`, `GRAFIA_SEM_PRODUTO`, `LINHA_VARIOS_TAMANHOS`, `VARIACAO_FORA_DO_CATALOGO`, `VENDIDO_SEM_CADASTRO`, `EAN_INVALIDO`, `EAN_DIVERGE_ENTRE_COLECOES`, `CONTAGEM_SKU_DIGITADO_ERRADO`, `CONTAGEM_SKU_ILEGIVEL`] | `catalogo.xlsx`, `itens_venda.sku`, `entradas_estoque.sku`, contagens | 2.330 grafias guardadas como alias; 6 códigos reaproveitados; 13 grafias ilegíveis | SKU canônico `VLT-CAT-NNN-COR-TAM`; cada grafia vira alias com vigência; peça de 2024 com código reaproveitado vira outro produto, inativo, com SKU terminado em `-2024`. | As vendas antigas precisam apontar para a peça certa da época. | Nenhum direto no total: é o que liga cada venda, entrada e contagem à peça certa. |
| 15 | Conflito de preço: o da coleção mais nova × o menor [`PRECO_ENTRE_COLECOES`, `PRECO_DIVERGE_NA_ABA`, `PRECO_A_REVISAR`] | `catalogo.xlsx` (peça em mais de uma aba) | 22 peças | Vale o menor preço (Operações/Financeiro, por causa do Procon); o parâmetro aceita o da coleção mais nova. | Cobrar mais do que o anunciado em qualquer coleção vigente é risco no Procon. | Catálogo: +R$ 260,00 no preço de venda. Faturamento: nenhum (a venda vale pelo preço vendido). |
| 16 | Conflito de custo: último × médio [`CUSTO_DA_NOTA`] | `catalogo.xlsx:custo`, notas de entrada | 71 peças sem custo na planilha | Guardamos os dois: `preco_custo` = último custo (o da aba mais recente; sem ele, a última nota) e `custo_medio` = média ponderada das notas de entrada. | Compras usa o último para precificar; o Financeiro, o médio para a margem. | Nenhum no faturamento; muda a margem bruta conforme o custo escolhido. |
| 17 | Promoções não registradas [`DESCONTO_NAO_REGISTRADO`, `TOTAL_NAO_FECHA`] | `itens_venda.preco_unit` abaixo do preço do catálogo; total menor que a soma dos itens | 3.988 itens vendidos abaixo do catálogo; 3 vendas com desconto não registrado | A venda vale pelo preço praticado; diferença entre o total e os itens vira desconto. | A receita é o que o cliente pagou; o preço de catálogo é referência. | Faturamento: nenhum (já é o preço vendido). Diferença para o preço de catálogo: R$ 299.881,87. |
| 18 | Clientes duplicados; `cliente_ref` misturando CPF, e-mail e telefone [`CADASTROS_FUNDIDOS`, `IDENTIFICADORES_LIGADOS`, `REFERENCIA_AMBIGUA`, `REFERENCIA_SEM_CLIENTE`, `EMAIL_DIVERGE_ENTRE_DUPLICATAS`, `NOME_DIVERGE_ENTRE_DUPLICATAS`, `TELEFONE_DIVERGE_ENTRE_DUPLICATAS`, `EMAIL_DE_OUTRA_PESSOA`, `CPF_INVALIDO`, `EMAIL_INVALIDO`, `TELEFONE_INVALIDO`, `CLIENTE_SEM_NOME`, `VENDA_SEM_CLIENTE`, `REFERENCIA_DE_TESTE`, `NAO_LIGAR_COM_ACEITE`] | `clientes.xlsx` (Clientes, antigos), `vendas.cliente_ref`, `compras.cliente_ref`, contatos do atendimento | 299 cadastros fundidos; 1.286 e-mails/telefones ligados; 39 referências ambíguas | Uma pessoa = um cliente: junta por CPF, depois e-mail, depois telefone, sem nunca juntar CPFs diferentes; o `cliente_ref` é classificado (CPF válido vence; celular que também passa como CPF fica marcado). | Sem isso, a mesma pessoa aparece várias vezes e os pontos e pedidos se espalham. | 4.851 clientes da Vulto; 195 referências não identificam ninguém (pedido sem cliente). |
| 19 | Coluna Pontos congelada em 01/2025, com formatos misturados [`SALDO_COM_FORMATO`, `SALDO_ARREDONDADO`, `SALDOS_DUPLICADOS_SOMADOS`, `SALDO_SEM_CPF`, `PONTOS_ANTIGOS_JA_MIGRADOS`] | `clientes.xlsx:Clientes.Pontos` | 321 com ponto de milhar ou "pts"; 94 arredondados ("2,7k"); 71 clientes duplicados | "2.203" = 2203; "1389 pts" = 1389; "2,7k" = 2700 (estimado); duplicados somam; os pontos do programa antigo não somam de novo. | O sistema lia "2,7k" como zero e só a primeira linha do CPF. | Pontos: saldo inicial de 3.540.592 pontos em 01/01/2025. |
| 20 | Resgates fora do sistema (aba Resgates) [`RESGATE_SO_NA_PLANILHA`, `RESGATE_SEM_CPF`, `RESGATE_ILEGIVEL`] | `clientes.xlsx:Resgates` | 596 linhas; 41 só na planilha; 52 só com o nome | Resgate de 2025 em diante que não está no sistema (mesmo CPF e pontos, até 7 dias) é debitado; antes de 2025 já está no saldo congelado; só com o nome fica pendente. | As lojas anotavam resgates no papel; debitar os que já estão no sistema cobraria duas vezes. | Pontos: 39.000 pontos debitados; 45.900 pontos pendentes (no mínimo da faixa). |
| 21 | Ajustes `AJ` de −1,1 milhão de pontos [`AJUSTE_DO_BUG_SUBSTITUIDO`, `CREDITO_INFLADO_BUG_APP`] | `vulto.db:pontos_mov` (tipo AJ, obs "correcao bug app v3.4") | 21 ajustes do bug; 31 créditos inflados | Cada crédito inflado (pontos sobre centavos, 08 a 12/06/2026) volta ao valor em reais; os ajustes manuais do bug saem; os outros 40 ajustes (cortesia, aniversário) ficam. | A correção manual cobriu 18 clientes com o valor exato e esqueceu 12 créditos (+565.711 pontos). | Pontos: −1.553.967 pontos nos créditos e +1.138.676 pontos nos ajustes que saíram. |
| 22 | Valor do ponto: R$ 0,10 × R$ 0,05 [`RESGATE_COM_VALOR_ANTIGO`] | `vulto.db:config.valor_ponto` (0,10), README (R$ 10 por 100), aba LEIA ISSO (R$ 5 por 100 desde mar/2025) | Todo o passivo; resgates na planilha dando R$ 0,10 depois de mar/2025 | Vigente: R$ 0,05; a faixa vai até R$ 0,10. | A regra mudou em mar/2025, mas o sistema continuou com 0,10 e as lojas também. | Passivo: R$ 167.629,85 a R$ 0,05; R$ 335.259,70 a R$ 0,10. |
| 23 | Validade do Ouro: 12 × 18 meses | Aba LEIA ISSO ("combinado com o Diego, ainda não tá no sistema") | 48 contas Ouro | Gravado: 18 meses (o combinado, o passivo mais conservador); o passivo mostra os dois. | É o que foi prometido aos clientes Ouro. | Passivo: 94.644 pontos a mais com 18 meses (R$ 162.897,65 com 12 × R$ 167.629,85 com 18, a R$ 0,05). |
| 24 | Categoria manual × regra [`CATEGORIA_DECLARADA_DIVERGE`] | `clientes.xlsx:Clientes.categoria` (BRONZE, brz, Silver, ouro ★, vip?...) | 493 contas com a categoria declarada diferente da regra | Vale a regra (pontos do ano: Bronze até 1.999, Prata até 4.999, Ouro 5.000+); a declarada fica guardada. | A própria planilha diz que a categoria "foi colocada na mão, não bate com a regra". | Passivo: muda a validade de quem vira Ouro (18 meses). |
| 25 | Pontos creditados antes do pagamento aprovado [`CREDITO_ANTES_DO_PAGAMENTO`, `CANCELADA_SEM_ESTORNO`, `ESTORNO_DE_CREDITO_QUE_SAIU`] | `/venda` do legado (TODO "só creditar depois que o pagamento aprovar") | 199 créditos de vendas aguardando pagamento | Crédito de venda ainda aguardando pagamento sai; venda cancelada sem estorno ganha o estorno. | A regra: ponto só depois do pagamento aprovado; compra cancelada perde os pontos. | Pontos: −272.144 pontos; e −155.957 pontos de estornos que faltavam (285 vendas). |
| 26 | Atendimentos sem cliente ou pedido identificável [`ATENDIMENTO_SEM_CLIENTE`, `CLIENTE_PELO_PEDIDO`, `PEDIDO_NAO_ENCONTRADO`, `PEDIDO_DE_OUTRO_CLIENTE`, `PEDIDO_PELO_TEXTO`, `CONTATO_AMBIGUO`] | `atendimentos.csv` (contato, pedido) | 250 sem cliente; 32 pedidos que não casam | Cliente pelo contato (telefone ou e-mail) ou, sem ele, pelo pedido citado; sem nenhum, `cliente_id` vazio e o contato guardado. Pedido pela coluna (número do site/app ou id da venda) ou pelo texto. | @ do Instagram e telefone sem DDD não identificam ninguém sozinhos. | 287 atendimentos ganharam o cliente pelo pedido; 215 citam pedido de outro cadastro (provável mesma pessoa). |
| 27 | Senhas em texto puro e `senha_master` [`SENHA_TEXTO_PURO`, `SENHA_MASTER`, `SENHAS_NAO_MIGRADAS`, `SEM_EMAIL_INATIVOS`] | `vulto.db:funcionarios.senha`, `vulto.db:config.senha_master` | 24 funcionários na tabela; 1 senha mestra | Nenhuma senha é copiada (nem para o staging); a senha mestra entra mascarada e não é usada. Os funcionários entram inativos, sem e-mail e sem senha, e criam a senha pelo convite. | Senha em texto puro e senha mestra são falhas de segurança. | Nenhum número muda; ninguém da Vulto entra sem passar pelo convite. |

### Encontrados além da lista

| # | O que encontramos | Onde (arquivo / tabela / campo) | Quantos registros afeta | O que decidimos fazer | Por quê | Impacto no número final |
| --- | --- | --- | --- | --- | --- | --- |
| 28 | Vendas de teste da TI/QA e duplicatas do app [`VENDA_DE_TESTE`, `VENDA_DUPLICADA`, `CREDITO_DE_VENDA_DESCARTADA`, `PONTOS_DE_TESTE`, `ATENDIMENTO_SPAM`] | `vendas` (obs "teste", item TESTE-001, CPF 123.456.789-09; mesmo pedido externo gravado duas vezes) | 42 de teste; 76 duplicadas | Ficam de fora (e os pontos delas também). | Não são vendas: são testes e o app enviando o mesmo pedido duas vezes. | Faturamento: −R$ 100.070,06 (testes) e −R$ 29.084,27 (duplicatas) na ponte. |
| 29 | Cancelados e vendas aguardando pagamento no relatório da Vulto | `/relatorio/faturamento` do legado (cancelados como TODO) | Ver a ponte | Fora do faturamento: cancelados, estornados e chargebacks; e o que ainda aguarda pagamento. | Não é receita. | Faturamento: −R$ 276.264,21 (cancelados) e −R$ 109.445,94 (aguardando) na ponte. |
| 30 | Pontos para referência que não é CPF [`PONTOS_SEM_CPF_VALIDO`, `PONTOS_SEM_CLIENTE`] | `pontos_mov.cpf` com telefone ou e-mail | 237 movimentos | Saem: pontos só com CPF. | Regra do programa ("telefone/email não vale"). | Pontos: −90.937 pontos. |
| 31 | Dobro do online e bônus Ouro que o sistema nunca deu [`ONLINE_SEM_DOBRO`, `BONUS_OURO_NUNCA_APLICADO`] | `main.py` do legado (dobrava só "app" e "site" minúsculos; nunca aplicou +50% do Ouro) | Clientes com compras online sem dobro e as contas Ouro | O saldo fica como o cliente via; o que faltou entra só no máximo do passivo. | Creditar agora é uma decisão comercial, não de migração. | Passivo: 705.580 pontos de dobro e 200.454 de bônus ainda válidos (no máximo da faixa). |
| 32 | Saldo de pontos negativo [`SALDO_FICARIA_NEGATIVO`] | `pontos_mov` (o sistema deixava resgatar mais do que o saldo) | 81 contas | O saldo para em zero; um ajuste no mesmo instante cobre a diferença e fica registrado. | A regra: "NÃO pode ficar negativo". | Pontos: 98.532 pontos cobertos por ajuste. |
| 33 | Nome "?" ou "Cliente" no atendimento | `atendimentos.csv:nome_contato` | 160 cadastros que tinham ficado com esse nome | Texto sem letra e "Cliente" não são nome: o cadastro fica "Cliente Vulto (sem nome)". | Não é o nome da pessoa. | Nenhum número muda. |

## Decisões de regra (conflitos entre áreas)

| # | Regra em conflito | Quem diz o quê | O que decidimos (default) | Onde fica o parâmetro | Impacto |
| --- | --- | --- | --- | --- | --- |
| 1 | Preço de peça em mais de uma coleção | Compras: o da coleção mais nova · Operações/Financeiro: o menor (Procon) | O menor | `src/migracao_vulto/produtos.py: REGRA_PRECO` | 22 peças; +R$ 260,00 |
| 2 | Custo da peça | Compras: o último · Financeiro: o médio | Guardar os dois | `variacoes.preco_custo`, `variacoes.custo_medio` | Margem bruta conforme o custo escolhido |
| 3 | Frete | Receita × repasse | Faturamento sem frete (como a Casa Lorenzi); o frete aparece separado | `src/use_cases/diretoria.py` (ponte) · `faturamento_repository` | −R$ 55.248,70 |
| 4 | Status vazio | Pago × pendente | Pago | `src/migracao_vulto/vendas.py: STATUS_VAZIO` | R$ 315.404,23 (margem) |
| 5 | Canal da venda | Texto do canal × loja da venda | A loja | `normalizacao.CANAL_POR_LOJA_LEGADO` | 218 vendas mudam de canal |
| 6 | Troca | Venda nova × troca | Pedido TROCA: baixa o estoque, fora da receita | `src/entities/pedido.py: TIPOS_SEM_RECEITA` | −R$ 74.447,20 |
| 7 | Valor do ponto | config 0,10 · README R$ 10/100 · LEIA ISSO R$ 5/100 desde mar/2025 | R$ 0,05 (faixa até R$ 0,10) | `src/entities/fidelidade.py: VALOR_PONTO_VIGENTE` | R$ 167.629,85 × R$ 335.259,70 |
| 8 | Validade do Ouro | Sistema: 12 meses · Combinado com o Diego: 18 | 18 gravado; o passivo mostra os dois | `src/entities/fidelidade.py: VALIDADE_OURO_GRAVADA` | 94.644 pontos |
| 9 | Categoria do Vulto+ | Planilha (à mão) × regra dos pontos do ano | A regra; a declarada fica guardada | `src/entities/fidelidade.py: FAIXAS_CATEGORIA` | 493 contas |
| 10 | Ponto antes do pagamento | Sistema: na hora · Regra: depois do pagamento | Depois do pagamento | `src/migracao_vulto/fidelidade.py` | −272.144 pontos |
| 11 | Dobro do online e bônus Ouro não aplicados | Regra × o que o sistema creditou | Saldo como o cliente via; no máximo da faixa | `src/migracao_vulto/fidelidade.py` | 705.580 + 200.454 pontos |
| 12 | Data da contagem sem data | A planilha não diz | 30/09/2026 (estimada) | `src/migracao_vulto/estoque.py: CONTAGENS` | Eldorado, Savassi e Batel |
| 13 | Abertura do estoque (01/01/2025) | Desconhecida | A menor que deixa o histórico sem negativo | `src/migracao_vulto/estoque.py` | 20.911 peças |
| 14 | Clientes duplicados | Por qual identificador juntar | CPF → e-mail → telefone, sem juntar CPFs diferentes | `src/migracao_vulto/clientes.py: agrupar` | 299 cadastros fundidos |
| 15 | Atendimento sem cliente | Anulável × cliente genérico | `cliente_id` anulável, contato guardado | `atendimentos.cliente_id` | 250 atendimentos |
| 16 | Janela de um atendimento | Linhas do mesmo contato e assunto | 72 horas | `src/migracao_vulto/atendimento.py: JANELA` | Nenhuma junção nesta carga |
| 17 | Funcionários da Vulto | Migrar senha × convite | Inativos, sem e-mail e sem senha; convite depois | `src/migracao_vulto/usuarios.py` | Todos os funcionários migrados |

## Limitações conhecidas

O que não dá para recuperar com os dados entregues e como isso afeta os números.

| # | Limitação | Consequência | Margem de erro |
| --- | --- | --- | --- |
| 1 | Troca não registra a peça devolvida | A peça que volta numa troca não entra no histórico; o ajuste da contagem a absorve. | Dentro do ajuste da contagem (+4.790 peças) |
| 2 | Contagem da Batel incompleta | 82 linhas "faltou contar provador"/"recontar": o contado pode estar abaixo do real. | Sem quantidade anotada |
| 3 | Data real dos pontos congelados | Os pontos de antes de 2025 são tratados como ganhos em 01/01/2025 (a hipótese mais generosa): venceram em 01/01/2026 (Ouro: 01/07/2026) quando não usados. | Sem dado para estimar |
| 4 | Vendas com status vazio | Lidas como pagas. | Até R$ 315.404,23 a menos no faturamento |
| 5 | Planilha manual da Batel | Anotada à mão com o PDV fora do ar; uma venda Pix pode ter ficado de fora (Plan2). | Até R$ 22.466,99 a menos |
| 6 | Mesma pessoa em dois cadastros | Sem CPF, cadastros pelo WhatsApp e pelo e-mail da compra não são fundidos. | 215 atendimentos citam pedido de outro cadastro |
| 7 | Emojis do atendimento | Chegaram como "?" no CSV: a perda é anterior à migração. | Só texto |
| 8 | Vulto+ depois da virada | A plataforma ainda não credita, resgata nem vence pontos: o saldo é o de 01/10/2026. | Vencimentos depois de 01/10/2026 não aplicados |
| 9 | Lojas sem endereço | O legado só tem nome e cidade das lojas. | 5 lojas para completar |

## Apêndice: todas as ocorrências da migração

108 tipos de ocorrência, 16.182 registros. Ação: CORRIGIDO (entrou com valor ajustado), DESCARTADO (não entrou), ESTIMADO (entrou com estimativa), MANTIDO (entrou como veio, com o aviso), PENDENTE (precisa de alguém).

### atendimento

| Código | Ação | Registros | Impacto | Origem | Exemplo |
| --- | --- | --- | --- | --- | --- |
| `CLIENTE_PELO_PEDIDO` | CORRIGIDO | 287 | — | atendimentos.csv | O contato não identifica o cliente (@ do Instagram, telefone sem DDD): cliente do pedido citado. |
| `PEDIDO_PELO_TEXTO` | CORRIGIDO | 280 | — | atendimentos.csv | Coluna pedido vazia: pedido citado na mensagem. |
| `ATENDIMENTO_SEM_CLIENTE` | MANTIDO | 250 | — | atendimentos.csv | Contato que não identifica nenhum cliente e sem pedido que identifique: fica sem cliente, com o contato guardado. |
| `TIPO_PELAS_TAGS` · | CORRIGIDO | 225 | — | atendimentos.csv | Sem assunto: tipo pelas tags. |
| `PEDIDO_DE_OUTRO_CLIENTE` | PENDENTE | 215 | — | atendimentos.csv | O pedido citado é de outro cliente: ficam o cliente do contato e o pedido, para a equipe conferir. |
| `TROCA_OU_DEVOLUCAO` · | CORRIGIDO | 186 | — | atendimentos.csv | "troca/devolução": devolução quando o texto fala em devolver ou reembolso. |
| `STATUS_VAZIO` · | CORRIGIDO | 81 | — | atendimentos.csv | Atendimento sem status: entra como ABERTO, para alguém conferir. |
| `PEDIDO_NAO_ENCONTRADO` | PENDENTE | 32 | — | atendimentos.csv | O pedido informado não corresponde a nenhuma venda migrada. |
| `ATENDIMENTO_REPETIDO` · | DESCARTADO | 17 | — | atendimentos.csv | Linha repetida na exportação (mesmo contato, hora e mensagem): entra uma vez. |
| `ASSUNTO_SEM_TIPO` · | CORRIGIDO | 12 | — | atendimentos.csv | Sem assunto nem tag reconhecida: entra como dúvida sobre produto. |
| `ATENDIMENTO_SPAM` | DESCARTADO | 10 | — | atendimentos.csv | Spam ou mensagem de teste: fora do atendimento. |
| `CONTATO_AMBIGUO` | PENDENTE | 1 | — | atendimentos.csv | O contato é de mais de um cliente: fica sem cliente (ou o do pedido). |

### clientes

| Código | Ação | Registros | Impacto | Origem | Exemplo |
| --- | --- | --- | --- | --- | --- |
| `CLIENTE_SEM_NOME` | PENDENTE | 2.127 | — | vulto.db:cliente_ref | Cliente que só aparece nas vendas (cadastrou depois de jan/25): entra com o nome "Cliente Vulto (sem nome)" até alguém completar. |
| `IDENTIFICADORES_LIGADOS` | MANTIDO | 1.286 | — | vulto.db:cliente_ref | E-mail/telefone das vendas ou do atendimento ligados ao mesmo cliente (regras: CPF, EMAIL, TELEFONE). |
| `TELEFONE_INVALIDO` | DESCARTADO | 425 | — | clientes.xlsx:Clientes | Telefone sem DDD ou inválido: o cliente entra sem telefone (Telefone inválido: '90061-4041'). |
| `CADASTROS_FUNDIDOS` | CORRIGIDO | 299 | — | clientes.xlsx:Clientes | Cadastros duplicados da mesma pessoa viraram um cliente só (regras: CPF, EMAIL, TELEFONE). |
| `REFERENCIA_SEM_CLIENTE` | DESCARTADO | 195 | — | vulto.db:vendas/compras.cliente_ref | Referência de cliente que não identifica ninguém (1 vendas/compras): ficam sem cliente. |
| `EMAIL_DIVERGE_ENTRE_DUPLICATAS` | MANTIDO | 130 | — | clientes.xlsx:Clientes | A mesma pessoa com e-mails diferentes: fica o mais recente (os outros continuam ligados a ela no de_para). |
| `NAO_LIGAR_COM_ACEITE` | CORRIGIDO | 41 | — | clientes.xlsx:Clientes | aceita_msg diz sim, mas a observação diz "não ligar": fica sem consentimento (LGPD, na dúvida). |
| `REFERENCIA_AMBIGUA` | MANTIDO | 39 | — | vulto.db:vendas/compras.cliente_ref | 11 dígitos que são CPF válido e também têm cara de celular (1 registros): tratado como CPF (o dígito verificador bate). |
| `CPF_INVALIDO` | DESCARTADO | 28 | — | clientes.xlsx:Clientes | CPF inválido: o cliente entra sem CPF (CPF inválido: '084.077.822-55'). |
| `EMAIL_DE_OUTRA_PESSOA` | CORRIGIDO | 20 | — | clientes.xlsx:Clientes | O mesmo e-mail em cadastros com CPFs diferentes (duas pessoas): o e-mail fica com o cadastro mais recente. |
| `NOME_DIVERGE_ENTRE_DUPLICATAS` | MANTIDO | 17 | — | clientes.xlsx:Clientes | A mesma pessoa com nomes diferentes nos cadastros: vale o mais recente. |
| `EMAIL_INVALIDO` | DESCARTADO | 7 | — | clientes.xlsx:Clientes | E-mail inválido: o cliente entra sem e-mail (E-mail inválido: '-'). |
| `REFERENCIA_DE_TESTE` | DESCARTADO | 4 | — | vulto.db:vendas/compras.cliente_ref | Identidade usada pela TI/QA da Vulto para testes (10 vendas/compras): não vira cliente. |
| `TELEFONE_DIVERGE_ENTRE_DUPLICATAS` | MANTIDO | 1 | — | clientes.xlsx:Clientes | A mesma pessoa com telefones diferentes: vale o mais recente. |

### estoque

| Código | Ação | Registros | Impacto | Origem | Exemplo |
| --- | --- | --- | --- | --- | --- |
| `CONTAGEM_DIFERE_DO_RECONSTRUIDO` | CORRIGIDO | 2.830 | +4.790 peças | contagem_inventario_set26.xlsx:savassi_por_modelo | O contado em set/26 não bate com o saldo reconstruído (entradas, transferências, vendas e devoluções desde a abertura estimada): ajuste para o contado. Negativo = peça que sumiu (p |
| `SAVASSI_CONTAGEM_POR_MODELO` | ESTIMADO | 161 | +2.114 peças | contagem_inventario_set26.xlsx:savassi_por_modelo | A Savassi contou por modelo, não por SKU: o total do modelo foi rateado entre as variações pelo mix de entradas e vendas. Margem de erro: as peças do modelo podem estar em qualquer |
| `BATEL_CONTAGEM_INCOMPLETA` · | PENDENTE | 82 | — | contagem_inventario_set26.xlsx:batel | Linha da contagem da Batel marcada "faltou contar provador": o contado pode estar abaixo do real (o ajuste usa o contado). |
| `TRANSFERENCIA_ENTRE_LOJAS` | CORRIGIDO | 21 | — | vulto.db:entradas_estoque | Transferência entre lojas, anotada por quem enviou com a quantidade só na obs. |
| `CONTAGEM_QUANTIDADE_COM_TEXTO` · | CORRIGIDO | 16 | — | contagem_inventario_set26.xlsx:batel | Quantidade anotada com o detalhe estoque + vitrine: vale o total. |
| `CONTAGEM_SKU_ILEGIVEL` | DESCARTADO | 14 | −44 peças | contagem_inventario_set26.xlsx:pinheiros_20_09 | SKU da contagem que não acha variação: as peças ficam de fora do ajuste. |
| `ABERTURA_ESTIMADA` | ESTIMADO | 5 | +20.911 peças | vulto.db:entradas_estoque | Saldo de 01/01/2025 desconhecido: abertura estimada, a menor que deixa o histórico da peça sem saldo negativo até a contagem (a loja vendeu peças que já tinha antes de 2025). O aju |
| `CONTAGEM_SKU_DIGITADO_ERRADO` | CORRIGIDO | 4 | — | contagem_inventario_set26.xlsx:pinheiros_20_09 | SKU digitado errado na contagem, com conserto inequívoco (separador fora do lugar ou letras da cor trocadas). |
| `CONTAGEM_SEM_DATA` | ESTIMADO | 3 | — | contagem_inventario_set26.xlsx | A planilha não diz o dia da contagem de Vulto Batel: ajuste em 30/09/2026 (estimativa aprovada). As vendas entre a contagem real e essa data podem ficar contadas duas vezes ou nenh |
| `ESTOQUE_DAS_LOJAS_VIRTUAIS` | DESCARTADO | 1 | −12.694 peças | vulto.db:estoque | Saldo das "lojas" site (5) e app (6) do legado: não existe estoque físico lá (site e app vendem do CD); desconsiderado. |
| `ESTOQUE_DO_LEGADO_SO_COMPARACAO` | DESCARTADO | 1 | −18.360 peças | vulto.db:estoque | A tabela estoque da Vulto não tem histórico e tem 1156 saldos negativos: não entra, só se compara. Dos 4421 itens (loja × peça), 1665 batem com o saldo reconstruído; a soma das dif |
| `SALDO_NEGATIVO_DEPOIS_DA_CONTAGEM` | PENDENTE | 1 | +4 peças | contagem_inventario_set26.xlsx | Peças que venderam mais do que o contado entre a contagem e 01/10/2026 (contagem incompleta ou venda sem entrada lançada). |
| `TRANSFERENCIA_DOS_DOIS_LADOS` | CORRIGIDO | 1 | −5.290 peças | vulto.db:entradas_estoque | Quem envia e quem recebe anotam a mesma transferência ("uma das duas pontas basta"): 5290 peças aparecem dos dois lados (mesma peça e loja, de 10 dias antes a 15 depois do envio) e |

### fidelidade

| Código | Ação | Registros | Impacto | Origem | Exemplo |
| --- | --- | --- | --- | --- | --- |
| `SALDO_COM_FORMATO` | CORRIGIDO | 321 | — | clientes.xlsx:Clientes | Saldo com ponto de milhar ou "pts" ("2.203" = 2203). |
| `CANCELADA_SEM_ESTORNO` | CORRIGIDO | 285 | −155.957 pontos | vulto.db:pontos_mov | Venda cancelada que manteve os pontos (o estorno era lançado à mão): estornada. |
| `PONTOS_SEM_CPF_VALIDO` | DESCARTADO | 237 | −90.937 pontos | vulto.db:pontos_mov | Movimento para referência que não é CPF válido (telefone, e-mail): pontos só com CPF. |
| `CREDITO_ANTES_DO_PAGAMENTO` | DESCARTADO | 199 | −272.144 pontos | vulto.db:pontos_mov | Venda ainda aguardando pagamento: ponto só depois do pagamento aprovado (o sistema creditava na hora). |
| `SALDO_ARREDONDADO` | ESTIMADO | 94 | — | clientes.xlsx:Clientes | Saldo anotado arredondado ("2,7k"): entra o valor arredondado. |
| `SALDO_FICARIA_NEGATIVO` | PENDENTE | 81 | +98.532 pontos | vulto.db:pontos_mov | Resgates ou estornos maiores que o saldo disponível (o sistema deixava ficar negativo): o saldo para em zero e a diferença entra como ajuste. |
| `CREDITO_DE_VENDA_DESCARTADA` | DESCARTADO | 76 | −44.058 pontos | vulto.db:pontos_mov | Crédito de uma venda duplicada (descartada na etapa de vendas): sai. |
| `SALDOS_DUPLICADOS_SOMADOS` | CORRIGIDO | 71 | — | clientes.xlsx:Clientes | Cliente duplicado na planilha: os saldos congelados foram somados na conta única. |
| `RESGATE_SEM_CPF` | PENDENTE | 52 | −45.900 pontos | clientes.xlsx:Resgates | Resgate anotado só com o nome (ou CPF que não é cliente): não dá para saber de quem debitar. |
| `RESGATE_SO_NA_PLANILHA` | CORRIGIDO | 41 | −39.000 pontos | clientes.xlsx:Resgates | Resgate de 2025 em diante anotado só na planilha (fora do sistema): debitado. |
| `CREDITO_INFLADO_BUG_APP` | CORRIGIDO | 31 | −1.553.967 pontos | vulto.db:pontos_mov | Crédito calculado sobre o valor em centavos (bug do app v3.4): corrigido para o valor em reais. |
| `AJUSTE_DO_BUG_SUBSTITUIDO` | DESCARTADO | 21 | +1.138.676 pontos | vulto.db:pontos_mov | Ajuste manual da correção do bug do app v3.4: sai, porque cada crédito inflado já foi corrigido com o valor exato. |
| `PONTOS_DE_TESTE` | DESCARTADO | 19 | −24 pontos | vulto.db:pontos_mov | Movimento de pontos de CPF de teste. |
| `SALDO_SEM_CPF` | DESCARTADO | 17 | −34.447 pontos | clientes.xlsx:Clientes | Saldo congelado de cliente sem CPF válido: pontos só com CPF. |
| `PONTOS_SEM_CLIENTE` | DESCARTADO | 2 | −1.690 pontos | vulto.db:pontos_mov | Movimento de CPF que não é cliente migrado. |
| `BONUS_OURO_NUNCA_APLICADO` | MANTIDO | 1 | +200.454 pontos | main.py:/compra | O sistema nunca aplicou o bônus Ouro de +50%: o saldo fica como o cliente via. O impacto é o bônus sobre os créditos de 2026 das contas Ouro que ainda valeria em 01/10/2026, e entr |
| `CATEGORIA_DECLARADA_DIVERGE` | CORRIGIDO | 1 | — | clientes.xlsx:Clientes | 493 contas com a categoria colocada à mão diferente da regra (pontos creditados em 2026): vale a regra; a declarada fica guardada. |
| `CREDITO_EM_TROCA` · | MANTIDO | 1 | +22.430 pontos | vulto.db:pontos_mov | 65 trocas lançadas como venda nova ganharam pontos (a regra não fala de troca): mantidos como o sistema creditou. |
| `DEVOLUCAO_SEM_ESTORNO` · | MANTIDO | 1 | — | vulto.db:pontos_mov | 34 devoluções de compras que pontuaram (R$ 5702,17 devolvidos) não estornaram pontos. A regra só fala de compra cancelada: mantidos. |
| `ONLINE_SEM_DOBRO` | MANTIDO | 1 | +705.580 pontos | vulto.db:pontos_mov | Compras online com o canal escrito "APP", "online", "web", "E-commerce"... não ganharam o dobro (o sistema só dobrava "app" e "site"): o saldo fica como o cliente via. O impacto é  |
| `PONTOS_ANTIGOS_JA_MIGRADOS` | MANTIDO | 1 | — | clientes.xlsx:clientes antigos (NAO APAGAR) | Os pontos do programa antigo dos 107 clientes ATIVO já foram migrados em jan/24 para a coluna Pontos: não somam de novo. 31 deles não estão na aba Clientes (se tinham pontos, ficar |
| `RESGATE_COM_VALOR_ANTIGO` | MANTIDO | 1 | — | clientes.xlsx:Resgates | 420 resgates depois de mar/2025 deram R$ 0,10 por ponto (o config.valor_ponto do sistema e o README), e não os R$ 0,05 da regra: R$ 17795,00 de desconto a mais. O passivo mostra os |
| `SALDO_DO_LEGADO_SO_COMPARACAO` · | MANTIDO | 1 | +8.226.792 pontos | main.py:/cliente | O sistema da Vulto mostrava 8226792 pontos (sem validade; 13 clientes com saldo negativo). Depois das correções, 7876596 pontos sem validade; 4523999 venceram até 01/10/2026. Só co |

### lojas

| Código | Ação | Registros | Impacto | Origem | Exemplo |
| --- | --- | --- | --- | --- | --- |
| `LOJA_SEM_ENDERECO` · | PENDENTE | 5 | — | vulto.db:lojas | O legado só tem nome e cidade: UF deduzida da cidade; endereço, telefone e horários ficam para a equipe completar na central administrativa. |
| `LOJA_VIRTUAL_VIRA_CANAL` | CORRIGIDO | 2 | — | vulto.db:lojas | Vulto App não vira loja: é o canal App. O estoque online é físico no CD Cajamar, de onde os pedidos saem (ou de Pinheiros, no ship from store). |

### produtos

| Código | Ação | Registros | Impacto | Origem | Exemplo |
| --- | --- | --- | --- | --- | --- |
| `CUSTO_DA_NOTA` | CORRIGIDO | 71 | — | catalogo.xlsx:custo | Sem custo na planilha: vale o da última nota de entrada. |
| `EAN_INVALIDO` | DESCARTADO | 22 | — | catalogo.xlsx:Verão 26 | EAN não usado: EAN com dígito verificador errado: '7890231000000' |
| `PRECO_ENTRE_COLECOES` | CORRIGIDO | 22 | +R$ 260,00 | catalogo.xlsx:modelo | Peça em mais de uma coleção com preços diferentes. Regra aplicada: MENOR (Operações/Financeiro, por causa do Procon); Compras usaria o da coleção mais nova. Impacto: diferença por  |
| `SO_NA_PLANILHA_ANTIGA` · | MANTIDO | 14 | — | catalogo.xlsx:modelo | Peça que só está na planilha antiga (2024) mas ainda tem vendas: entra inativa, com o preço de 2024. |
| `GRAFIA_DE_SKU_ILEGIVEL` | PENDENTE | 13 | — | vulto.db:itens_venda | Grafia de SKU que não dá para interpretar (erro de digitação ou código de teste): não vira alias. |
| `LINHA_VARIOS_TAMANHOS` | CORRIGIDO | 12 | — | catalogo.xlsx:inverno25 | Uma linha para vários tamanhos: vira uma variação por tamanho, com o mesmo preço e custo e sem EAN (o EAN da linha não identifica um tamanho). |
| `CATEGORIA_DIVERGE_DO_SKU` · | MANTIDO | 8 | — | catalogo.xlsx:categoria | O texto da categoria indica outra categoria: vale o prefixo do SKU (Tricô). |
| `PRECO_DIVERGE_NA_ABA` | CORRIGIDO | 8 | −R$ 974,02 | catalogo.xlsx:Verão 26 | Preço diferente do resto do modelo na mesma aba (2024 (planilha antiga)): vale o mais frequente. |
| `CODIGO_REAPROVEITADO` | CORRIGIDO | 6 | — | catalogo.xlsx:modelo | Código reaproveitado por outra peça (regra 8 de Compras): a peça de 2024 vira outro produto, inativo, com SKU terminado em -2024; as grafias em comum valem para a peça antiga até a |
| `GRAFIA_SEM_PRODUTO` | PENDENTE | 6 | — | contagem.xlsx:PINHEIROS 20-09 | Grafia de um modelo que não está no catálogo: não vira alias. |
| `PRECO_A_REVISAR` | PENDENTE | 5 | — | catalogo.xlsx:VERAO 25 | Linha marcada em amarelo na planilha ("revisar preço"). |
| `VARIACAO_FORA_DO_CATALOGO` | CORRIGIDO | 2 | — | contagem.xlsx:Eldorado | Cor/tamanho que aparece nas vendas ou no estoque, mas não no catálogo, de um modelo que está nele: entra como variação inativa, sem EAN e sem custo. |
| `VENDIDO_SEM_CADASTRO` | CORRIGIDO | 2 | — | vulto.db:itens_venda.sku | Item vendido sem produto no catálogo: entra no produto "Item sem cadastro (Vulto)", categoria Não catalogado. |
| `EAN_DIVERGE_ENTRE_COLECOES` | MANTIDO | 1 | — | catalogo.xlsx:ean | A mesma peça tem EANs diferentes nas coleções: fica o da coleção mais nova. |

### staging

| Código | Ação | Registros | Impacto | Origem | Exemplo |
| --- | --- | --- | --- | --- | --- |
| `SENHA_MASTER` | DESCARTADO | 1 | — | vulto.db:config.senha_master | O legado tem uma senha mestra que entra como qualquer funcionário (falha de segurança). Entra mascarada no staging e não é usada em lugar nenhum da plataforma. |
| `SENHA_TEXTO_PURO` | DESCARTADO | 1 | 24 registros | vulto.db:funcionarios.senha | As senhas dos funcionários estão em texto puro no legado. Não foram copiadas nem para o staging (fica só _senha_preenchida); os funcionários entram sem senha, pelo convite. |

### usuarios

| Código | Ação | Registros | Impacto | Origem | Exemplo |
| --- | --- | --- | --- | --- | --- |
| `FUNCIONARIO_DESCARTADO` · | DESCARTADO | 3 | — | vulto.db:funcionarios | Conta de teste da ti: não vira usuário. |
| `CONTA_DE_FUNCAO` · | PENDENTE | 2 | — | vulto.db:funcionarios | Conta com o nome da função, não de uma pessoa: migrada inativa; troque pelo nome de quem usa ao cadastrar o e-mail. |
| `ATENDENTES_SEM_USUARIO` · | MANTIDO | 1 | — | atendimentos.csv:atendente | "time insta" (conta compartilhada) e o bot não viram usuário: o atendimento fica sem responsável e o nome fica no texto. |
| `CODIGO_REPETIDO` · | MANTIDO | 1 | — | vulto.db:funcionarios | O mesmo código de vendedor para 2 pessoas: as vendas com esse código não dizem quem vendeu. Todas viram usuário. |
| `SEM_EMAIL_INATIVOS` | MANTIDO | 1 | — | vulto.db:funcionarios | Os funcionários da Vulto não têm e-mail: entram inativos e sem senha. Para dar acesso, um administrador cadastra o e-mail, reativa e manda o convite. |
| `SENHAS_NAO_MIGRADAS` | DESCARTADO | 1 | — | vulto.db:funcionarios | 23 senhas em texto puro (e a senha_master do config) não migram: cada pessoa cria a sua pelo convite. |

### vendas

| Código | Ação | Registros | Impacto | Origem | Exemplo |
| --- | --- | --- | --- | --- | --- |
| `VALOR_EM_CENTAVOS` | CORRIGIDO | 2.288 | −R$ 85.595.853,42 | vulto.db:vendas | Total e itens gravados em centavos pelo app (decidido pelo preço do catálogo). |
| `STATUS_VAZIO_COMO_PAGO` | CORRIGIDO | 949 | — | vulto.db:vendas | Status vazio (lojas físicas, jan–fev/25, com itens e conta fechando): tratado como pago. |
| `FRETE_EMBUTIDO_NO_TOTAL` | CORRIGIDO | 780 | — | vulto.db:vendas | O app somou o frete no total sem gravar na coluna frete: separado. |
| `TROCA_FORA_DA_RECEITA` | CORRIGIDO | 328 | −R$ 74.447,20 | vulto.db:vendas | Troca lançada como venda nova pelo preço cheio: entra como pedido TROCA (baixa o estoque), fora do faturamento — a venda original já contou. |
| `CANAL_TEXTO_DIVERGE` | MANTIDO | 218 | — | vulto.db:vendas | O texto do canal contradiz a loja da venda: vale a loja. |
| `DEVOLUCAO_REFERENCIA` | MANTIDO | 90 | −R$ 18.510,52 | vulto.db:vendas | Devolução ligada à venda citada na obs. |
| `DEVOLUCAO_CLIENTE` | ESTIMADO | 87 | −R$ 15.846,92 | vulto.db:vendas | Devolução sem referência válida: ligada à última compra do mesmo cliente com a mesma peça. |
| `VENDA_DUPLICADA` | DESCARTADO | 76 | — | vulto.db:vendas | Mesmo pedido externo APP-7001324 (aguardando seguido do pago, 64 s depois): fica só a venda 273. |
| `BATEL_VENDA_MANUAL` | ESTIMADO | 59 | +R$ 22.466,99 | vendas_batel_MANUAL_marco.xlsx:MARÇO | Venda feita com o PDV fora do ar, só na planilha manual: entra como pedido (peças casadas pela descrição; preço do catálogo e a diferença como desconto). |
| `SHIP_FROM_STORE` | CORRIGIDO | 56 | — | vulto.db:vendas | Pedido do site que saiu de Pinheiros: a loja de expedição é Pinheiros (o sistema da Vulto baixava do site). |
| `VENDA_DE_TESTE` | DESCARTADO | 42 | — | vulto.db:vendas | Venda de teste da TI/QA (cliente de teste (00000000000)): fora da plataforma. |
| `BATEL_DATA_INVERTIDA` | CORRIGIDO | 26 | — | vendas_batel_MANUAL_marco.xlsx:MARÇO | O Excel leu a data digitada como mês/dia: dia e mês destrocados. |
| `DEVOLUCAO_SEM_ORIGEM` | PENDENTE | 24 | −R$ 4.464,41 | vulto.db:vendas | Devolução que não dá para ligar a nenhuma venda: entra sem origem (conta no líquido). |
| `BATEL_JA_RELANCADA` | DESCARTADO | 13 | — | vendas_batel_MANUAL_marco.xlsx:MARÇO | Venda manual que a gerente relançou no sistema (venda 12800, mesmo CPF e valor): fica a do sistema, que tem os SKUs. |
| `BATEL_RELANCADA_REDATADA` | CORRIGIDO | 13 | — | vulto.db:vendas | Venda relançada com a data do relançamento: volta para a data em que aconteceu (planilha manual). |
| `BATEL_RELANCADA_SEM_PAR` | PENDENTE | 3 | — | vulto.db:vendas | Venda relançada que não casou com nenhuma linha da planilha manual: fica como está. |
| `DESCONTO_NAO_REGISTRADO` | CORRIGIDO | 3 | — | vulto.db:vendas | Total menor que a soma dos itens sem desconto registrado: a diferença vira desconto. |
| `TOTAL_NAO_FECHA` | PENDENTE | 3 | +R$ 0,60 | vulto.db:vendas | Total maior que itens + frete numa loja física: mantido o total gravado. |
| `BATEL_PIX_FALTANDO` | PENDENTE | 1 | — | vendas_batel_MANUAL_marco.xlsx:Plan2 | A aba Plan2 da planilha manual diz "semana 2 faltou 1 venda pix?": não há dado dessa venda; fica de fora. |
| `BATEL_TOTAL_DA_PLANILHA` | MANTIDO | 1 | R$ 0,00 | vendas_batel_MANUAL_marco.xlsx:MARÇO | Soma das 69 vendas manuais não canceladas conferida com o TOTAL MARÇO da planilha (3 canceladas ou estornadas ficam fora, como nos totais da gerente). |
| `ELDORADO_SERVIDOR_TROCADO` | CORRIGIDO | 1 | 32 registros | vulto.db:vendas | Desde a venda 11848 (2026-02-10T15:43:34Z) o PDV do Eldorado grava em UTC (Z); antes, horário local. Sem lacunas nem vendas duplicadas na troca. 1025 vendas convertidas para Brasíl |
| `VENDA_SEM_CLIENTE` | MANTIDO | 1 | 3.882 registros | vulto.db:vendas | Vendas sem cliente identificável (vazio, "NAO INFORMADO", "consumidor", referência inválida): pedido sem cliente. |

· ocorrência sem linha própria nas tabelas acima (detalhe da migração).
