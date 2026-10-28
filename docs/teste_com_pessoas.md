# Teste da Lúcia com pessoas de fora

A bateria (`tests/bateria_lucia.py`) mede as perguntas que o time achou difíceis. Quem não participou do projeto
escreve diferente: abrevia, erra a digitação, pergunta o que ninguém pensou. Este teste mostra onde a Lúcia ainda
falha, com números, antes da banca.

## Quando e com quem

- **Até 29/10, antes da recarga do banco de produção** (decisão 84). A recarga apaga as conversas: gere o
  relatório antes dela.
- **5 a 8 pessoas** que não trabalharam no projeto. Vale misturar: quem compra roupa pela internet, alguém mais
  velho, alguém que escreve abreviado ("vcs tem", "qnt custa") e alguém que tente fazer a Lúcia errar.
- No **site publicado** (https://casalorenzi-frontend.vercel.app), no celular ou no computador. Na rede do Insper,
  se o site não abrir, use o 4G.

## Contas

- Perguntas de peça, loja, frete e política: **sem login**.
- Pedido, pontos e conta: a conta de demonstração **mariana.costa@gmail.com** (senha `lorenzi2026`), entrando pelo
  formulário que aparece no próprio chat.
- A conta é a mesma para todos. Por isso, **ninguém confirma** troca de e-mail, cancelamento nem devolução no cartão:
  pode pedir e ver o cartão aparecer, mas não confirmar.

## Missões

Cada pessoa faz as missões **com as próprias palavras** (não leia o texto para ela) e toca em 👍 ou 👎 em toda
resposta; no 👎, escreve o que faltou.

1. Ache um presente de até R$ 300 para alguém da sua família.
2. Escolha uma peça e descubra se tem no seu tamanho numa loja da sua cidade.
3. Coloque uma peça na sacola pelo chat (e desfaça, se quiser).
4. Entre na conta pelo chat e pergunte onde está o último pedido.
5. Descubra quantos pontos Lupe+ a conta tem e quando eles vencem.
6. Pergunte quanto fica o frete para o seu CEP.
7. Peça para cancelar um pedido (sem confirmar no cartão).
8. Faça uma pergunta que você acha que a Lúcia não sabe responder.
9. Peça para falar com uma pessoa.
10. Cinco minutos livres: pergunte o que perguntaria a uma loja.

## Para quem conduz

- Anote o horário de início e de fim da sessão (o relatório usa os dois).
- Não ajude a reformular a pergunta: o "não entendi" é exatamente o que queremos medir.
- No fim, três perguntas a cada pessoa: de 0 a 10, a Lúcia resolveu o que você queria? O que mais incomodou? Usaria
  de novo numa loja de verdade?
- Ninguém escreve dado pessoal de verdade (CPF, telefone, endereço) no chat.

## Depois: o relatório

```bash
# DATABASE_URL = URL externa do banco de produção (painel do Render, com o Lucas)
python scripts/relatorio_lucia.py --desde "2026-10-28 14:00" --ate "2026-10-28 16:00"
```

O relatório vai para `relatorios/`, **fora do git**: ele traz o que os testadores escreveram, e o repositório é
público. Para a apresentação, `--sem-textos` gera só os números.

| No relatório | O que fazer |
| --- | --- |
| Resolvidas sem uma pessoa | O número para a banca: quantas conversas terminaram sem precisar da equipe. |
| Falhas (pergunta e resposta) | Cada uma vira um caso novo em `tests/bateria_lucia.py`, com o que a resposta deveria ter. |
| Números que o verificador barrou | O que o modelo tentou dizer sem fonte e o que saiu no lugar (decisão 101). |
| "Não ajudou" com comentário | A lista de melhorias, nas palavras de quem usou. |
| Consultas que deram erro | Defeito nosso: corrigir antes da banca. |
| Custo e tempo | Confere a estimativa de `docs/custos_ia.md` com o uso real. |

Depois de corrigir: `pytest tests/test_bateria_lucia.py` (sem o Claude) e `python scripts/avaliar_lucia.py` (com o
Claude, poucos centavos). O placar não pode cair.
