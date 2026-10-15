# CLAUDE.md — Casa Lorenzi backend · União com a Vulto (Entrega 3)

Guia para quem (pessoa ou agente) trabalha neste repositório durante a união dos sistemas
Casa Lorenzi + Vulto. O README explica o projeto; este arquivo resume **as regras da união**.

## Contexto

A Casa Lorenzi comprou a Vulto. A diretoria quer **uma plataforma só**: esta. A Vulto entregou um
sistema legado (FastAPI + SQLite) e planilhas; ninguém que os construiu continua na empresa.

Missão:
1. Incorporar os domínios da Vulto a este backend: produtos, estoque, vendas, clientes + Vulto+ e atendimento.
2. Migrar os dados da Vulto **uma única vez**. Depois disso, esta plataforma é a única fonte de verdade.

**Migrar não é copiar.** Para cada dado: o que é confiável, o que precisa ser corrigido, o que não
dá para recuperar. **Toda decisão é registrada** (`migracao_ocorrencias` → `docs/registro_decisoes.md`).

## Repositórios

| Pasta (`~/`) | Papel | Pode modificar? |
|---|---|---|
| `casalorenzi-backend/` | Este backend (FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · JWT) | **Sim** |
| `casalorenzi-frontend/` | Frontend React + Vite | **Não** (as telas são do time de front) |
| `vulto-legado-back/` | Legado da Vulto + dados em `data/` | **Não — somente leitura** |
| `vulto-legado-front/` | Front legado da Vulto | **Não — somente leitura** |

**O legado é só leitura.** Abra o SQLite com `file:...vulto.db?mode=ro`; nunca grave nas planilhas
(o `planilha.anota_resgate` do legado escreve no xlsx: não chame código do legado).

Arquivos em `vulto-legado-back/data/`:
- `vulto.db` — `lojas`, `compras`, `pontos_mov`, `config`, `vendas`, `itens_venda`, `estoque`, `entradas_estoque`, `funcionarios`.
- `catalogo_vulto_2026_REVISADO_final.xlsx` — abas válidas `VERAO 25`, `inverno25`, `Verão 26` (contém a
  sub-tabela "INVERNO 26 (provisório)" a partir da linha 274), `Atemporais`. `PLANILHA ANTIGA NAO USAR` só
  como referência de preço de 2024. Ler `LEIA ISSO - REGRAS`.
- `clientes_fidelidade_FINAL_v3 (1).xlsx` — `Clientes`, `clientes antigos (NAO APAGAR)`, `Resgates`, `LEIA ISSO`.
- `contagem_inventario_set26.xlsx` — uma aba por loja, cada uma num formato.
- `vendas_batel_MANUAL_marco.xlsx` — vendas da Batel com o PDV fora (02 a 22/03/2026).
- `atendimentos_export_whatsapp_insta.csv` — latin-1, primeira linha `sep=;`, mensagens com quebra de linha.
- `REGRAS_OPERACAO.txt` — regras do Diego. Em conflito com a planilha da Marina, vale o Diego.
  Regras contraditórias entre áreas: **registre o conflito, não resolva em silêncio**.

As regras implícitas do legado (ex.: o relatório de faturamento) estão em `main.py`, `banco.py`,
`planilha.py` e `catalogo.py`.

## Escopo — o que NÃO fazer

- **Não mexer no frontend** (nem no da Lorenzi nem no da Vulto). A entrega são endpoints documentados
  no Swagger, com schemas de resposta claros. Cada PR com endpoints novos lista rotas, parâmetros e
  exemplos de resposta.
- **Não escrever em `vulto-legado-*`.**
- **Não migrar senhas.** `funcionarios.senha` está em texto puro e `config.senha_master` é uma falha de
  segurança: não copiar, não usar, registrar. Funcionários entram sem senha, pelo fluxo de convite.
- **Não inventar regra de negócio.** Regra ambígua: (1) usar o default do plano (ou o mais
  conservador); (2) deixar parametrizável (constante em `src/entities` ou config); (3) registrar.
  Se nem isso der, parar e perguntar.

## Decisões já tomadas (aprovadas)

- **Marca é dimensão, não tabela.** Nada de `produtos_vulto`. `marca` (`LORENZI` | `VULTO`, default
  `LORENZI`) em `lojas` e `produtos`; `tipo` (`FISICA` | `CD` | `VIRTUAL`) em `lojas`. Pedidos, estoques,
  movimentações e atendimentos herdam a marca pela loja ou pelo produto. **Cliente não tem marca**: a
  mesma pessoa nas duas redes é um registro só.
- **Lojas Vulto:** Pinheiros, Eldorado, Savassi e Batel (`FISICA`) e CD Cajamar (`CD`). **E-commerce e App
  da Vulto são canais, não lojas**: o pedido online fica com a loja que expede (CD Cajamar; Pinheiros no
  ship from store) e o canal `E-commerce` ou `App`. As "lojas" 5 e 6 do legado não existem aqui.
- **Canal guardado pelo rótulo** (`Loja física`, `E-commerce`, `App`), porque o frontend filtra pelo
  texto. Os códigos canônicos (`LOJA`, `SITE`, `APP`) ficam só nas constantes de `src/entities/pedido.py`.
- **Financeiro e dashboard** somam as duas marcas por padrão e aceitam filtro por `marca`.
- **Site da Lorenzi** (vitrine, `/lojas` público, checkout, expedição e transferências automáticas)
  continua só com a marca `LORENZI`.
- **Funcionários Vulto** (não têm e-mail): importados **inativos**, sem senha, até alguém cadastrar o
  e-mail no painel e enviar o convite. Usuário de teste `9999`, `estagio` e `admin` inativo não migram.
- **Consentimento de marketing (LGPD):** na dúvida, sem consentimento. Clientes atuais da Lorenzi
  ficam com `aceita_marketing = false` (não há registro de consentimento deles).

## Fluxo de trabalho e Git

- **Nunca commitar na `main`.** Uma branch por etapa, a partir da `main` atualizada
  (`git fetch && git switch -c tipo/descricao origin/main`). Nomes `feat/...`, `fix/...`, `chore/...`, `docs/...`.
  Não acumular etapas numa branch. Etapa que depende de outra ainda não mergeada: branch a partir da
  anterior, avisando no PR.
- **Commits:** Conventional Commits em português, imperativo, título com até 50 caracteres, um
  assunto por commit (`feat: importa catálogo da Vulto com aliases de SKU`). A migration vai no mesmo
  commit do código que depende dela.
- **Por etapa:** planejar e mostrar o plano → implementar → testes → validar com consultas reais nos
  dados → commit → PR (o que foi feito, como testar, o que fica pendente). **Não fazer merge**: o
  responsável revisa e faz o merge.
- **Antes do PR:** `pytest` passa (com `TEST_DATABASE_URL`), `alembic upgrade head` roda num banco
  limpo e o seed da Lorenzi continua funcionando. `ruff check src tests alembic`.

## Arquitetura (respeitar)

- `src/models` (SQLAlchemy 2 com `Mapped[...]`, um arquivo por tabela), `src/entities` (constantes, enums
  e regras do dado), `src/repositories`, `src/use_cases`, `src/routers`, `src/schemas`; migrations em
  `alembic/versions`; restrições de valor via `_restricoes.valor_em` (`CheckConstraint`).
- **Não quebrar a Lorenzi:** colunas novas com default; enums novos incluem os valores antigos;
  respostas da API só ganham campos.
- Nomes em português. Sem segredos no código (use o `.env`).

### Pipeline de migração (3 camadas)

1. **Staging** — schema `legado_vulto`: tudo cru, colunas TEXT, com arquivo/aba e número da linha de
   origem. Nada de limpeza aqui.
2. **Transformação** — `src/migracao_vulto/`, um módulo por domínio (pandas + SQLAlchemy): normaliza,
   deduplica, valida.
3. **Carga** — schema `public`, tabelas da plataforma.

Apoio: `de_para` (origem, id_origem → tabela_destino, id_destino) e `migracao_ocorrencias` (base do
registro de decisões). O pipeline é **idempotente**, **nunca apaga dados da Lorenzi**, roda com
`python -m src.migracao_vulto --tudo` ou `--dominio <nome>` e imprime lidos/carregados/corrigidos/
descartados por domínio.

**Atenção:** `python -m src.database.seed --recriar` apaga **todas** as tabelas do metadata, inclusive
os dados migrados da Vulto. Depois de um `--recriar`, rode o pipeline de novo. Nunca rode `--recriar`
em produção depois da migração. (Sem `--recriar`, o seed só popula banco vazio — é o que o start do
Render faz a cada deploy.)

## Padronização dos dados da Vulto

Funções puras e testadas em `src/migracao_vulto/normalizacao.py`, usadas por todos os domínios.

| Dado | Padrão de destino |
|---|---|
| Dinheiro | `Decimal`, `Numeric(12,2)`, em reais. Centavos (app) detectados pela conta da venda e pelo preço do catálogo — nunca por heurística cega |
| Data/hora | `timestamptz`. Sem fuso ⇒ `America/Sao_Paulo`; `Z` ⇒ UTC. Nunca ordenar datas como texto |
| CPF | 11 dígitos, dígito verificador validado; inválido ⇒ `NULL` + ocorrência |
| E-mail | minúsculo, sem espaços, formato validado |
| Telefone | E.164 (`+5511948854328`) |
| Instagram | handle minúsculo sem `@` |
| Nome de pessoa | trim + espaços únicos, capitalização preservada (original no staging) |
| SKU | canônico `VLT-CAT-NNN-COR-TAM`; todas as outras grafias em `sku_alias` |
| EAN | 13 dígitos; chave forte para desempate de SKU |
| Cor | dicionário fechado, maiúsculo |
| Tamanho | maiúsculo, sem espaços (`PP`…`GG`, `36`…`46`, `U`) |
| Categoria | mapeada para `categorias` (tabela de mapeamento explícita) |
| Canal | derivado da `loja_id` do legado (1–4 loja física, 5 site, 6 app), **não** do texto |
| Status | enums existentes (`STATUS_PEDIDO`, `STATUS_PAGAMENTO`) |
| Booleanos | `true`/`false` |
| Texto livre | trim, UTF-8 |

Regras gerais: **sempre guardar o valor original** (staging + `valor_original` na ocorrência);
valor que não converte com segurança ⇒ `NULL` ou descarte, sempre com ocorrência `PENDENTE`/`DESCARTADO`;
enums novos em `src/entities` com `CheckConstraint` via `valor_em`.

## Registro de decisões

Para cada problema: o que encontramos · onde (arquivo/tabela/campo) · quantos registros · o que
decidimos · por quê · impacto no número final. Sempre quantificado ("Fizemos X por causa de Y, e
isso muda o faturamento em Z"). Sem número exato: melhor estimativa + margem de erro.

## Comandos

```bash
source .venv/bin/activate
set -a && source .env && set +a     # o conftest lê TEST_DATABASE_URL do ambiente
pytest                               # banco casalorenzi_test, recriado do seed a cada teste
alembic upgrade head
python -m src.database.seed          # só popula banco vazio
ruff check src tests alembic
uvicorn src.app:app --reload --port 8000
```
