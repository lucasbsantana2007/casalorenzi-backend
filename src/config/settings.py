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
