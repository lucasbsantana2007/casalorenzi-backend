# Casa Lorenzi — Backend

API da plataforma integrada Casa Lorenzi. **FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · JWT.**

As rotas e os formatos de resposta seguem exatamente a camada de serviços do frontend
(`src/services/*Service.js` e `src/services/mock/*.js`). Para trocar os mocks pela API real,
basta usar `VITE_USE_MOCKS=false` no `.env` do frontend.

## Como rodar

Pré-requisitos: Python 3.11+ e PostgreSQL rodando localmente.

```bash
# 1. Ambiente virtual e dependências
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configuração
cp .env.example .env               # ajuste DATABASE_URL com usuário e senha do seu Postgres

# 3. Banco de dados
createdb casalorenzi               # ou: CREATE DATABASE casalorenzi; no psql / pgAdmin
alembic upgrade head               # cria as tabelas
python -m app.seed                 # carrega os dados de demonstração

# 4. API
uvicorn app.main:app --reload --port 8000
```

- Documentação interativa (Swagger): http://localhost:8000/docs
- Status: http://localhost:8000/api/health

### Instalando o PostgreSQL no Mac

```bash
brew install postgresql@16
brew services start postgresql@16
createdb casalorenzi
```

Com o Postgres do Homebrew o usuário é o do seu Mac e não há senha:
`DATABASE_URL=postgresql+psycopg://SEU_USUARIO@localhost:5432/casalorenzi`.

### Ligando o frontend na API

No `.env` do frontend:

```
VITE_API_URL=http://127.0.0.1:8000/api
VITE_USE_MOCKS=false
```

Reinicie o `npm run dev` depois de mudar o `.env`.

## Dados de demonstração

`python -m app.seed` usa o **mesmo gerador e as mesmas sementes** do frontend (`src/data/seed`),
então lojas, produtos, histórico de estoque, transferências, pedidos e atendimentos ficam idênticos
aos dos mocks. As datas são relativas ao momento da carga.

- `python -m app.seed --recriar` apaga tudo e carrega de novo (útil para "resetar" a demo).
- Todas as contas usam a senha **`lorenzi2026`**.

| Perfil        | E-mail                               | Acesso                                      |
| ------------- | ------------------------------------ | ------------------------------------------- |
| Administrador | helena@casalorenzi.com.br            | Tudo                                        |
| Lojista       | rafael.monteiro@casalorenzi.com.br   | Dashboard (só a própria loja), estoque, atendimento |
| Operador      | diego.almeida@casalorenzi.com.br     | Dashboard, estoque, transferências          |
| Cliente       | mariana.costa@gmail.com              | Portal do cliente                           |

## Rotas

Todas sob o prefixo `/api`. As rotas internas exigem `Authorization: Bearer <token>`,
obtido em `POST /api/auth/login`.

| Método | Rota | Quem acessa |
| --- | --- | --- |
| POST | `/auth/login` | público |
| GET | `/auth/me` | logado |
| GET | `/lojas`, `/categorias`, `/tipos-solicitacao` | público |
| GET | `/usuarios?papel=` | equipe |
| GET | `/produtos?busca&categoria&ativo`, `/produtos/{id}` | público (vitrine) |
| POST, PUT | `/produtos`, `/produtos/{id}` | administrador |
| GET | `/estoque?busca&lojaId&categoria&status&variacaoId` | equipe |
| GET | `/estoque/{id}` | equipe |
| GET | `/estoque/posicao?data&lojaId&busca` | equipe |
| GET | `/movimentacoes?estoqueId&lojaId&tipo&de&ate&busca` | equipe |
| POST | `/movimentacoes` | equipe |
| GET, POST | `/transferencias` | administrador, operador |
| PATCH | `/transferencias/{id}` (status) | administrador, operador |
| GET | `/atendimentos?busca&tipoSolicitacaoId&responsavelId&lojaId` | administrador, lojista |
| POST | `/atendimentos` (abrir solicitação) | cliente (para si) ou administrador/lojista |
| GET | `/atendimentos/{id}` | administrador, lojista ou o próprio cliente |
| PATCH | `/atendimentos/{id}` (status, responsável) | administrador, lojista |
| POST | `/atendimentos/{id}/mensagens` | administrador, lojista ou o próprio cliente |
| GET | `/clientes/{id}`, `/clientes/{id}/atendimentos[/{id}]`, `/clientes/{id}/pedidos[/{numero}]` | o próprio cliente, administrador, lojista |
| GET | `/dashboard/resumo?lojaId` | equipe |
| GET | `/financeiro/resumo?de&ate&comparar&agrupar&lojas&canais&categorias&generos` | administrador |

Regras importantes:

- **Estoque = loja + variação (SKU).** O saldo nunca é editado direto: toda mudança é uma
  movimentação com quantidade com sinal, e o saldo nunca fica negativo.
- **Transferências:** `SOLICITADA → EM_TRANSITO` (baixa na origem) `→ CONCLUIDA` (entrada no destino);
  `SOLICITADA → CANCELADA`. Outras mudanças devolvem 409.
- **Quem fez a ação vem do token.** Campos como `usuarioId`, `autorId` e `autorTipo` enviados pelo
  frontend são aceitos, mas ignorados.
- Datas saem em milissegundos (como `Date.now()`); filtros de data usam `aaaa-mm-dd` no fuso `FUSO_HORARIO`.
- Erros seguem o padrão do FastAPI: `{ "detail": "mensagem" }`.

## Estrutura

```
app/
  main.py          # cria o app, CORS e registra as rotas em /api
  config.py        # variáveis do .env
  database.py      # engine e sessão do SQLAlchemy
  models.py        # tabelas
  schemas.py       # corpos de requisição (camelCase)
  views.py         # monta o JSON no formato que o frontend espera
  security.py      # senhas, JWT e permissões por papel
  services.py      # regras compartilhadas (movimentar estoque)
  seed.py          # dados de demonstração
  routers/         # uma rota por módulo da interface
alembic/           # migrações
tests/             # testes de regras e permissões
```

## Migrações (Alembic)

Sempre que mudar `app/models.py`:

```bash
alembic revision --autogenerate -m "descreva a mudança"
# confira o arquivo gerado em alembic/versions/
alembic upgrade head
```

Outros comandos úteis: `alembic current`, `alembic history`, `alembic downgrade -1`.
Faça commit do arquivo de migração junto com a mudança no modelo, para o grupo aplicar com `alembic upgrade head`.

## Testes

Os testes usam um banco separado, recriado a cada teste:

```bash
pip install -r requirements-dev.txt
createdb casalorenzi_test
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/casalorenzi_test pytest
```
