"""Clientes: equipe de atendimento (painel) ou o próprio cliente logado (área do cliente).

O id do cliente nas rotas é o CPF (11 dígitos), como no site; por dentro, a API usa o número da
tabela. O cliente só acessa o próprio CPF: o de outra pessoa aparece como inexistente (404), para
não revelar quem é cliente.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.marca import na_marca
from src.middlewares.autenticacao import Sessao, escopo_marca, exigir_cliente_ou_modulo, exigir_modulo
from src.routers.atendimentos import detalhe_saida, lista_saida
from src.schemas.clientes import AcessoEntrada, cliente_saida
from src.schemas.fidelidade import pontos_saida
from src.schemas.pedidos import pedido_saida
from src.use_cases import clientes, fidelidade
from src.utils.erros import NaoEncontrado

router = APIRouter(prefix="/clientes", tags=["Clientes"])
acesso_painel = exigir_modulo("atendimento")
acesso = exigir_cliente_ou_modulo("atendimento")


def _cliente(db: Session, sessao: Sessao, cpf: str) -> m.Cliente:
    """Cliente do CPF da rota, conferindo que o cliente logado só abre a própria conta."""
    cliente = clientes.por_cpf(db, cpf)
    if sessao.cliente is not None and sessao.cliente.id != cliente.id:
        raise NaoEncontrado("Cliente não encontrado.")
    return cliente


@router.get("")
def listar(
    busca: str | None = None,
    dadosValidos: bool | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(acesso_painel),
):
    """Busca por nome, e-mail, telefone (até 50 resultados). Só a equipe. Usada para abrir chamado em nome do cliente.
    dadosValidos=false lista todos os clientes com algo a corrigir no cadastro (CPF inválido, sem e-mail,
    telefone sem DDD...), com o motivo em problemasCadastro: a lista de quem contatar."""
    return [cliente_saida(c) for c in clientes.listar(db, busca, dadosValidos)]


@router.get("/{cliente_id}")
def obter(cliente_id: str, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    cliente = _cliente(db, sessao, cliente_id)
    total_pedidos, total_atendimentos = clientes.totais(db, cliente.id)
    return {**cliente_saida(cliente), "totalPedidos": total_pedidos, "totalAtendimentos": total_atendimentos}


@router.get("/{cliente_id}/pontos")
def pontos(cliente_id: str, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    """Vulto+ do cliente (equipe de atendimento ou o próprio cliente): saldo, categoria e extrato."""
    return pontos_saida(fidelidade.resumo(db, _cliente(db, sessao, cliente_id)))


@router.post("/{cliente_id}/acesso")
def liberar_acesso(cliente_id: str, dados: AcessoEntrada, db: Session = Depends(get_db), _: m.Usuario = Depends(acesso_painel)):
    """Só a equipe de atendimento. Cadastra o e-mail do cliente (ex.: cliente da Vulto sem e-mail) e manda
    o link para ele criar a senha; depois ele entra com o CPF ou o e-mail. E-mail de outra conta: 409."""
    return {"enviado": True, "linkDemo": clientes.liberar_acesso(db, clientes.por_cpf(db, cliente_id), dados.email)}


@router.get("/{cliente_id}/pedidos")
def listar_pedidos(
    cliente_id: str, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso), marca: str | None = Depends(escopo_marca)
):
    """O cliente é um só nas duas marcas; a equipe de uma marca vê só os pedidos dela."""
    cliente = _cliente(db, sessao, cliente_id)
    return [pedido_saida(p) for p in clientes.pedidos(db, cliente.id) if na_marca(marca, p.loja.marca)]


@router.get("/{cliente_id}/pedidos/{numero}")
def consultar_pedido(cliente_id: str, numero: str, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    """Aceita "CL-104820" ou só "104820". Pedido de outro cliente: 404."""
    cliente = _cliente(db, sessao, cliente_id)
    return pedido_saida(clientes.pedido_por_numero(db, cliente.id, numero))


@router.get("/{cliente_id}/atendimentos")
def listar_atendimentos(
    cliente_id: str, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso), marca: str | None = Depends(escopo_marca)
):
    cliente = _cliente(db, sessao, cliente_id)
    return lista_saida(db, [a for a in clientes.atendimentos(db, cliente.id) if na_marca(marca, a.marca)])


@router.get("/{cliente_id}/atendimentos/{atendimento_id}")
def obter_atendimento(cliente_id: str, atendimento_id: int, db: Session = Depends(get_db), sessao: Sessao = Depends(acesso)):
    """Chamado com a conversa e as fotos. Chamado de outro cliente: 404."""
    cliente = _cliente(db, sessao, cliente_id)
    return detalhe_saida(db, clientes.atendimento(db, cliente.id, atendimento_id))
