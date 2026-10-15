# Casa Lorenzi — Backend

API da plataforma integrada Casa Lorenzi (Insper Jr.). **FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · JWT.**

Os formatos de resposta seguem a camada de serviços do frontend (`src/services/*Service.js` e
`src/services/mock/*.js` no repositório `casalorenzi-frontend`). Para o front usar esta API em vez
dos dados simulados, basta `VITE_USE_MOCKS=false` no `.env` do frontend.

## Como rodar

Pré-requisitos: **Python 3.11+** e **PostgreSQL** (16 ou mais novo) rodando na porta 5432.

```bash
# 1. Ambiente virtual e dependências
python -m venv .venv
.venv\Scripts\activate             # Mac/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt

# 2. Configuração (o .env não vai para o git)
copy .env.example .env             # Mac/Linux: cp .env.example .env
#    edite o .env e troque a senha do Postgres em DATABASE_URL e TEST_DATABASE_URL

# 3. Bancos de dados (uma vez só)
createdb -U postgres casalorenzi
createdb -U postgres casalorenzi_test
#    ou, no psql/pgAdmin: CREATE DATABASE casalorenzi; CREATE DATABASE casalorenzi_test;

# 4. Tabelas e dados de demonstração
alembic upgrade head
python -m src.database.seed --recriar

# 5. API
uvicorn src.app:app --reload --port 8000
```

- Documentação interativa (Swagger): http://localhost:8000/docs
- Status: http://localhost:8000/api/health

> **Atualizando de uma versão antiga** (antes da pasta `src/`): rode `pip install -r requirements-dev.txt`,
> `alembic upgrade head` (migra os clientes para a tabela nova sem perder pedidos nem chamados) e
> `python -m src.database.seed --recriar` se quiser os dados de demonstração atualizados.

### Instalando o PostgreSQL

- **Windows:** instalador oficial em https://www.postgresql.org/download/windows/ (porta 5432, locale DEFAULT;
  o Stack Builder do final não é necessário). Anote a senha do usuário `postgres`: ela vai no `.env`.
- **Mac:** `brew install postgresql@16 && brew services start postgresql@16`. Sem senha, a URL fica
  `postgresql+psycopg://SEU_USUARIO@localhost:5432/casalorenzi`.

Se a senha tiver `@ : / # ? %`, escreva esses caracteres codificados na URL (ex.: `@` vira `%40`).

### Ligando o frontend na API

No `.env` do frontend:

```
VITE_API_URL=http://127.0.0.1:8000/api
VITE_USE_MOCKS=false
```

Reinicie o `npm run dev` depois de mudar o `.env`.

## Estrutura de pastas

Segue o padrão de boas práticas da Insper Jr.: **cada pasta tem uma responsabilidade só**.

```
src/
  app.py          porta de entrada: CORS, logs, tratamento de erros e rotas em /api
  config/         o que muda por ambiente (lido do .env)
  database/       conexão com o banco e dados de demonstração (seed/: dados, gerador, carga)
  models/         como cada dado vira tabela — um arquivo por tabela
  entities/       regras do próprio dado: status permitidos, transições, papéis e acessos
  repositories/   a única parte que busca e salva no banco
  use_cases/      o que o sistema faz: as regras de negócio (não conhecem HTTP)
  schemas/        contratos da API: o que entra (camelCase) e o que sai (JSON)
  routers/        rotas finas: validam, conferem acesso, chamam o use case e respondem
  middlewares/    login (JWT), permissões por papel, limite de tentativas e registro das requisições
  integrations/   serviços externos: envio de e-mails pelo Resend (email.py) e os textos (modelos_email.py)
  utils/          funções pequenas: erros de negócio, datas, texto, senhas
alembic/          histórico de mudanças no banco (migrations)
tests/            testes de API (pytest) num banco separado
```

**O caminho de uma requisição:** `routers` → `middlewares` (está logado? pode?) → `use_cases` (regra) →
`repositories` (banco) → `models`; na volta, `schemas` monta a resposta.

**Onde mexer:**

| Quero… | Arquivo |
| --- | --- |
| mudar uma regra (ex.: quando aceitar devolução) | `src/use_cases/<assunto>.py` |
| mudar quem acessa um módulo | `src/entities/papeis.py` (`ACESSO`) |
| mudar um status permitido ou transição | `src/entities/<assunto>.py` |
| mudar uma consulta ao banco | `src/repositories/<assunto>_repository.py` |
| adicionar um campo na resposta | `src/schemas/<assunto>.py` (funções `*_saida`) |
| adicionar uma coluna/tabela | `src/models/<tabela>.py` + migration (veja abaixo) |
| mudar o texto de um e-mail | `src/integrations/modelos_email.py` |

### Configurando o Resend (e-mails)

1. Crie a conta em https://resend.com e, em **API Keys**, gere uma chave com permissão *Sending access*.
2. No `.env`: `RESEND_API_KEY=re_...` e `URL_FRONTEND` com o endereço do site (os links dos e-mails apontam para ele).
3. Para testar sem domínio, deixe `EMAIL_REMETENTE=Casa Lorenzi <onboarding@resend.dev>`: o Resend só entrega
   para o e-mail dono da conta. Para mandar a qualquer cliente, em **Domains** adicione o domínio da loja,
   crie no DNS os registros que o Resend mostrar (SPF e DKIM) e use um remetente desse domínio
   (ex.: `Casa Lorenzi <nao-responda@casalorenzi.com.br>`).
4. Confira: `python -m src.integrations.email seu@email.com` envia um e-mail de teste.

Nunca coloque a chave no git; no deploy (Render), cadastre as mesmas variáveis no painel do serviço.

## Modelo de dados

| Módulo | Tabelas |
| --- | --- |
| Núcleo | `lojas` (endereço, telefone, horários, `ativa`, `marca` e `tipo`), `usuarios` (só a equipe: ADMINISTRADOR, LOJISTA, OPERADOR; sem senha enquanto o convite está pendente; os funcionários da Vulto vieram sem e-mail e ficam inativos até ter um) |
| Clientes | `clientes` (CPF e e-mail únicos, e-mail opcional para clientes vindos da Vulto, pelo menos um de CPF/e-mail/telefone, consentimento de marketing; senha só como hash), `tokens_senha` |
| Catálogo | `categorias`, `produtos` (com descrição, composição, cuidados, `marca` e `colecao`), `variacoes` (SKU, com `preco_custo` = último custo, `custo_medio` = média ponderada das notas, `ean` e `ativa`), `sku_alias` (outras grafias do SKU, com vigência), `imagens_produto` (foto enviada no cadastro) |
| Estoque | `estoques` (saldo por **loja + SKU**), `movimentacoes` (histórico com sinal), `transferencias` (com `pedido_id` quando atendem um pedido) |
| Vendas | `pedidos` (com frete e endereço de entrega no e-commerce, `desconto`, `tipo` VENDA/TROCA e `pedido_externo`; cliente opcional nas vendas da Vulto sem cliente), `itens_pedido`, `eventos_pedido` (histórico), `pagamentos`, `devolucoes` (devolução da Vulto sem venda de origem: só a `variacao_id`) |
| Atendimento | `tipos_solicitacao`, `atendimentos` (`canal` SITE/WHATSAPP/INSTAGRAM/EMAIL, `contato` e `contato_nome`; cliente opcional nos da Vulto cujo contato não identifica ninguém), `mensagens`, `anexos` (foto) |
| Administração | `config_frete` e `frete_regioes` (frete configurável), `log_acoes` (quem fez o quê) |
| Vulto+ | `contas_pontos` (saldo e categoria por cliente), `movimentos_pontos` (extrato com sinal e validade) |
| Migração da Vulto | `de_para` (cada registro migrado aponta para a origem), `migracao_ocorrencias` (problemas nos dados e o que foi feito) |

**Duas marcas, uma plataforma.** Desde a compra da Vulto, `lojas` e `produtos` têm `marca`
(`LORENZI` ou `VULTO`) e `lojas` tem `tipo` (`FISICA`, `CD` ou `VIRTUAL`); pedidos, estoques e
atendimentos herdam a marca pela loja ou pelo produto. Cliente não tem marca: a mesma pessoa é um
registro só. Os canais são `Loja física`, `E-commerce` e `App`. O site (vitrine, página Lojas,
checkout e expedição) continua só com a Casa Lorenzi; o painel vê as duas marcas.

**Um login só para equipe e clientes.** O cliente cria a conta no checkout (nome, CPF, e-mail,
telefone e senha) e entra pelo mesmo `POST /auth/login`; o token traz o papel `CLIENTE`, que só
abre a área do cliente (nunca as rotas do painel). **Para o site, o id do cliente é o CPF**
(11 dígitos, sem pontuação): é ele que sai em `usuario.id` no login, em `clienteId` de pedidos e
chamados e nas rotas `/clientes/{cpf}/...`. Por dentro, o banco continua ligando tudo pelo número da
tabela `clientes`, que nunca sai da API; assim a exclusão de conta pode apagar o CPF sem quebrar os
pedidos. Nos logs da API, o CPF que aparece no caminho sai mascarado (`*********03`).

## Rotas

Todas sob o prefixo `/api`. As rotas internas exigem `Authorization: Bearer <token>`, obtido em
`POST /api/auth/login`. Detalhes de cada parâmetro e resposta em `/docs`.

| Método | Rota | Quem acessa |
| --- | --- | --- |
| POST | `/auth/login` · GET `/auth/me` | público · logado (equipe ou cliente) |
| POST | `/auth/cadastro` (conta do cliente; já devolve a sessão), `/auth/esqueci-senha`, `/auth/redefinir-senha` | público |
| GET | `/lojas?marca` (com endereço, telefone, horários, `ativa`, `marca` e `tipo`; visitante e cliente só veem as da Casa Lorenzi), `/categorias`, `/tipos-solicitacao` | público |
| GET, PUT · PUT · POST | `/conta` · `/conta/senha` · `/conta/exclusao` (configurações da conta) | o próprio cliente |
| GET | `/frete/condicoes` (valores e prazos, sem custo) | público |
| GET, PUT | `/frete/config` · POST `/frete/simulacao` | administrador |
| GET, POST | `/admin/funcionarios` · PUT `/admin/funcionarios/{id}` · PATCH `/admin/funcionarios/{id}/status` · POST `/admin/funcionarios/{id}/convite` | administrador |
| GET, POST | `/admin/lojas` · PUT `/admin/lojas/{id}` (`marca` e `tipo` opcionais; a marca não muda depois do cadastro) | administrador |
| GET | `/admin/log?area&usuarioId&busca` | administrador |
| GET | `/usuarios?papel=` | equipe |
| GET | `/produtos?busca&categoria&ativo&marca`, `/produtos/{id}` (`precoCusto` e `custoMedio` só para o administrador; visitante e cliente só veem a Casa Lorenzi), `/produtos/{id}/imagem` | público (vitrine) |
| GET | `/produtos/sku/{codigo}?data` (variação por qualquer grafia de SKU; `data` resolve código reaproveitado) | equipe |
| POST, PUT | `/produtos`, `/produtos/{id}` (com `genero`, `estacao`, `precoCusto`, `imagem` e `removerImagem`; `genero` obrigatório no cadastro) | administrador |
| DELETE | `/produtos/{id}` (remove do catálogo; o histórico continua) | administrador |
| GET | `/estoque?busca&lojaId&categoria&status&variacaoId`, `/estoque/{id}` | equipe |
| GET | `/estoque/posicao?data&lojaId&busca&marca&agrupar` (saldo em qualquer data, por item ou por produto) | equipe |
| GET, POST | `/movimentacoes` (filtros: `estoqueId&lojaId&tipo&de&ate&busca`) | equipe |
| GET, POST | `/transferencias` · PATCH `/transferencias/{id}` (status) | administrador, operador |
| POST | `/checkout` (o cliente vem do token) | cliente logado |
| GET | `/pedidos?status&lojaId&canal&busca&marca` (padrão: só a Casa Lorenzi; `VULTO` ou `TODAS`), `/pedidos/{id}` | equipe |
| GET | `/pedidos/vulto/{referencia}` (venda da Vulto pelo id antigo, pelo número do site/app ou pelo VLT-...) | equipe |
| PATCH | `/pedidos/{id}` (loja de expedição ou status) | equipe |
| GET | `/pedidos/{id}/pagamentos` | equipe |
| POST | `/pedidos/{id}/devolucoes` · GET `/devolucoes?de&ate&lojaId` | equipe |
| GET · GET, PATCH | `/atendimentos?busca&tipoSolicitacaoId&responsavelId&lojaId&marca&canal` · `/atendimentos/{id}` (com `outrosAtendimentos` da mesma pessoa e `pedidosDoCliente`) | administrador, lojista |
| POST | `/atendimentos` (cliente: abre para si; equipe: em nome do cliente), `/atendimentos/{id}/mensagens` (aceita `anexo`) | administrador, lojista, cliente dono |
| GET | `/clientes?busca` | administrador, lojista |
| GET | `/clientes/unificado?cpf&email&telefone` (a mesma pessoa nas duas marcas: pedidos da Casa Lorenzi e da Vulto, conta Vulto+) | administrador, lojista |
| GET | `/clientes/{id}`, `/clientes/{id}/pedidos`, `/clientes/{id}/pedidos/{numero}`, `/clientes/{id}/atendimentos`, `/clientes/{id}/atendimentos/{aid}` | administrador, lojista, o próprio cliente |
| GET | `/clientes/{id}/vulto-mais` (extrato de pontos do Vulto+: saldo, categoria, a vencer e movimentos) | administrador, lojista, o próprio cliente |
| GET | `/dashboard/resumo?lojaId&marca` | equipe |
| GET | `/financeiro/resumo?de&ate&comparar&agrupar&lojas&canais&categorias&generos&marcas` (sem `marcas`, soma as duas) | administrador |
| GET | `/financeiro/faturamento?de&ate&marca` (mês × loja × canal, com e sem frete, devoluções e líquido) | administrador |
| GET | `/financeiro/faturamento/comparativo-vulto?de&ate` (relatório do sistema da Vulto × nosso número, com a diferença por ajuste) | administrador |
| GET | `/diretoria/numeros` (faturamento, estoque e passivo da Vulto, com explicação, decisões e margem) · `/diretoria/numeros/{secao}.csv` (`faturamento`, `ponte`, `estoque-lojas`, `estoque-produtos`, `passivo`; Excel em português) | administrador |
| GET | `/financeiro/vulto-mais/passivo?data` (pontos válidos do Vulto+ em R$, cenários Ouro 12/18 meses e a faixa mínima/máxima; padrão 01/10/2026) | administrador |

## Regras importantes

- **Conta do cliente e checkout:** só compra quem está logado com conta de cliente (conta da equipe
  recebe 401). Preço e frete são sempre recalculados no servidor. O cliente só vê os próprios
  pedidos e chamados: o id de outro cliente responde 404. CPF ou e-mail já usados (inclusive por
  clientes antigos e pela equipe) dão 409; clientes antigos criam a senha por "Esqueceu a senha?".
- **Configurações da conta:** o cliente vê e edita nome, e-mail e celular (o CPF não muda),
  troca a senha e exclui a conta. Trocar o e-mail e excluir pedem a senha; senha errada responde
  422. A exclusão apaga os dados pessoais (`excluido_em`), o token deixa de valer e os pedidos e
  chamados ficam anônimos; CPF e e-mail ficam livres para uma conta nova.
- **Esqueceu a senha:** link de uso único (30 minutos) para `/login/nova-senha?token=...`, enviado
  por e-mail; com `LINK_SENHA_NA_RESPOSTA=true` (só demonstração) ele volta também na resposta. A
  resposta é a mesma exista ou não a conta. No máximo 3 pedidos por e-mail e 10 por IP a cada 15
  minutos (429); o contador fica na memória do servidor (vale para uma instância).
- **E-mails (Resend):** link de nova senha, convite de funcionário e confirmação do pedido. Saem em
  segundo plano, depois de gravar no banco; falha do Resend fica no log e não desfaz a operação. Sem
  `RESEND_API_KEY`, o conteúdo vai para o log da API. Veja "Configurando o Resend".
- **Pedidos por loja:** Lojista e Operador só veem, alteram e devolvem pedidos que a própria loja
  expede (o `lojaId` da consulta é ignorado; pedido de outra loja responde 404). Só o Administrador
  troca a loja de expedição (os demais: 403).
- **Central administrativa (só Administrador):** funcionário novo nasce sem senha e recebe um
  convite (link de uso único, 7 dias) para criá-la; até lá, o login responde que falta criar a
  senha. Desativado recebe 403 no login (só depois da senha certa) e a sessão aberta deixa de valer.
  Ninguém desativa a própria conta e sempre fica pelo menos um Administrador ativo. Loja nova
  nasce com estoque zerado de todas as variações; loja desativada sai do site, da expedição e das
  transferências automáticas. O convite vai por e-mail; com `LINK_SENHA_NA_RESPOSTA=true`
  o link volta também na resposta (só demonstração).
- **Log de ações:** funcionários, lojas, frete, produtos (preço, custo, foto), pedidos,
  transferências e movimentações de estoque gravam quem fez (do token), quando e o que mudou,
  na mesma transação da ação.
- **Frete configurável:** valor, custo e prazo por região do CEP, mínimo do frete grátis e
  Expresso liga/desliga, em `config_frete` e `frete_regioes`. O checkout usa a configuração do
  momento e guarda o custo no pedido; só o Administrador vê o custo (no frete e nos produtos).
- **Remover produto:** marca `removido_em` (e `ativo = false`) em vez de apagar, porque pedidos,
  vendas e movimentações apontam para as variações. O produto some da loja, do painel e do estoque
  atual (a posição em data passada ainda o mostra), e não recebe movimentações nem transferências.
  Com pedido em processamento ou transferência pendente da peça, responde 409. Os SKUs continuam
  reservados.
- **Foto do produto:** JPG, PNG ou WebP de até 2 MB (conferida pelo conteúdo), guardada em
  `imagens_produto` e servida em `/api/produtos/{id}/imagem`. `imagemUrl` é um link absoluto
  (defina `URL_PUBLICA_API` atrás de um proxy); trocar para S3 depois muda só onde o arquivo fica.
- **Reserva no checkout:** a peça vendida fica prometida desde a compra, embora só saia do estoque no
  envio. O disponível para venda é, por loja, o saldo + o que está a caminho dela (transferências) −
  as peças de pedidos ainda não enviados que ela expede − as transferências solicitadas que vão sair
  dela. Somado nas lojas ativas, é o `disponivel` da vitrine (o `estoqueTotal` segue sendo o físico).
  O checkout trava os saldos das peças da sacola (`SELECT ... FOR UPDATE`): duas compras da última
  peça ao mesmo tempo passam uma de cada vez, e a segunda recebe 409 ("esgotou").
- **Expedição:** cada pedido sai da loja com mais peças da sacola livres (empate: a loja do mesmo
  estado do CEP). O que faltar nela vira transferência automática (`SOLICITADA`, ligada ao pedido),
  só de peças livres: uma peça prometida a outro pedido não é puxada de novo.
  O envio (`PROCESSANDO → ENVIADO`, com código de rastreio) só é liberado com todas as peças na loja e
  baixa o estoque (`VENDA`). Cancelar (`PROCESSANDO → CANCELADO`) estorna o pagamento e cancela as
  transferências ainda não enviadas.
- **Estoque = loja + SKU.** O saldo nunca é editado direto: toda mudança é uma movimentação com
  quantidade com sinal, e o saldo nunca fica negativo.
- **Transferências:** `SOLICITADA → EM_TRANSITO` (baixa na origem) `→ CONCLUIDA` (entrada no destino);
  `SOLICITADA → CANCELADA`. Outras mudanças devolvem 409.
- **Devoluções:** por item do pedido; a peça volta ao estoque da loja com movimentação `DEVOLUCAO`.
  Não deixa devolver mais que o comprado; pedido cancelado ou em separação recusa (409). O frete não é
  devolvido. Quando todas as peças voltam, os pagamentos aprovados viram `ESTORNADO`.
- **Fotos nos chamados:** JPG, PNG ou WEBP de até 2 MB, conferindo se o conteúdo é mesmo imagem.
  Entram como `anexo: { nome, tipo, conteudoBase64 }` e saem como `anexo: { id, nome, tipo, url }`.
- **Quem fez a ação vem do token.** Campos como `usuarioId`, `autorId` e `autorTipo` enviados pelo
  frontend são aceitos, mas ignorados.
- **Erros** seguem o padrão do FastAPI, `{ "detail": "mensagem" }`, com o status certo
  (401, 403, 404, 409, 410, 422, 429). Erro inesperado responde 500 genérico com um código; o detalhe
  fica no log do servidor.
- **Logs:** toda requisição é registrada com método, rota, status, duração e `request_id` (também
  devolvido no cabeçalho `X-Request-ID`). Nível em `LOG_LEVEL`.
- **Datas** saem em milissegundos (como `Date.now()`); filtros de data usam `aaaa-mm-dd` no fuso `FUSO_HORARIO`.

## Dados de demonstração

`python -m src.database.seed --recriar` apaga tudo e carrega de novo. Usa o **mesmo gerador e as
mesmas sementes** do frontend (`src/data/seed`), então os dados ficam idênticos aos dos mocks. As datas
são relativas ao momento da carga. Sem `--recriar`, só popula se o banco estiver vazio.

| Perfil | E-mail | Acesso |
| --- | --- | --- |
| Administrador | helena@casalorenzi.com.br | tudo |
| Lojista | rafael.monteiro@casalorenzi.com.br | dashboard (só a própria loja), pedidos, estoque, atendimento |
| Operador | diego.almeida@casalorenzi.com.br | dashboard, pedidos, estoque, transferências |

A senha da equipe e dos clientes de demonstração está em `src/database/seed/dados.py`
(`SENHA_DEMO`). Clientes entram pelo mesmo login (ex.: mariana.costa@gmail.com, CPF 158.813.998-03).

## Migrações (Alembic)

Sempre que mudar algo em `src/models/`:

```bash
alembic revision --autogenerate -m "descreva a mudança"
# confira o arquivo gerado em alembic/versions/ (o autogenerate não move dados)
alembic upgrade head
```

Outros comandos: `alembic current`, `alembic history`, `alembic downgrade -1`.
**A migration vai no mesmo commit do código que depende dela**, para o time aplicar com `alembic upgrade head`.
Nunca mude o banco à mão.

## Migração dos dados da Vulto

Os dados da Vulto entram uma única vez, por um pipeline idempotente (pode rodar de novo sem
duplicar) que nunca apaga dados da Casa Lorenzi. O legado (`vulto-legado-back/`) é só leitura.
Regras e decisões em `CLAUDE.md` e `docs/registro_decisoes.md`.

**Passo a passo** (em produção, do seu computador com a URL externa do banco em `DATABASE_URL`):

```bash
alembic upgrade head                                       # tabelas e colunas da união
python -m src.migracao_vulto --tudo                        # staging e todos os domínios, na ordem
python -m src.relatorios.diretoria --saida docs/numeros_diretoria   # os números da diretoria (JSON e CSV)
python -m src.relatorios.registro_decisoes                 # docs/registro_decisoes.md, das ocorrências
```

Para rodar uma parte só:

```bash
python -m src.migracao_vulto --dominio staging   # só a cópia crua do legado
python -m src.migracao_vulto --dominio lojas     # um domínio só (lojas, produtos, clientes, usuarios,
                                                 # vendas, estoque, fidelidade, atendimento)
```

**O que a união acrescentou.** Tabelas: `sku_alias`, `contas_pontos`, `movimentos_pontos`, `de_para`,
`migracao_ocorrencias` e o schema `legado_vulto` (staging); colunas de marca, canal e origem nas tabelas
existentes (veja "Modelo de dados"). Rotas (veja "Rotas"): o filtro `marca` em lojas, produtos, pedidos,
estoque, dashboard e financeiro; `/produtos/sku/{codigo}`, `/pedidos/vulto/{referencia}`,
`/clientes/unificado`, `/clientes/{id}/vulto-mais`, `/estoque/posicao?agrupar=produto`,
`/financeiro/faturamento`, `/financeiro/faturamento/comparativo-vulto`, `/financeiro/vulto-mais/passivo`,
`/diretoria/numeros` e os filtros `marca` e `canal` em `/atendimentos`.

Os arquivos do legado vêm de `VULTO_DADOS` no `.env` (padrão: `../vulto-legado-back/data`).

**Staging (schema `legado_vulto`).** Primeira camada: cada tabela do `vulto.db`, cada aba das
planilhas e o export do atendimento viram uma tabela crua (`db__vendas`, `catalogo__verao_26`,
`clientes__clientes`, `atendimentos`...), com todas as colunas em texto, sem limpeza, e com
`_arquivo`, `_aba` e `_linha` (a linha como aparece no Excel; no `vulto.db`, o rowid). Das planilhas
vêm também `_tipos` (o tipo que o Excel deu à célula, ex.: data) e a formatação da linha
(`_tachado`, `_cor_fonte`, `_cor_fundo`). `legado_vulto._cargas` lista cada tabela com a origem, a
linha do cabeçalho, os nomes originais das colunas e as contagens. As senhas em texto puro dos
funcionários não são copiadas e a `senha_master` entra mascarada. Cada carga recria o schema.

**Padronização** (`src/migracao_vulto/normalizacao.py`): funções puras e testadas usadas por todos os
domínios (dinheiro, datas com fuso, CPF, e-mail, telefone E.164, SKU, EAN, cor, tamanho, categoria,
canal, status). Valor que não converte com segurança não é chutado: vira ocorrência.

**Produtos** (`--dominio produtos`). Cada modelo do catálogo vira um produto `VULTO` e cada cor +
tamanho uma variação com o SKU canônico `VLT-CAT-NNN-COR-TAM`; todas as outras grafias (código curto
do CD, digitação do fiscal, vendas, entradas, contagem) vão para `sku_alias`. Código reaproveitado por
outra peça vira outro produto (SKU com `-2024`) e as grafias em comum ganham vigência por data.
Preço: o mais frequente da aba; entre coleções, `REGRA_PRECO` em `produtos.py` (padrão `MENOR`,
Operações/Financeiro; `MAIS_NOVA` é a regra de Compras). Linha tachada ou vermelha = variação
inativa. A categoria vem do prefixo do SKU (Calças, Bermudas e Shorts e Não catalogado são novas;
o resto usa as da Casa Lorenzi).

**Clientes** (`--dominio clientes`). Aba Clientes, clientes antigos, `cliente_ref` das vendas e das
compras e os contatos do atendimento viram um cliente por pessoa (CPF → e-mail → telefone; CPFs
diferentes nunca se juntam), também contra os clientes da Casa Lorenzi, que nunca são sobrescritos
(só os campos vazios são completados). Consentimento de mensagens só com "sim" explícito e sem
"não ligar"; telefone sem DDD fica vazio; quem só aparece nas vendas entra com o nome provisório
"Cliente Vulto (sem nome)". Cliente com CPF ganha conta Vulto+ com a categoria declarada na planilha.
Telefones da Vulto ficam em E.164 (`+5511...`); os da Casa Lorenzi continuam como foram cadastrados.

**Vendas** (`--dominio vendas`). As vendas do `vulto.db` viram pedidos `VLT-00001`... (canal pela loja do
legado; online sai do CD Cajamar, ship from store de Pinheiros), com itens, pagamento e histórico. Total e
itens em centavos (app) são detectados pelo preço do catálogo; frete embutido e desconto não registrado
saem da conta da venda; status vazio = pago; troca = pedido `TROCA` (fora da receita); valor negativo =
devolução, ligada à venda original quando dá. Ficam de fora as vendas de teste (TI/QA) e as duplicatas
do app. A planilha manual da Batel (março/26) entra menos o que foi relançado no sistema, que volta para
a data real. Faturamento = vendas não canceladas e com pagamento que não está só pendente, menos as
devoluções; `/financeiro/faturamento/comparativo-vulto` mostra a diferença para o relatório da Vulto.

**Estoque** (`--dominio estoque`). A tabela `estoque` da Vulto (sem histórico, com saldos negativos) só
serve de comparação: o histórico é reconstruído em `movimentacoes` a partir das notas de entrada, das
transferências (envio e recebimento da mesma peça contam uma vez), das vendas e das devoluções migradas.
A contagem de set/26 é a âncora (ajuste no dia da contagem; Eldorado, Savassi e Batel sem data na
planilha: 30/09, estimado; a Savassi contou por modelo e foi rateada) e o saldo de abertura (01/01/2025),
desconhecido, é o menor que deixa o histórico sem saldo negativo. Antes da contagem, o histórico é
derivado; o saldo em 01/10/2026 é o contado mais os movimentos depois dele.

**Funcionários** (`--dominio usuarios`). Os funcionários da Vulto viram usuários **inativos, sem e-mail
e sem senha** (as senhas do legado estão em texto puro e não migram, nem a `senha_master`). Vendedor e
gerente viram LOJISTA da loja; o operador do CD, OPERADOR; Diego, Paula e Marina, ADMINISTRADOR. Contas de
teste e genéricas ficam de fora. Os atendentes do SAC (Marcos, Júlia, Renata) viram LOJISTA do CD. Para dar
acesso: na Central administrativa, cadastre o e-mail, reative e reenvie o convite.

**Fidelidade** (`--dominio fidelidade`). O Vulto+ vira `contas_pontos` + `movimentos_pontos` (pontos só
com CPF). Saldo inicial: a coluna Pontos da planilha, congelada em 01/01/2025 ("2.203" = 2203; "2,7k",
estimado; duplicados somam). Depois, os movimentos do `vulto.db` corrigidos: o crédito inflado pelo bug do
app v3.4 (pontos sobre centavos) volta ao valor certo e os ajustes manuais dessa correção saem; venda
aguardando pagamento, de teste ou duplicada não pontua; venda cancelada sem estorno é estornada. Resgates
anotados só na planilha (2025 em diante) são debitados. Regras em `src/entities/fidelidade.py`: categoria
pelos pontos do ano, validade FIFO de 12 meses (Ouro 18, o combinado, é o gravado), saldo nunca negativo.
O passivo (`/financeiro/vulto-mais/passivo`) recalcula a validade nos dois cenários do Ouro e mostra a
faixa: R$ 0,05 por ponto (vigente desde mar/2025) a R$ 0,10 (o que o sistema da Vulto seguiu dando), com o
dobro do online e o bônus Ouro que o sistema nunca aplicou no máximo.

**Atendimento** (`--dominio atendimento`). Cada linha do CSV já é um atendimento inteiro: a conversa
embutida ("[Atendente]: ...", "[Bot]: ...") vira `mensagens`; linhas repetidas e spam ficam de fora; linhas
do mesmo contato e tipo a até 72 h viram um atendimento só. O cliente vem do contato (telefone ou e-mail) ou,
se o contato não identifica ninguém (@ do Instagram, telefone sem DDD), do pedido citado; sem nenhum dos
dois, o atendimento fica sem cliente, com o contato guardado. O pedido vem da coluna `pedido` (número no
site/app ou id da venda) ou do texto. Tipos que faltavam (Pontos Vulto+, Pagamento, Cancelamento, Elogio,
Informações da loja) são criados inativos, para não aparecerem no site da Casa Lorenzi sem decisão.

Ao final, imprime lidos, carregados, corrigidos e descartados por domínio. Contra o banco do Render,
rode do seu computador com a "External Database URL": `DATABASE_URL="postgresql+psycopg://..."`.
**Atenção:** `python -m src.database.seed --recriar` apaga tudo, inclusive o que veio da Vulto;
depois dele, rode a migração de novo.

**Números da diretoria e registro de decisões.** Depois da migração, `python -m src.relatorios.diretoria`
gera o JSON e os CSVs com as três respostas (faturamento com a ponte até o relatório da Vulto, estoque em
01/10/2026 e passivo de pontos), e `python -m src.relatorios.registro_decisoes` gera o
`docs/registro_decisoes.md` (cada problema, a decisão, o porquê e o impacto, e o apêndice com todas as
ocorrências). Os gerados com o banco de validação estão em `docs/`.

## Testes

Rodam num banco separado (`TEST_DATABASE_URL` no `.env`), recriado a partir do seed a cada teste:

```bash
pytest
```

Rode os testes antes de cada commit. Toda regra nova ganha teste.

## Padrão de código e commits

```bash
ruff check src tests alembic              # erros e imports
ruff format src tests --exclude "src/database/seed/*"
```

Commits no formato convencional, no imperativo, sem ponto final e com até 50 caracteres no título,
um assunto por commit: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `revert:`.

Exemplo: `feat: registra devoluções com volta ao estoque`.

## Deploy (Render)

A API e o banco vão para o Render; o site, para a Vercel (passo a passo no README do frontend).
O arquivo `render.yaml` descreve tudo, então o Render cria os dois de uma vez:

1. No painel do Render: **New > Blueprint** e escolha este repositório.
2. Ele pede `CORS_ORIGINS` e `URL_FRONTEND`: os dois são o endereço do site na Vercel (ex.:
   `https://casalorenzi.vercel.app`). Se ainda não souber, coloque o endereço que pretende usar e
   corrija depois em **Environment** (salvar refaz o deploy).
3. O Render cria o banco `casalorenzi-db` e a API `casalorenzi-api`. A cada deploy, o start command
   roda `alembic upgrade head` (tabelas em dia) e `python -m src.database.seed`, que só carrega os
   dados de demonstração quando o banco está vazio; depois sobe a API. Confira em
   `https://SUA-API.onrender.com/api/health`.

O `render.yaml` já define: `JWT_SECRET` aleatório (gerado pelo Render), `DATABASE_URL` do banco,
`PYTHON_VERSION`, `EMAIL_REMETENTE` (domínio `mail.casalorenzi.site`, verificado no Resend) e
`LINK_SENHA_NA_RESPOSTA=false`. Na criação, o Render pede também a `RESEND_API_KEY`. O link das
fotos dos produtos usa sozinho o endereço público do serviço (`RENDER_EXTERNAL_URL`).

Os e-mails (nova senha, convite e confirmação do pedido) saem de verdade pelo Resend; os links
apontam para `URL_FRONTEND`. Os dados ainda são de **demonstração** (contas com a senha de
demonstração): antes de um uso real, troque as senhas e, no frontend, defina `VITE_MODO_DEMO=false`.

Para recarregar os dados de demonstração do banco do Render (apaga tudo), rode do seu computador
com a "External Database URL" que o Render mostra na página do banco:

```bash
DATABASE_URL="postgresql://..." .venv/bin/python -m src.database.seed --recriar
```

No plano grátis, a API "dorme" sem uso e o primeiro acesso seguinte demora perto de um minuto.

## Próximos passos

- Integração real de pagamento (hoje simulado: todo checkout é aprovado).
- Vulto+ na plataforma: creditar e resgatar pontos nas vendas novas e rodar os vencimentos depois de
  01/10/2026 (hoje o saldo das contas é o da virada).
