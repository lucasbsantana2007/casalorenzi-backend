"""Configurações lidas do ambiente (arquivo .env na raiz do backend).

Tudo que muda entre o computador de cada um, os testes e a produção fica aqui.
"""

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _lista(valor: str) -> list[str]:
    return [item.strip() for item in valor.split(",") if item.strip()]


def _origens(valor: str) -> list[str]:
    """Endereços do frontend para o CORS. O navegador manda a origem sem a barra final, então
    "https://site.vercel.app/" (colado com a barra) também precisa valer."""
    return [item.rstrip("/") for item in _lista(valor)]


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/casalorenzi")

# Chave usada para assinar os tokens JWT. Troque em produção.
JWT_SECRET = os.getenv("JWT_SECRET", "dev-somente-local-troque-esta-chave-em-producao")
JWT_EXPIRA_HORAS = int(os.getenv("JWT_EXPIRA_HORAS", "2"))

CORS_ORIGINS = _origens(os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"))

# Fuso usado para interpretar filtros de data (yyyy-mm-dd) e agrupar o financeiro por dia/mês.
FUSO = ZoneInfo(os.getenv("FUSO_HORARIO", "America/Sao_Paulo"))

# Nível dos logs: DEBUG, INFO, WARNING ou ERROR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Endereço público da API, usado nos links das fotos de produto (imagemUrl). No Render, vem sozinho
# de RENDER_EXTERNAL_URL (o https do serviço). Vazio: usa o endereço pelo qual a requisição chegou
# (bom no ambiente local).
URL_PUBLICA_API = (os.getenv("URL_PUBLICA_API") or os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")

# E-mails (esqueci a senha, convite de funcionário, pedido confirmado) pelo Resend.
# Sem RESEND_API_KEY, os e-mails não saem: o conteúdo vai para o log da API.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
# Remetente: precisa ser de um domínio verificado no Resend. onboarding@resend.dev só entrega para o
# e-mail dono da conta do Resend (bom para testar).
# Nome que aparece como remetente: o das duas marcas (no Render, o domínio verificado no Resend)
EMAIL_REMETENTE = os.getenv("EMAIL_REMETENTE", "Casa Lorenzi e Vulto <onboarding@resend.dev>")
# Endereço do site, usado nos links dos e-mails (ex.: https://casalorenzi.vercel.app)
URL_FRONTEND = os.getenv("URL_FRONTEND", "http://localhost:5173").rstrip("/")

# "Esqueci a senha" e convite de funcionário: true devolve o link também na resposta da API, para
# testar o fluxo na demonstração. Nunca true em produção.
LINK_SENHA_NA_RESPOSTA = os.getenv("LINK_SENHA_NA_RESPOSTA", "false").lower() == "true"

# ---------- Assistentes de IA (docs/assistente_ia.md) ----------
# Chave da API da Anthropic (Claude). Sem ela, os assistentes respondem só pelas regras
# determinísticas (sem LLM). Nunca vai para o frontend nem para o git.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Modelo do Claude. Padrão econômico: Haiku 5.5. Trocar o modelo não exige mudar o código.
IA_MODELO = os.getenv("IA_MODELO", "claude-haiku-5-5")
# Quanto o modelo pensa antes de responder: low (chat, mais barato), medium ou high
IA_ESFORCO = os.getenv("IA_ESFORCO", "low")
# Teto de tokens de saída por chamada (inclui o raciocínio do modelo)
IA_MAX_TOKENS = int(os.getenv("IA_MAX_TOKENS", "2048"))
# Tempo máximo de cada chamada ao modelo e quantas vezes o SDK tenta de novo (429, 5xx, rede)
IA_TIMEOUT_SEGUNDOS = float(os.getenv("IA_TIMEOUT_SEGUNDOS", "25"))
IA_MAX_TENTATIVAS = int(os.getenv("IA_MAX_TENTATIVAS", "1"))
# Mensagens anteriores enviadas ao modelo (o resto da conversa fica no banco, fora do contexto)
IA_HISTORICO_MENSAGENS = int(os.getenv("IA_HISTORICO_MENSAGENS", "12"))
# Por mensagem do usuário: idas e voltas com o modelo e consultas (ferramentas) no máximo
IA_MAX_RODADAS = int(os.getenv("IA_MAX_RODADAS", "4"))
IA_MAX_FERRAMENTAS = int(os.getenv("IA_MAX_FERRAMENTAS", "6"))
# Conversa parada há mais que isso recomeça do zero (a memória da conversa expira)
IA_CONVERSA_EXPIRA_HORAS = int(os.getenv("IA_CONVERSA_EXPIRA_HORAS", "24"))
# Retenção: conversas sem atividade há mais que isso são apagadas pela automação de limpeza
IA_RETENCAO_DIAS = int(os.getenv("IA_RETENCAO_DIAS", "90"))
# Respostas prontas (sem LLM) para mensagens simples: saudação, agradecimento, pedido de atendente
IA_RESPOSTAS_DIRETAS = os.getenv("IA_RESPOSTAS_DIRETAS", "true").lower() == "true"

# WhatsApp do atendimento, só números com DDI e DDD (5511999999999). Com ele, o assistente do site oferece
# "Continuar no WhatsApp": abre o chamado com o resumo da conversa e um link wa.me com o protocolo.
# Vazio: só o chamado pelo site (decisão 81).
WHATSAPP_ATENDIMENTO = "".join(c for c in os.getenv("WHATSAPP_ATENDIMENTO", "") if c.isdigit())

# Banco só de leitura para o copiloto e as automações (opcional): um usuário do Postgres só com SELECT.
# Vazio: usa DATABASE_URL, e cada consulta roda numa transação READ ONLY com tempo máximo.
DATABASE_URL_LEITURA = os.getenv("DATABASE_URL_LEITURA", "") or DATABASE_URL
CONSULTA_TIMEOUT_MS = int(os.getenv("CONSULTA_TIMEOUT_MS", "8000"))

# Automações (python -m src.automacoes): limites dos alertas operacionais
# Estoque baixo só vira alerta se a peça vendeu no local nos últimos N dias (evita milhares de alertas)
ALERTA_ESTOQUE_BAIXO_JANELA_DIAS = int(os.getenv("ALERTA_ESTOQUE_BAIXO_JANELA_DIAS", "60"))
# Estoque parado: peça com saldo e sem venda no local há N dias ou mais
ALERTA_ESTOQUE_PARADO_DIAS = int(os.getenv("ALERTA_ESTOQUE_PARADO_DIAS", "90"))
# Pontos Helo que vencem nos próximos N dias
ALERTA_PONTOS_DIAS = int(os.getenv("ALERTA_PONTOS_DIAS", "30"))

# Aviso por e-mail de pontos a vencer (decisão 82, automação aviso_pontos). Desligado por padrão: com a chave
# do Resend, o e-mail sai de verdade, e a base migrada tem e-mails que podem ser de pessoas reais.
AVISO_PONTOS_ENVIAR = os.getenv("AVISO_PONTOS_ENVIAR", "false").lower() == "true"
# Modo teste: todos os avisos vão para este e-mail do time (no máximo 5 por dia), com o destinatário no assunto
AVISO_PONTOS_TESTE_PARA = os.getenv("AVISO_PONTOS_TESTE_PARA", "").strip()
# Teto por dia: o plano grátis do Resend manda 100 e-mails por dia, e os outros e-mails da plataforma usam a mesma cota
AVISO_PONTOS_LIMITE_DIA = int(os.getenv("AVISO_PONTOS_LIMITE_DIA", "80"))
