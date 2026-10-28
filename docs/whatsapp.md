# A Lúcia no WhatsApp (decisões 108, 114 e 115)

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

| `botao` | O id do botão tocado (`interactive.button_reply.id` da Meta): `LUCIA`, `EQUIPE` ou `MENU` |

Resposta: `{ "responder": true, "texto": "...", "mensagem": {...}, "conversaId": "...", "protocolo": null }`.
`mensagem` é o corpo pronto para `POST /{phone-number-id}/messages` da Graph API: texto ou botões, já com o
destinatário. Com `responder: false` (a Meta entregou a mesma mensagem de novo), o n8n não envia nada.

### O menu (decisão 114)

1. **Primeira mensagem:** cumprimento pelo horário com o primeiro nome do perfil ("Boa tarde, Ana! Aqui é a
   Lúcia...") e dois botões: **Respostas rápidas** e **Falar com a equipe**. Responder 1 ou 2 também vale. Se a
   primeira mensagem era uma pergunta, ela fica guardada e é respondida quando o cliente escolher a Lúcia.
2. **Respostas rápidas:** a Lúcia responde como no site, e toda resposta traz o botão **Falar com a equipe**
   (ou, se o texto passar de 1.024 caracteres, a dica "responda 2").
3. **Equipe:** o chamado abre na hora, com o resumo e o telefone. As mensagens seguintes entram no mesmo
   chamado, e o cliente recebe a confirmação com o protocolo e o botão **Respostas rápidas** para voltar.
4. **"menu"** mostra as opções de novo. Chamado encerrado: a próxima mensagem recomeça pelo menu.

### Um lugar só para o atendimento humano (decisão 115)

- **Um número:** `WHATSAPP_ATENDIMENTO` no Render é o mesmo número da Meta. O botão "Continuar no WhatsApp" do
  site abre esse número com o protocolo escrito; a mensagem chega com o protocolo e entra no chamado que já
  existe ("Recebi o seu protocolo..."), sem abrir outro.
- **Uma caixa:** a equipe responde no painel, em Atendimento. Em chamado do WhatsApp, a resposta vai para o
  cliente pelo n8n, assinada "Equipe Casa Lorenzi e Vulto · protocolo ...", com o botão Respostas rápidas.
  Passadas 24 h da última mensagem do cliente, a Meta não aceita mensagem livre: a resposta não sai e o chamado
  registra o aviso.
- **Ciclo de 4 horas** (`WHATSAPP_CICLO_HORAS`): se o cliente fica 4 h sem responder depois da equipe, a
  automação `encerrar_whatsapp` encerra o chamado e avisa o cliente. Se ele voltar antes de a automação rodar,
  o chamado é encerrado na hora e a conversa recomeça pelo cumprimento e pelo menu. Se a última mensagem é do
  cliente, o ciclo não fecha: quem deve resposta é a equipe. Conversa com a Lúcia parada 4 h também recomeça.

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

1. **Render** (Environment): `WHATSAPP_ATENDIMENTO` com o número da Meta (só dígitos, com DDI), `N8N_ENVIO_URL`
   com a URL do webhook de envio do n8n e `CANAL_WHATSAPP_SEGREDO` com um valor longo e aleatório (por exemplo, a saída de
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Opcional: `CANAL_WHATSAPP_MARCA`
   (`LORENZI`, o padrão, ou `VULTO`): a vitrine do número. Nunca no git.
2. **Meta for Developers:** app do tipo Business com o produto WhatsApp. Anote o *Phone number ID* do número de
   teste e cadastre os telefones que vão testar (até 5). Para a banca, use um token permanente de usuário do sistema
   (o temporário vence em 24 h).
3. **n8n:** um fluxo com cinco nós:

| # | Nó | Configuração |
| --- | --- | --- |
| 1 | **WhatsApp Trigger** | Credencial do app da Meta; evento *messages* |
| 2 | **IF** | `{{ Array.isArray($json.messages) && $json.messages.length > 0 }}` com o operador **Boolean > is true** e **Convert types where required** ligado. A Meta também manda avisos de entrega e leitura (`statuses`), que param aqui |
| 3 | **HTTP Request** | `POST https://casalorenzi-api.onrender.com/api/canais/whatsapp/mensagens`; credencial Header Auth (`X-Canal-Segredo`); **Send Body** ligado, JSON com os campos abaixo, cada valor em modo Expression; tempo máximo de 60 s; em *Settings*, **Retry On Fail** com 5 tentativas a cada 5 s (a API do plano grátis do Render dorme e responde 503 enquanto acorda) |
| 4 | **IF** | `{{ $json.responder }}` com **Boolean > is true** |
| 5 | **HTTP Request** (envio) | `POST https://graph.facebook.com/v25.0/{phone-number-id}/messages`; credencial Header Auth com *Name* `Authorization` e *Value* `Bearer {token permanente}`; *Send Body* ligado, *Body Content Type* JSON, *Specify Body* **Using JSON**, com `{{ JSON.stringify($json.mensagem) }}` |

Corpo do nó 3:

```json
{
  "telefone": "{{ $json.messages[0].from }}",
  "texto": "{{ $json.messages[0].text ? $json.messages[0].text.body : '' }}",
  "idMensagem": "{{ $json.messages[0].id }}",
  "nome": "{{ $json.contacts[0].profile.name }}",
  "botao": "{{ $json.messages[0].interactive ? $json.messages[0].interactive.button_reply.id : '' }}"
}

O nó **WhatsApp > Send message** não manda botões; por isso o envio é o HTTP Request do passo 5, que publica a
`mensagem` que a API montou.

### Segundo fluxo: envio da equipe (decisão 115)

A API chama este fluxo quando a equipe responde no painel ou quando o ciclo fecha.

| # | Nó | Configuração |
| --- | --- | --- |
| 1 | **Webhook** | *HTTP Method* POST; *Path* `envio-whatsapp`; *Authentication* Header Auth com a mesma credencial do segredo do canal (`X-Canal-Segredo`); *Respond* Immediately |
| 2 | **HTTP Request** | Igual ao passo 5 do primeiro fluxo (Graph API, credencial `Authorization: Bearer ...`), com o JSON `{{ JSON.stringify($json.body.mensagem) }}` |

Depois de publicar, copie a **Production URL** do Webhook e ponha no Render em `N8N_ENVIO_URL`.
```

Conferido em 28/10/2026: o WhatsApp Trigger entrega `messages` e `contacts` no primeiro nível do item (os caminhos
acima funcionam). Depois de qualquer mudança no fluxo, clique em **Publish**: enquanto houver a bolinha amarela, as
mensagens rodam a versão anterior.

## Problemas encontrados na montagem

| Sintoma | Causa | O que fazer |
| --- | --- | --- |
| IF com "Wrong type: '[object Object]' is a string but was expecting an array" | Comparar a lista direto no IF | Usar a expressão booleana acima, operador Boolean e Convert types ligado |
| HTTP Request com "Service unavailable" | A API estava dormindo (Render grátis) | Retry On Fail no nó; para a banca, plano Starter do Render |
| HTTP Request com "Field required" | Send Body desligado | Ligar Send Body com os 4 campos |
| Execução verde, mas a resposta não chega | A Meta recusa a entrega; o motivo vem no aviso seguinte (`statuses[0].errors`) | Abrir a execução do aviso e ler o código do erro |
| Erro 131031 "Business Account locked" | A Meta bloqueou a conta do WhatsApp Business (conta do Facebook recém-criada) | Pedir revisão em Business Support Home ou criar o app com uma conta do Facebook antiga |
| Resposta não chega no número com o 9 | O WhatsApp identifica muitos números antigos de MG sem o nono dígito (`from` = 553184139032) | Cadastrar em **To**, na Meta, as duas versões do número |

## Limitações

- **Mensagens iniciadas pela empresa** (avisos de pontos, sacola) precisam de modelo aprovado pela Meta; fora da
  janela de 24 h, só elas são permitidas.
- **No modo regras** (sem chave da API ou com o modelo fora do ar), alguns textos prontos ainda são do site. A API
  tira as frases que mandam tocar em botão.
