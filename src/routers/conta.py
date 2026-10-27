"""Configurações da conta do cliente logado (área do cliente > Minha conta > Dados da conta).
Só o próprio cliente, pelo token: a equipe não usa estas rotas. Regras em src/use_cases/conta.py."""

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import cliente_atual
from src.schemas.comum import Entrada
from src.schemas.conta import DadosContaEntrada, ExclusaoContaEntrada, TrocaSenhaEntrada, conta_saida
from src.schemas.fidelidade import pontos_saida
from src.use_cases import conta, fidelidade, pedidos_cliente

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


@router.get("/pontos")
def pontos(db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """Lupe+ do cliente logado: { saldo, valorEmReais, categoria, bonus, aVencer, extrato, regras }."""
    return pontos_saida(fidelidade.resumo(db, cliente))


@router.put("/senha", status_code=204, response_class=Response)
def trocar_senha(dados: TrocaSenhaEntrada, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """{ senhaAtual, senha, senhaConfirmacao }. Senha atual errada: 422."""
    conta.trocar_senha(db, cliente, senha_atual=dados.senha_atual, senha=dados.senha, confirmacao=dados.senha_confirmacao)


@router.post("/exclusao", status_code=204, response_class=Response)
def excluir(dados: ExclusaoContaEntrada, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """{ senha }. Apaga os dados pessoais e encerra o acesso; pedidos e chamados ficam anônimos."""
    conta.excluir(db, cliente, senha=dados.senha)


# ---------- Pedidos do próprio cliente: cancelar e pedir devolução (decisões 96 e 97) ----------


class PecaEntrada(Entrada):
    item_pedido_id: int
    quantidade: int = Field(ge=1, le=99)


class DevolucaoClienteEntrada(Entrada):
    pecas: list[PecaEntrada] = Field(min_length=1, max_length=30)
    motivo: str = Field(max_length=500)


@router.post("/pedidos/{numero}/cancelamento")
def cancelar_pedido(numero: str, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)):
    """Cancela um pedido do cliente ainda em separação: estorna o pagamento e acerta os pontos. Já enviado ou já
    cancelado: 409. Pedido de outra pessoa: 404."""
    pedido = pedidos_cliente.cancelar(db, cliente, numero)
    estornado = sum(p.valor for p in pedido.pagamentos if p.status == "ESTORNADO")
    return {"numero": pedido.numero, "status": pedido.status, "valorEstornado": float(estornado)}


@router.post("/pedidos/{numero}/devolucao", status_code=201)
def pedir_devolucao(
    numero: str, dados: DevolucaoClienteEntrada, db: Session = Depends(get_db), cliente: m.Cliente = Depends(cliente_atual)
):
    """{ pecas: [{ itemPedidoId, quantidade }], motivo }. Abre a solicitação "Devolução e reembolso" do pedido (a
    equipe confere a peça e faz o estorno). Fora do prazo de 30 dias ou pedido não enviado: 409. Pedir de novo,
    com uma aberta para o mesmo pedido, devolve a mesma."""
    pecas = [pedidos_cliente.PecaDevolvida(p.item_pedido_id, p.quantidade) for p in dados.pecas]
    atendimento = pedidos_cliente.pedir_devolucao(db, cliente, numero, pecas, dados.motivo)
    return {
        "atendimentoId": atendimento.id,
        "protocolo": atendimento.protocolo,
        "link": f"/cliente/solicitacoes/{atendimento.id}",
    }
