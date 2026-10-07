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
  middlewares/    login (JWT), permissões por papel e registro das requisições
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

## Modelo de dados

| Módulo | Tabelas |
| --- | --- |
| Núcleo | `lojas` (endereço, telefone, horários e `ativa`), `usuarios` (só a equipe: ADMINISTRADOR, LOJISTA, OPERADOR; sem senha enquanto o convite está pendente) |
| Clientes | `clientes` (CPF e e-mail únicos, senha só como hash; PIN legado), `tokens_senha`, `tokens_pin` |
| Catálogo | `categorias`, `produtos` (com descrição, composição e cuidados), `variacoes` (SKU, com `preco_custo`), `imagens_produto` (foto enviada no cadastro) |
| Estoque | `estoques` (saldo por **loja + SKU**), `movimentacoes` (histórico com sinal), `transferencias` (com `pedido_id` quando atendem um pedido) |
| Vendas | `pedidos` (com frete e endereço de entrega no e-commerce), `itens_pedido`, `eventos_pedido` (histórico), `pagamentos`, `devolucoes` |
| Atendimento | `tipos_solicitacao`, `atendimentos` (sempre de um cliente), `mensagens`, `anexos` (foto) |
| Administração | `config_frete` e `frete_regioes` (frete configurável), `log_acoes` (quem fez o quê) |

**Um login só para equipe e clientes.** O cliente cria a conta no checkout (nome, CPF, e-mail,
telefone e senha) e entra pelo mesmo `POST /auth/login`; o token traz o papel `CLIENTE`, que só
abre a área do cliente (nunca as rotas do painel). O `id` do cliente continua sendo o número da
tabela `clientes`; o CPF é um campo à parte (11 dígitos, único, conferido pelos dígitos verificadores).
O acesso por e-mail + PIN ("Meus pedidos") ficou como legado.

## Rotas

Todas sob o prefixo `/api`. As rotas internas exigem `Authorization: Bearer <token>`, obtido em
`POST /api/auth/login`. Detalhes de cada parâmetro e resposta em `/docs`.

| Método | Rota | Quem acessa |
| --- | --- | --- |
| POST | `/auth/login` · GET `/auth/me` | público · logado (equipe ou cliente) |
| POST | `/auth/cadastro` (conta do cliente; já devolve a sessão), `/auth/esqueci-senha`, `/auth/redefinir-senha` | público |
| GET | `/lojas` (com endereço, telefone, horários e `ativa`), `/categorias`, `/tipos-solicitacao` | público |
| GET, PUT · PUT · POST | `/conta` · `/conta/senha` · `/conta/exclusao` (configurações da conta) | o próprio cliente |
| GET | `/frete/condicoes` (valores e prazos, sem custo) | público |
| GET, PUT | `/frete/config` · POST `/frete/simulacao` | administrador |
| GET, POST | `/admin/funcionarios` · PUT `/admin/funcionarios/{id}` · PATCH `/admin/funcionarios/{id}/status` · POST `/admin/funcionarios/{id}/convite` | administrador |
| GET, POST | `/admin/lojas` · PUT `/admin/lojas/{id}` | administrador |
| GET | `/admin/log?area&usuarioId&busca` | administrador |
| GET | `/usuarios?papel=` | equipe |
| GET | `/produtos?busca&categoria&ativo`, `/produtos/{id}` (`precoCusto` só para o administrador), `/produtos/{id}/imagem` | público (vitrine) |
| POST, PUT | `/produtos`, `/produtos/{id}` (com `genero`, `estacao`, `precoCusto`, `imagem` e `removerImagem`; `genero` obrigatório no cadastro) | administrador |
| GET | `/estoque?busca&lojaId&categoria&status&variacaoId`, `/estoque/{id}` | equipe |
| GET | `/estoque/posicao?data&lojaId&busca` | equipe |
| GET, POST | `/movimentacoes` (filtros: `estoqueId&lojaId&tipo&de&ate&busca`) | equipe |
| GET, POST | `/transferencias` · PATCH `/transferencias/{id}` (status) | administrador, operador |
| POST | `/checkout` (o cliente vem do token) | cliente logado |
| POST | `/meus-pedidos` (legado: e-mail + PIN no corpo) | público |
| POST | `/meus-pedidos/esqueci-pin`, `/meus-pedidos/redefinir-pin` | público |
| POST | `/meus-pedidos/solicitacoes/consulta`, `/meus-pedidos/solicitacoes`, `/meus-pedidos/solicitacoes/{id}/mensagens` | público (e-mail + PIN) |
| GET | `/pedidos?status&lojaId&canal&busca`, `/pedidos/{id}` | equipe |
| PATCH | `/pedidos/{id}` (loja de expedição ou status) | equipe |
| GET | `/pedidos/{id}/pagamentos` | equipe |
| POST | `/pedidos/{id}/devolucoes` · GET `/devolucoes?de&ate&lojaId` | equipe |
| GET · GET, PATCH | `/atendimentos` · `/atendimentos/{id}` | administrador, lojista |
| POST | `/atendimentos` (cliente: abre para si; equipe: em nome do cliente), `/atendimentos/{id}/mensagens` (aceita `anexo`) | administrador, lojista, cliente dono |
| GET | `/clientes?busca` | administrador, lojista |
| GET | `/clientes/{id}`, `/clientes/{id}/pedidos`, `/clientes/{id}/pedidos/{numero}`, `/clientes/{id}/atendimentos`, `/clientes/{id}/atendimentos/{aid}` | administrador, lojista, o próprio cliente |
| GET | `/dashboard/resumo?lojaId` | equipe |
| GET | `/financeiro/resumo?de&ate&comparar&agrupar&lojas&canais&categorias&generos` | administrador |

## Regras importantes

- **Conta do cliente e checkout:** só compra quem está logado com conta de cliente (conta da equipe
  recebe 401). Preço e frete são sempre recalculados no servidor. O cliente só vê os próprios
  pedidos e chamados: o id de outro cliente responde 404. CPF ou e-mail já usados (inclusive por
  clientes antigos e pela equipe) dão 409; clientes antigos criam a senha por "Esqueceu a senha?".
- **Configurações da conta:** o cliente vê e edita nome, e-mail e celular (o CPF não muda),
  troca a senha e exclui a conta. Trocar o e-mail e excluir pedem a senha; senha errada responde
  422. A exclusão apaga os dados pessoais (`excluido_em`), o token deixa de valer e os pedidos e
  chamados ficam anônimos; CPF e e-mail ficam livres para uma conta nova.
- **Esqueceu a senha:** link de uso único (30 minutos) para `/login/nova-senha?token=...`, que por
  enquanto sai no log da API; com `LINK_SENHA_NA_RESPOSTA=true` (só demonstração) ele volta na
  resposta. A resposta é a mesma exista ou não a conta.
- **"Meus pedidos" (legado):** e-mail + PIN de 4 dígitos (só como hash; 5 erros seguidos bloqueiam
  por 15 minutos), com `PIN_LINK_NA_RESPOSTA` para o link de "Esqueci o PIN".
- **Central administrativa (só Administrador):** funcionário novo nasce sem senha e recebe um
  convite (link de uso único, 7 dias) para criá-la; até lá, o login responde que falta criar a
  senha. Desativado recebe 403 no login (só depois da senha certa) e a sessão aberta deixa de valer.
  Ninguém desativa a própria conta e sempre fica pelo menos um Administrador ativo. Loja nova
  nasce com estoque zerado de todas as variações; loja desativada sai do site, da expedição e das
  transferências automáticas. O link do convite sai no log da API; com `LINK_SENHA_NA_RESPOSTA=true`
  ele volta na resposta (só demonstração).
- **Log de ações:** funcionários, lojas, frete, produtos (preço, custo, foto), pedidos,
  transferências e movimentações de estoque gravam quem fez (do token), quando e o que mudou,
  na mesma transação da ação.
- **Frete configurável:** valor, custo e prazo por região do CEP, mínimo do frete grátis e
  Expresso liga/desliga, em `config_frete` e `frete_regioes`. O checkout usa a configuração do
  momento e guarda o custo no pedido; só o Administrador vê o custo (no frete e nos produtos).
- **Foto do produto:** JPG, PNG ou WebP de até 2 MB (conferida pelo conteúdo), guardada em
  `imagens_produto` e servida em `/api/produtos/{id}/imagem`. `imagemUrl` é um link absoluto
  (defina `URL_PUBLICA_API` atrás de um proxy); trocar para S3 depois muda só onde o arquivo fica.
- **Expedição:** cada pedido sai da loja com mais peças da sacola em estoque (empate: a loja do mesmo
  estado do CEP). O que faltar nela vira transferência automática (`SOLICITADA`, ligada ao pedido).
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

A senha da equipe e dos clientes de demonstração e o PIN legado estão em `src/database/seed/dados.py`
(`SENHA_DEMO` e `PIN_DEMO`). Clientes entram pelo mesmo login (ex.: mariana.costa@gmail.com, CPF 158.813.998-03).

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

## Próximos passos

- Enviar por e-mail o link de "Esqueceu a senha?" (hoje sai no log da API).
- Enviar por e-mail o convite dos funcionários novos (hoje sai no log da API).
- Guardar as fotos dos produtos no S3 (hoje ficam no banco).
- Integração real de pagamento (hoje simulado: todo checkout é aprovado).
- Deploy: Render (API + banco) e Vercel (frontend), como no Plano de Execução.
