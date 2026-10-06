"""Porta de entrada: cria o app, liga CORS, logs e tratamento de erros e registra as rotas em /api.

Rodar:  uvicorn src.app:app --reload --port 8000
Docs:   http://localhost:8000/docs
"""

import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config.settings import CORS_ORIGINS, LOG_LEVEL
from src.middlewares import requisicoes
from src.routers import (
    atendimentos,
    autenticacao,
    cadastros,
    clientes,
    dashboard,
    devolucoes,
    estoque,
    financeiro,
    loja,
    pagamentos,
    pedidos,
    produtos,
    transferencias,
)

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="Casa Lorenzi API",
    description="API da plataforma integrada Casa Lorenzi. Todas as rotas ficam sob o prefixo /api.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
requisicoes.registrar(app)


@app.get("/", include_in_schema=False)
def raiz():
    return {"message": "Casa Lorenzi API funcionando", "docs": "/docs"}


api = APIRouter(prefix="/api")


@api.get("/health", tags=["Status"])
def health():
    return {"status": "ok"}


for modulo in (
    autenticacao,
    cadastros,
    produtos,
    estoque,
    transferencias,
    loja,
    pedidos,
    pagamentos,
    devolucoes,
    atendimentos,
    clientes,
    dashboard,
    financeiro,
):
    api.include_router(modulo.router)

app.include_router(api)

# Mantido por compatibilidade com quem já usava /health
app.add_api_route("/health", health, include_in_schema=False)
