"""Central administrativa (só Administrador; 403 para os demais cargos): funcionários, lojas e
log de ações. Cada alteração grava no log quem fez, a partir do token. Regras em
src/use_cases/administracao.py."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.marca import GRUPO, na_marca
from src.middlewares.autenticacao import conferir_marca, escopo_marca, exigir_modulo
from src.repositories import cadastro_repository, usuario_repository
from src.schemas.administracao import (
    FuncionarioEntrada,
    LojaEntrada,
    StatusFuncionarioEntrada,
    funcionario_saida,
    log_saida,
    loja_admin_saida,
)
from src.use_cases import administracao, log_acoes
from src.utils.erros import NaoEncontrado

router = APIRouter(prefix="/admin", tags=["Administração"])
acesso = exigir_modulo("administracao")


def _escopo_de(autor: m.Usuario, marca: str | None) -> str | None:
    """Marca em que o Administrador cadastra: a dele; o do grupo, livre (None), mesmo com o seletor do painel."""
    return None if autor.marca == GRUPO else marca


def _conferir_funcionario(db: Session, usuario_id: int, marca: str | None) -> None:
    """Administrador de uma marca só mexe nos funcionários dela (nunca no grupo)."""
    if marca is None:
        return
    alvo = usuario_repository.por_id(db, usuario_id)
    if alvo is None or alvo.marca != marca:
        raise NaoEncontrado("Funcionário não encontrado.")


# ---------- Funcionários ----------


@router.get("/funcionarios")
def listar_funcionarios(
    busca: str | None = None,
    papel: Literal["ADMINISTRADOR", "LOJISTA", "OPERADOR"] | None = None,
    lojaId: int | None = None,
    status: Literal["ATIVO", "INATIVO"] | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """Administrador de uma marca: só os funcionários dela (o do grupo vê todos)."""
    lista = administracao.listar_funcionarios(db, busca=busca, papel=papel, loja_id=lojaId, status=status)
    return [funcionario_saida(u) for u in lista if marca is None or u.marca == marca]


@router.post("/funcionarios", status_code=201)
def criar_funcionario(
    dados: FuncionarioEntrada,
    db: Session = Depends(get_db),
    autor: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """Cria o funcionário sem senha e envia o convite (link de uso único, 7 dias) para ele criá-la.
    → { funcionario, linkDemo }; linkDemo só vem com LINK_SENHA_NA_RESPOSTA=true."""
    usuario, link = administracao.criar_funcionario(db, autor, dados, _escopo_de(autor, marca))
    return {"funcionario": funcionario_saida(usuario), "linkDemo": link}


@router.put("/funcionarios/{usuario_id}")
def atualizar_funcionario(
    usuario_id: int,
    dados: FuncionarioEntrada,
    db: Session = Depends(get_db),
    autor: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    _conferir_funcionario(db, usuario_id, marca)
    return funcionario_saida(administracao.atualizar_funcionario(db, autor, usuario_id, dados, _escopo_de(autor, marca)))


@router.patch("/funcionarios/{usuario_id}/status")
def alterar_status_funcionario(
    usuario_id: int,
    dados: StatusFuncionarioEntrada,
    db: Session = Depends(get_db),
    autor: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """{ ativo }. 422 ao desativar a si mesmo ou o último Administrador ativo."""
    _conferir_funcionario(db, usuario_id, marca)
    return funcionario_saida(administracao.alterar_status_funcionario(db, autor, usuario_id, dados.ativo))


@router.post("/funcionarios/{usuario_id}/convite")
def reenviar_convite(
    usuario_id: int, db: Session = Depends(get_db), autor: m.Usuario = Depends(acesso), marca: str | None = Depends(escopo_marca)
):
    """Novo convite para quem ainda não criou a senha → { linkDemo }."""
    _conferir_funcionario(db, usuario_id, marca)
    return {"linkDemo": administracao.reenviar_convite(db, autor, usuario_id)}


# ---------- Lojas ----------


@router.get("/lojas")
def listar_lojas(db: Session = Depends(get_db), _: m.Usuario = Depends(acesso), marca: str | None = Depends(escopo_marca)):
    """Lojas da marca (o grupo vê todas; ativas primeiro), com funcionários ativos e peças em estoque."""
    lojas, funcionarios, pecas = administracao.listar_lojas(db)
    return [loja_admin_saida(loja, funcionarios, pecas) for loja in lojas if na_marca(marca, loja.marca)]


def _loja(db: Session, loja: m.Loja) -> dict:
    _, funcionarios, pecas = administracao.listar_lojas(db)
    return loja_admin_saida(loja, funcionarios, pecas)


@router.post("/lojas", status_code=201)
def criar_loja(
    dados: LojaEntrada,
    db: Session = Depends(get_db),
    autor: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """{ nome, cidade, uf, endereco, telefone, horarios: string[], ativa, marca }. Nasce com estoque zerado.
    Do Administrador da marca, sempre da marca dele."""
    return _loja(db, administracao.criar_loja(db, autor, dados, _escopo_de(autor, marca)))


@router.put("/lojas/{loja_id}")
def atualizar_loja(
    loja_id: int,
    dados: LojaEntrada,
    db: Session = Depends(get_db),
    autor: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """ativa=false tira a loja do site e da expedição (o histórico continua). Loja de outra marca: 404."""
    loja = cadastro_repository.loja(db, loja_id)
    conferir_marca(marca, loja.marca if loja else None, "Loja não encontrada.")
    return _loja(db, administracao.atualizar_loja(db, autor, loja_id, dados))


# ---------- Log ----------


@router.get("/log")
def listar_log(
    area: str | None = None,
    usuarioId: int | None = None,
    busca: str | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """Mais recentes primeiro (até 500): [{ area, acao, descricao, alteracoes: [{ campo, de, para }], usuario, criadoEm }].
    Administrador de uma marca: só as ações da equipe dela."""
    registros = log_acoes.listar(db, area=area, usuario_id=usuarioId, busca=busca)
    return [log_saida(r) for r in registros if marca is None or (r.usuario is not None and r.usuario.marca == marca)]
