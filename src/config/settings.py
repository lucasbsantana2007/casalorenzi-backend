"""Configurações lidas do ambiente (arquivo .env na raiz do backend).

Tudo que muda entre o computador de cada um, os testes e a produção fica aqui.
"""

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _lista(valor: str) -> list[str]:
    return [item.strip() for item in valor.split(",") if item.strip()]


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/casalorenzi")

# Chave usada para assinar os tokens JWT. Troque em produção.
JWT_SECRET = os.getenv("JWT_SECRET", "dev-somente-local-troque-esta-chave-em-producao")
JWT_EXPIRA_HORAS = int(os.getenv("JWT_EXPIRA_HORAS", "12"))

CORS_ORIGINS = _lista(os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"))

# Fuso usado para interpretar filtros de data (yyyy-mm-dd) e agrupar o financeiro por dia/mês.
FUSO = ZoneInfo(os.getenv("FUSO_HORARIO", "America/Sao_Paulo"))

# Nível dos logs: DEBUG, INFO, WARNING ou ERROR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Endereço público da API, usado nos links das fotos de produto (imagemUrl). Vazio: usa o endereço
# pelo qual a requisição chegou (bom no ambiente local; atrás de um proxy, defina o https público).
URL_PUBLICA_API = os.getenv("URL_PUBLICA_API", "").rstrip("/")

# E-mails (esqueci a senha, convite de funcionário, pedido confirmado) pelo Resend.
# Sem RESEND_API_KEY, os e-mails não saem: o conteúdo vai para o log da API.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
# Remetente: precisa ser de um domínio verificado no Resend. onboarding@resend.dev só entrega para o
# e-mail dono da conta do Resend (bom para testar).
EMAIL_REMETENTE = os.getenv("EMAIL_REMETENTE", "Casa Lorenzi <onboarding@resend.dev>")
# Endereço do site, usado nos links dos e-mails (ex.: https://casalorenzi.vercel.app)
URL_FRONTEND = os.getenv("URL_FRONTEND", "http://localhost:5173").rstrip("/")

# "Esqueci a senha" e convite de funcionário: true devolve o link também na resposta da API, para
# testar o fluxo na demonstração. Nunca true em produção.
LINK_SENHA_NA_RESPOSTA = os.getenv("LINK_SENHA_NA_RESPOSTA", "false").lower() == "true"
