# Copiloto no Claude: o servidor MCP (decisões 106 e 109)

O copiloto gerencial também atende fora do painel, como a **cúpula de informação da liderança**: no **Claude
Code**, no **Claude Desktop** ou num agente do **n8n**, pelo protocolo MCP (Model Context Protocol). Só o papel
**Administrador** usa (decisão 109); Lojista e Operador usam o copiloto no painel. Quem pergunta usa as mesmas consultas, as mesmas regras e as
mesmas permissões do painel. Muda só o lugar da conversa.

| O quê | Como |
| --- | --- |
| Endereço | `https://<api>/api/conector-mcp` (local: `http://127.0.0.1:8000/api/conector-mcp`) |
| Login | Token pessoal (`Authorization: Bearer clmcp_...`), criado em **Inteligência > Conectar ao Claude** |
| O que dá para consultar | As 11 ferramentas do copiloto e `ver_contexto` (data de hoje, até quando há vendas, lojas com os ids, categorias, permissões e definições das métricas) |
| O que não sai | Nada do cliente: pedidos, pontos, devoluções e conta ficam só na Lúcia, no site |
| Permissão | Só Administrador. A do dono do token **no momento da chamada**: papel, marca (quem é da Vulto vê só a Vulto) e conta ativa |
| Escrita | Nenhuma. As consultas rodam em transação READ ONLY, como no copiloto |

## Como conectar

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
- Quem é desativado ou deixa de ser Administrador perde o MCP na hora, sem precisar revogar.
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

- Conector no claude.ai (Configurações > Conectores) exige OAuth: fica para depois da banca.
- Uso do MCP no painel "Uso e custo da IA" (hoje a tela de tokens mostra o último uso e as consultas de cada um).
