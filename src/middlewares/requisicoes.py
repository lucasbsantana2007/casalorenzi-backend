"""Registro das requisições e tratamento central de erros.

O cliente recebe só o que precisa saber ({ "detail": "..." }); o time recebe o contexto no log:
quando, onde, qual operação e o request-id, que também volta no cabeçalho X-Request-ID.
"""

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.utils.erros import ErroDeNegocio
from src.utils.urls import definir_base

logger = logging.getLogger("casalorenzi")


def registrar(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        definir_base(str(request.base_url))
        inicio = time.perf_counter()
        resposta = await call_next(request)
        duracao = (time.perf_counter() - inicio) * 1000
        resposta.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "%s %s -> %s (%.0f ms) request_id=%s",
            request.method,
            request.url.path,
            resposta.status_code,
            duracao,
            request.state.request_id,
        )
        return resposta

    @app.exception_handler(ErroDeNegocio)
    async def erro_esperado(request: Request, erro: ErroDeNegocio):
        """Erro previsto pelas regras: vira a resposta definida, sem stack trace."""
        if erro.status_code in (401, 403, 429):
            logger.warning(
                "%s %s -> %s %s request_id=%s",
                request.method,
                request.url.path,
                erro.status_code,
                erro.mensagem,
                getattr(request.state, "request_id", "-"),
            )
        headers = {"WWW-Authenticate": "Bearer"} if erro.status_code == 401 else None
        return JSONResponse({"detail": erro.mensagem}, status_code=erro.status_code, headers=headers)

    @app.exception_handler(Exception)
    async def erro_inesperado(request: Request, erro: Exception):
        """Falha não prevista (banco fora do ar, bug): registra tudo para o time e responde 500 genérico."""
        request_id = getattr(request.state, "request_id", "-")
        logger.exception("Falha em %s %s request_id=%s", request.method, request.url.path, request_id)
        return JSONResponse(
            {"detail": f"Erro interno. Se persistir, informe o código {request_id} à equipe."},
            status_code=500,
            headers={"X-Request-ID": request_id},
        )
