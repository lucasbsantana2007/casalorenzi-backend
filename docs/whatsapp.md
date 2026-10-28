# A Lúcia no WhatsApp (decisão 108)

O n8n recebe e entrega as mensagens; quem responde é a API, com o mesmo assistente do site.

```
Cliente ──WhatsApp──► Meta (Cloud API) ──webhook──► n8n ──POST /api/canais/whatsapp/mensagens──► API (Lúcia)
Cliente ◄──WhatsApp── Meta ◄──enviar mensagem── n8n ◄──────────── { responder, texto, protocolo } ─┘
```

## O que a API faz

`POST /api/canais/whatsapp/mensagens`, com o cabeçalho `X-Canal-Segredo` igual a `CANAL_WHATSAPP_SEGREDO`.

Corpo (JSON):

| Campo | O que é |
| --- | --- |
| `telefone` | Quem escreveu, com DDI e DDD (o `from` da Meta, ex.: `5511987654321`) |
| `texto` | O texto da mensagem; vazio se for áudio, foto ou figurinha |
| `idMensagem` | O id da mensagem na Meta (`wamid...`) |
| `nome` | O nome do perfil do WhatsApp (vai para o chamado de atendimento) |

Resposta: `{ "responder": true, "texto": "...", "conversaId": "...", "protocolo": null }`. Com `responder: false`
(a Meta entregou a mesma mensagem de novo), o n8n não envia nada.

Como a conversa funciona:
- **Uma conversa por telefone**, enquanto estiver ativa. Depois de 24 h sem mensagem, começa outra, como no site.
- **O número não fica salvo na conversa.** Ela é achada pelo HMAC do telefone, calculado com o segredo do canal.
- **O assistente é o mesmo do site**: as mesmas ferramentas, o verificador de números e a regra de duas falhas →
  pessoa. O modelo sabe que está no WhatsApp: responde só em texto, sem botões, com no máximo 5 peças.
- **Os cards viram texto.** Peças saem com preço e link do site; disponibilidade sai por loja; lojas saem com
  endereço, horário de hoje e telefone. Quando a peça está escolhida, sai o link para comprar.
- **Sem login.** O WhatsApp não identifica a conta do site, então pedidos, pontos e dados da conta ficam no site
  (`/login`).
- **Pedido de pessoa**, cliente irritado ou duas falhas seguidas **abrem o chamado na hora**: canal WHATSAPP, com o
  resumo da conversa, o telefone e o nome do perfil. A resposta traz o protocolo. Uma conversa abre no máximo um
  chamado; se o cliente pedir de novo, a Lúcia lembra o protocolo.
- **Mensagens em sequência** ("oi" / "tudo bem?" / "tem camisa azul?"): cada uma espera a anterior ser respondida.
- **Limites:** 30 mensagens a cada 10 minutos por telefone e 800 caracteres por mensagem, os mesmos do site.

## Configuração

1. **Render** (Environment): `CANAL_WHATSAPP_SEGREDO` com um valor longo e aleatório (por exemplo, a saída de
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Opcional: `CANAL_WHATSAPP_MARCA`
   (`LORENZI`, o padrão, ou `VULTO`): a vitrine do número. Nunca no git.
2. **Meta for Developers:** app do tipo Business com o produto WhatsApp. Anote o *Phone number ID* do número de
   teste e cadastre os telefones que vão testar (até 5). Para a banca, use um token permanente de usuário do sistema
   (o temporário vence em 24 h).
3. **n8n:** um fluxo com cinco nós:

| # | Nó | Configuração |
| --- | --- | --- |
| 1 | **WhatsApp Trigger** | Credencial do app da Meta; evento *messages* |
| 2 | **IF** | Só segue se `{{ $json.messages }}` existir (a Meta também manda avisos de entrega e leitura, que não são mensagens) |
| 3 | **HTTP Request** | `POST https://casalorenzi-api.onrender.com/api/canais/whatsapp/mensagens`; cabeçalho `X-Canal-Segredo`; corpo JSON abaixo; tempo máximo de 60 s |
| 4 | **IF** | Só segue se `{{ $json.responder }}` for verdadeiro |
| 5 | **WhatsApp** (*Send message*) | *Phone number ID* do número; destinatário `{{ $('WhatsApp Trigger').item.json.messages[0].from }}`; texto `{{ $json.texto }}` |

Corpo do nó 3:

```json
{
  "telefone": "{{ $json.messages[0].from }}",
  "texto": "{{ $json.messages[0].text ? $json.messages[0].text.body : '' }}",
  "idMensagem": "{{ $json.messages[0].id }}",
  "nome": "{{ $json.contacts[0].profile.name }}"
}
```

Confira no primeiro teste o caminho dos campos na saída do WhatsApp Trigger: a Meta manda `messages` e
`contacts` dentro de `value`, e o nó pode entregar o objeto inteiro ou só o `value`.

## Limitações

- **A equipe responde por fora.** O chamado aparece no painel de Atendimento com o telefone do cliente. A resposta da
  equipe ainda não volta pelo n8n: a equipe fala com o cliente pelo WhatsApp do atendimento.
- **Mensagens iniciadas pela empresa** (avisos de pontos, sacola) precisam de modelo aprovado pela Meta; fora da
  janela de 24 h, só elas são permitidas.
- **No modo regras** (sem chave da API ou com o modelo fora do ar), alguns textos prontos ainda são do site. A API
  tira as frases que mandam tocar em botão.
