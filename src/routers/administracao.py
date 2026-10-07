"""Central administrativa (só Administrador; 403 para os demais cargos): funcionários, lojas e
log de ações. Cada alteração grava no log quem fez, a partir do token. Regras em
src/use_cases/administracao.py."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.schemas.administracao import (
    FuncionarioEntrada,
    LojaEntrada,
    StatusFuncionarioEntrada,
    funcionario_saida,
    log_saida,
    loja_admin_saida,
)
from src.use_cases import administracao, log_acoes

router = APIRouter(prefix="/admin", tags=["Administração"])
acesso = exigir_modulo("administracao")


# ---------- Funcionários ----------


@router.get("/funcionarios")
def listar_funcionarios(
    busca: str | None = None,
    papel: Literal["ADMINISTRADOR", "LOJISTA", "OPERADOR"] | None = None,
    lojaId: int | None = None,
    status: Literal["ATIVO", "INATIVO"] | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
):
    lista = administracao.listar_funcionarios(db, busca=busca, papel=papel, loja_id=lojaId, status=status)
    return [funcionario_saida(u) for u in lista]


@router.post("/funcionarios", status_code=201)
def criar_funcionario(dados: FuncionarioEntrada, db: Session = Depends(get_db), autor: m.Usuario = Depends(acesso)):
    """Cria o funcionário sem senha e envia o convite (link de uso único, 7 dias) para ele criá-la.
    → { funcionario, linkDemo }; linkDemo só vem com LINK_SENHA_NA_RESPOSTA=true."""
    usuario, link = administracao.criar_funcionario(db, autor, dados)
    return {"funcionario": funcionario_saida(usuario), "linkDemo": link}


@router.put("/funcionarios/{usuario_id}")
def atualizar_funcionario(
    usuario_id: int, dados: FuncionarioEntrada, db: Session = Depends(get_db), autor: m.Usuario = Depends(acesso)
):
    return funcionario_saida(administracao.atualizar_funcionario(db, autor, usuario_id, dados))


@router.patch("/funcionarios/{usuario_id}/status")
def alterar_status_funcionario(
    usuario_id: int, dados: StatusFuncionarioEntrada, db: Session = Depends(get_db), autor: m.Usuario = Depends(acesso)
):
    """{ ativo }. 422 ao desativar a si mesmo ou o último Administrador ativo."""
    return funcionario_saida(administracao.alterar_status_funcionario(db, autor, usuario_id, dados.ativo))


@router.post("/funcionarios/{usuario_id}/convite")
def reenviar_convite(usuario_id: int, db: Session = Depends(get_db), autor: m.Usuario = Depends(acesso)):
    """Novo convite para quem ainda não criou a senha → { linkDemo }."""
    return {"linkDemo": administracao.reenviar_convite(db, autor, usuario_id)}


# ---------- Lojas ----------


@router.get("/lojas")
def listar_lojas(db: Session = Depends(get_db), _: m.Usuario = Depends(acesso)):
    """Todas as lojas (ativas primeiro), com funcionários ativos e peças em estoque."""
    lojas, funcionarios, pecas = administracao.listar_lojas(db)
    return [loja_admin_saida(loja, funcionarios, pecas) for loja in lojas]


def _loja(db: Session, loja: m.Loja) -> dict:
    _, funcionarios, pecas = administracao.listar_lojas(db)
    return loja_admin_saida(loja, funcionarios, pecas)


@router.post("/lojas", status_code=201)
def criar_loja(dados: LojaEntrada, db: Session = Depends(get_db), autor: m.Usuario = Depends(acesso)):
    """{ nome, cidade, uf, endereco, telefone, horarios: string[], ativa }. Nasce com estoque zerado."""
    return _loja(db, administracao.criar_loja(db, autor, dados))


@router.put("/lojas/{loja_id}")
def atualizar_loja(loja_id: int, dados: LojaEntrada, db: Session = Depends(get_db), autor: m.Usuario = Depends(acesso)):
    """ativa=false tira a loja do site e da expedição (o histórico continua)."""
    return _loja(db, administracao.atualizar_loja(db, autor, loja_id, dados))


# ---------- Log ----------


@router.get("/log")
def listar_log(
    area: str | None = None,
    usuarioId: int | None = None,
    busca: str | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
):
    """Mais recentes primeiro (até 500): [{ area, acao, descricao, alteracoes: [{ campo, de, para }], usuario, criadoEm }]."""
    return [log_saida(r) for r in log_acoes.listar(db, area=area, usuario_id=usuarioId, busca=busca)]
