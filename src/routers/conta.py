"""Configurações da conta do cliente logado (área do cliente > Minha conta > Dados da conta).
Só o próprio cliente, pelo token: a equipe não usa estas rotas. Regras em src/use_cases/conta.py."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import cliente_atual
from src.schemas.conta import DadosContaEntrada, ExclusaoContaEntrada, TrocaSenhaEntrada, conta_saida
from src.use_cases import conta

router = APIRouter(prefix="/conta", tags=["Conta do cliente"])


@router.get("")
def obter(cliente: m.Cliente = Depends(cliente_atual)):
    """{ id, nome, email, cpf, telefone, clienteDesde }."""
    return conta_saida(cliente)


@router.put("")
def atualizar(dados: DadosContaEntrada, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """{ nome, email, telefone, senhaAtual? }. O CPF não muda. Trocar o e-mail pede senhaAtual; e-mail em uso: 409."""
    return conta_saida(
        conta.atualizar(db, cliente, nome=dados.nome, email=dados.email, telefone=dados.telefone, senha_atual=dados.senha_atual)
    )


@router.put("/senha", status_code=204, response_class=Response)
def trocar_senha(dados: TrocaSenhaEntrada, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """{ senhaAtual, senha, senhaConfirmacao }. Senha atual errada: 422."""
    conta.trocar_senha(db, cliente, senha_atual=dados.senha_atual, senha=dados.senha, confirmacao=dados.senha_confirmacao)


@router.post("/exclusao", status_code=204, response_class=Response)
def excluir(dados: ExclusaoContaEntrada, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """{ senha }. Apaga os dados pessoais e encerra o acesso; pedidos e chamados ficam anônimos."""
    conta.excluir(db, cliente, senha=dados.senha)
