from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.routers import (
    atendimentos,
    auth,
    cadastros,
    clientes,
    dashboard,
    estoque,
    financeiro,
    produtos,
    transferencias,
)

app = FastAPI(
    title="Casa Lorenzi API",
    description="API da plataforma integrada Casa Lorenzi. Todas as rotas ficam sob o prefixo /api.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root():
    return {"message": "Casa Lorenzi API funcionando", "docs": "/docs"}


api = APIRouter(prefix="/api")


@api.get("/health", tags=["Status"])
def health():
    return {"status": "ok"}


for modulo in (auth, cadastros, produtos, estoque, transferencias, atendimentos, clientes, dashboard, financeiro):
    api.include_router(modulo.router)

app.include_router(api)

# Mantido por compatibilidade com quem já usava /health
app.add_api_route("/health", health, include_in_schema=False)
