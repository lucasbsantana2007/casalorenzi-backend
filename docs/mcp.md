# Copiloto no Claude: o servidor MCP (decisões 106, 109, 114 e 115)

O copiloto gerencial também atende fora do painel: no **claude.ai**, no **Claude Code**, no **Claude Desktop** ou
num agente do **n8n**, pelo protocolo MCP (Model Context Protocol). **Toda a equipe** com acesso ao Assistente IA
usa (decisão 115, que substitui a 110), e cada pessoa vê só o que o perfil e a marca dela permitem. Quem pergunta
usa as mesmas consultas, as mesmas regras e as mesmas permissões do painel. Muda só o lugar da conversa.

| Perfil | Consulta | Não consulta |
| --- | --- | --- |
| Administrador do grupo | Tudo, nas duas marcas | — |
| Administrador de uma marca | Tudo, só na marca dele | A outra marca |
| Lojista | Lupe+, pedidos **da própria loja**, atendimentos da marca, estoque e alertas (decisão 118) | Faturamento, vendas, transferências |
| Operador | Pedidos **da própria loja**, estoque, transferências e alertas | Faturamento, vendas, Lupe+, atendimentos |

Pedidos e atendimentos saem sem nome, contato ou mensagens do cliente; nos pedidos, também sem a soma dos valores
(que seria faturamento).

**Dados de um cliente ficam fora do Claude (decisão 120, que desfaz essa parte da 119):** pelo MCP, só números
agregados. O saldo do Lupe+ de um cliente fica no painel: na aba **Atendimento > Lupe+** e no Assistente IA do painel
(`consultar_pontos_cliente`), para Administrador e Lojista. O servidor MCP não lista nem roda essa consulta.

| O quê | Como |
| --- | --- |
| Endereço | `https://<api>/api/conector-mcp` (local: `http://127.0.0.1:8000/api/conector-mcp`) |
| Login | **claude.ai**: login OAuth, com o e-mail e a senha do painel (decisão 114). **Claude Code, Claude Desktop e n8n**: token pessoal (`Authorization: Bearer clmcp_...`), criado em **Inteligência > Conectar ao Claude** |
| O que dá para consultar | 13 das 14 ferramentas do copiloto (com pedidos e atendimentos, decisão 118; os pontos de um cliente ficam só no painel, decisão 120) e `ver_contexto` (data de hoje, até quando há vendas, lojas com os ids, categorias, permissões e definições das métricas) |
| O que não sai | Nada do cliente: pedidos, pontos, devoluções e conta ficam só na Lúcia, no site |
| Permissão | Toda a equipe, conferida **a cada chamada**: papel, marca e conta ativa do dono, como no copiloto do painel |
| Escrita | Nenhuma. As consultas rodam em transação READ ONLY, como no copiloto |

## Conectar no claude.ai (login, decisão 114)

1. No claude.ai, abra **Configurações > Conectores > Adicionar conector personalizado**.
2. Dê um nome (por exemplo "Casa Lorenzi") e cole o endereço `https://casalorenzi-api.onrender.com/api/conector-mcp`.
   Não preencha client ID nem segredo: o claude.ai se cadastra sozinho.
3. Clique em **Conectar**. Abre a página "Conectar Claude à Casa Lorenzi": entre com o e-mail e a senha do painel
   (cada pessoa com a própria conta) e clique em **Entrar e autorizar**.
4. De volta ao claude.ai, ative o conector na conversa e pergunte.

A conexão aparece em **Inteligência > Conectar ao Claude** com o nome "Claude (login)" e se revoga por lá, como um
token. Ela usa a mesma auditoria e o mesmo limite de consultas. O claude.ai renova o acesso sozinho, sem pedir o
login de novo, até a conexão vencer (90 dias) ou ser revogada.

Como funciona por dentro (a especificação de autorização do MCP, OAuth 2.1):

| Etapa | Endereço |
| --- | --- |
| O servidor MCP responde 401 com o endereço da ficha do recurso | `WWW-Authenticate: Bearer resource_metadata=...` |
| Ficha do recurso (RFC 9728) | `/.well-known/oauth-protected-resource/api/conector-mcp` |
| Ficha do servidor de autorização (RFC 8414) | `/.well-known/oauth-authorization-server` |
| Cadastro do app: automático (RFC 7591) ou pela ficha publicada no domínio do app (CIMD, só `claude.ai` e `claude.com`) | `POST /api/oauth/registro` |
| Página de login e autorização | `GET/POST /api/oauth/autorizar` |
| Troca do código e renovação | `POST /api/oauth/token` |
| Desconectar pelo app (RFC 7009) | `POST /api/oauth/revogar` |

Garantias: PKCE S256 obrigatório; o código vale 10 minutos e uma vez só (usado de novo, a conexão cai); o acesso
vale 60 minutos (`OAUTH_ACESSO_MINUTOS`); a renovação vale 30 dias (`OAUTH_RENOVACAO_DIAS`) e é trocada a cada uso
(usada de novo, a conexão cai); o acesso só vale para este servidor (`resource`, RFC 8707); a volta leva `iss`
(RFC 9207); a página não pode ser embutida em outro site nem fica em cache; login com no máximo 10 tentativas a
cada 10 minutos por IP e por e-mail. Endereço de volta só `https` ou `http` no próprio computador. Do banco, só o
sha256 dos tokens. Opcional no Render: `URL_API` (o endereço público da API; sem ele, vale o endereço pelo qual o
pedido chegou) e `OAUTH_CIMD_DOMINIOS`.

## Conectar com token (Claude Code, Claude Desktop, n8n)

1. No painel, abra **Inteligência > Conectar ao Claude**, dê um nome ao token (por exemplo "Claude Code do
   notebook") e clique em **Criar token**.
2. Copie o token na hora: ele **aparece uma vez**. O banco guarda só o sha256.
3. Configure o app. A tela já mostra os textos prontos, com o token e o endereço preenchidos:

**Claude Code** (testado em 28/10/2026, versão 2.1.312):

```bash
claude mcp add --transport http casa-lorenzi https://<api>/api/conector-mcp --header "Authorization: Bearer clmcp_..."
```

**Claude Desktop** (`claude_desktop_config.json`, com o Node.js instalado; usa a ponte `mcp-remote`):

```json
{
  "mcpServers": {
    "casa-lorenzi": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://<api>/api/conector-mcp", "--header", "Authorization:${AUTH}"],
      "env": { "AUTH": "Bearer clmcp_..." }
    }
  }
}
```

**n8n**: no agente, o nó **MCP Client Tool** com o endereço acima, transporte **HTTP Streamable** e
autenticação **Bearer** com o token.

Depois, é só perguntar: "quanto faturamos em setembro na Oscar Freire?", "monte um e-mail para cada gerente com o
estoque parado da loja dele".

## Tokens

- Valem **90 dias** (`MCP_TOKEN_VALIDADE_DIAS`). Cada pessoa tem no máximo **5 ativos** (`MCP_TOKENS_POR_USUARIO`).
- **Revogar** na mesma tela corta o acesso na hora: a próxima chamada recebe 401.
- Quem é desativado perde o MCP na hora, sem precisar revogar. Quem muda de papel ou de marca passa a ver o do novo
  papel na próxima consulta.
- A tela mostra o último uso e quantas consultas cada token fez.
- Quem tiver o token consulta o que o dono consulta. Não mande por e-mail nem cole em lugar público.

## Segurança e auditoria

| Risco | Como está tratado |
| --- | --- |
| Token vazado | Só o sha256 no banco; começo fixo `clmcp_` para reconhecer; validade de 90 dias; revogação na hora |
| Ver o que o perfil não vê | `tools/list` só lista o que o papel pode usar; a execução confere de novo a cada chamada (`motivo_da_recusa`) |
| Outra marca | A marca vem do dono do token. Pedir a outra marca responde `SEM_PERMISSAO` |
| Parâmetro a mais (ex.: `cliente_id`) | Recusado pelo contrato (`extra="forbid"`), como no copiloto |
| Abuso | 60 consultas a cada 10 minutos por token; corpo de até 64 KB |
| Site malicioso no navegador (DNS rebinding) | Requisição com `Origin` de outro site recebe 403 |
| Corpo fora do padrão | `NaN`, `Infinity`, JSON aninhado sem fim ou lote de mensagens: 400 antes de chegar ao banco. Falha não prevista (banco fora do ar): erro JSON-RPC `-32603`, sem detalhe interno |
| Dois pedidos de token ao mesmo tempo | A criação trava a linha da pessoa: o limite de 5 ativos vale mesmo assim |
| Rastreabilidade | Cada chamada em `chamadas_mcp`: token, pessoa, ferramenta, parâmetros, sucesso, erro, duração e o app que chamou |

**O que muda em relação ao painel:** fora do painel, quem escreve a resposta é o modelo do app da pessoa, e não o
nosso. O verificador de números (decisão 101) não roda ali. O que segura a qualidade é o resultado das
ferramentas, que já vem formatado e com o período e a definição, e as instruções do servidor ("copie os valores
como vieram, sem calcular"). Para número que vai para uma decisão importante, confira no copiloto do painel.

## O protocolo

`src/use_cases/assistente/servidor_mcp.py` implementa o MCP sobre **Streamable HTTP**, com respostas em JSON e
sem sessão, nas duas gerações em uso:

- **2026-07-28**: sem `initialize`. Cada requisição traz a versão e as capacidades em `params._meta`, e os
  cabeçalhos `MCP-Protocol-Version`, `Mcp-Method` e `Mcp-Name` repetem o corpo. Se não batem, 400
  (`-32020`). `server/discover` diz as versões, as capacidades e as instruções.
- **2025-03-26 a 2025-11-25**: o cliente abre com `initialize`, e o servidor responde a versão pedida ou a
  2025-11-25. Depois o cliente manda a versão no cabeçalho; sem cabeçalho, vale 2025-03-26.

Métodos: `initialize`, `server/discover`, `ping`, `tools/list` e `tools/call`. Notificações recebem 202. GET e
DELETE recebem 405, porque não há stream do servidor nem sessão. Erro de consulta (sem permissão, parâmetro
inválido, limite) volta como resultado com `isError`, para o modelo poder corrigir. Ferramenta inexistente volta
como erro JSON-RPC `-32602`.

O SDK oficial (`mcp`) não entrou: o módulo cobre o que o servidor usa, sem dependência nova. Os testes estão em
`tests/test_mcp.py`, com as duas gerações, as permissões, os tokens e a auditoria.

### Antivírus que inspecionam MCP

Em 28/10/2026, nesta máquina de desenvolvimento, o **Avast** interceptava o tráfego MCP e corrompia as respostas
com `Content-Length`. Ele tirava o tamanho e marcava "chunked" sem o corpo estar em pedaços, e o Claude Code
recusava a resposta com `InvalidHTTPResponse`. O filtro age em requisições com o cabeçalho
`MCP-Protocol-Version` e em endereços terminados em `/mcp` ou `/sse`, em qualquer servidor.

Por isso as respostas do servidor saem em pedaços (`Transfer-Encoding: chunked`), que passam intactas, e o
endereço é `/api/conector-mcp`. Se outro servidor MCP falhar com `InvalidHTTPResponse` numa máquina com Avast,
a causa provável é a mesma. Um exemplo é o conector do Figma, que falhava nesta mesma máquina.

## Próximos passos

- Uso do MCP no painel "Uso e custo da IA" (hoje a tela de tokens mostra o último uso e as consultas de cada um).
