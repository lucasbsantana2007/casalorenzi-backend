"""Dados de demonstração (mesmos do frontend)."""

from src.database.seed.carga import apagar_tudo, popular
from src.database.seed.dados import PIN_DEMO, SENHA_DEMO

__all__ = ["PIN_DEMO", "SENHA_DEMO", "apagar_tudo", "popular"]
