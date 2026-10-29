"""Copiloto gerencial (Inteligência de Negócios — Assistente IA): só a equipe. A tela abre para todos os
papéis, mas cada consulta confere o módulo do assunto e a marca do token (src/use_cases/assistente)."""

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.orm import Session

from src import models as m
from src.config import settings
from src.database.connection import get_db
from src.entities import assistente as regra
from src.entities.papeis import pode_acessar
from src.middlewares import limite
from src.middlewares.autenticacao import escopo_marca, exigir_modulo
from src.schemas.comum import Entrada
from src.use_cases.assistente import conversas, regras_gerenciais
from src.use_cases.assistente.ferramentas_gerenciais import FERRAMENTAS

router = APIRouter(prefix="/copiloto", tags=["Copiloto gerencial"])
acesso = exigir_modulo("inteligencia")


class MensagemEntrada(Entrada):
    texto: str = Field(max_length=4000)
    id_cliente: str | None = Field(None, max_length=64)


@router.get("/sugestoes")
def sugestoes(usuario: m.Usuario = Depends(acesso)):
    """Perguntas de exemplo que este perfil pode fazer e o que ele pode consultar."""
    ferramentas = [{"nome": f.nome, "liberada": pode_acessar(usuario.papel, f.modulo) if f.modulo else True} for f in FERRAMENTAS]
    return {
        "sugestoes": regras_gerenciais.sugestoes_para(usuario.papel, usuario.marca == "GRUPO"),
        "permissoes": {
            "vendas": pode_acessar(usuario.papel, "financeiro"),
            "fidelidade": pode_acessar(usuario.papel, "fidelidade"),
            "pedidos": pode_acessar(usuario.papel, "pedidos"),
            "atendimento": pode_acessar(usuario.papel, "atendimento"),
            "estoque": pode_acessar(usuario.papel, "estoque"),
            "transferencias": pode_acessar(usuario.papel, "transferencias"),
            "usoDaIA": pode_acessar(usuario.papel, "administracao"),
        },
        "ferramentas": ferramentas,
        "modoIA": "LLM" if settings.ANTHROPIC_API_KEY else "REGRAS",
        "modelo": settings.IA_MODELO if settings.ANTHROPIC_API_KEY else None,
    }


@router.get("/conversas")
def listar(db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    """Conversas anteriores do usuário (as que têm pelo menos uma pergunta)."""
    return conversas.conversas_do_usuario(db, usuario)


@router.post("/conversas", status_code=201)
def abrir(db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    return conversas.conversa_saida(db, conversas.abrir_gerencial(db, usuario))


@router.get("/conversas/{conversa_id}")
def obter(conversa_id: str, db: Session = Depends(get_db), usuario: m.Usuario = Depends(acesso)):
    """De outro usuário: 404."""
    return conversas.conversa_saida(db, conversas.conversa_do_usuario(db, conversa_id, usuario))


@router.post("/conversas/{conversa_id}/mensagens")
def enviar(
    conversa_id: str,
    dados: MensagemEntrada,
    request: Request,
    db: Session = Depends(get_db),
    usuario: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """Responde com texto e blocos (indicadores, tabelas, gráficos e a fonte de cada número)."""
    conversa = conversas.conversa_do_usuario(db, conversa_id, usuario)
    maximo, janela = regra.LIMITE_POR_CONVERSA[regra.GERENCIAL]
    limite.conferir(f"copiloto:usuario:{usuario.id}", maximo=maximo, janela_segundos=janela)
    pergunta, resposta = conversas.enviar(
        db,
        conversa,
        dados.texto,
        id_cliente=dados.id_cliente,
        usuario=usuario,
        marca_escopo=marca,
        request_id=getattr(request.state, "request_id", None),
    )
    return {
        "pergunta": conversas.mensagem_saida(pergunta),
        "resposta": conversas.mensagem_saida(resposta),
        "status": conversa.status,
    }


@router.get("/uso")
def uso(dias: int = 30, db: Session = Depends(get_db), _: m.Usuario = Depends(exigir_modulo("administracao"))):
    """Só Administrador: conversas, respostas por modo, chamadas ao modelo, tokens, custo estimado e consultas."""
    return conversas.metricas(db, max(1, min(dias, 365)))
