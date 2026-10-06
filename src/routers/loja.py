"""Rotas públicas da loja (sem login): checkout e "Meus pedidos".

O cliente não tem conta: o e-mail + PIN de 4 dígitos (criado no checkout) vão no corpo de
cada requisição de "Meus pedidos". Por isso as consultas também são POST: o PIN nunca vai
na URL. Regras em src/use_cases/checkout.py e src/use_cases/meus_pedidos.py.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.database.connection import get_db
from src.schemas.meus_pedidos import (
    EsqueciPinEntrada,
    IdentificacaoEntrada,
    RedefinirPinEntrada,
    RespostaClienteEntrada,
    SolicitacaoClienteEntrada,
    solicitacao_publica_saida,
)
from src.schemas.pedidos import CheckoutEntrada, pedido_publico_saida
from src.use_cases import checkout, meus_pedidos

router = APIRouter(tags=["Loja"])


@router.post("/checkout", status_code=201)
def finalizar_compra(dados: CheckoutEntrada, db: Session = Depends(get_db)):
    """Cria o pedido (pagamento simulado, aprovado). Preços e frete são recalculados aqui.
    E-mail que já tem PIN precisa usar o mesmo: 409. Item esgotado: 409."""
    return pedido_publico_saida(checkout.finalizar_compra(db, dados))


@router.post("/meus-pedidos")
def listar_meus_pedidos(dados: IdentificacaoEntrada, db: Session = Depends(get_db)):
    """Pedidos do e-mail. E-mail ou PIN incorretos: 401. Após 5 erros seguidos, 429 por 15 minutos."""
    return [pedido_publico_saida(p) for p in meus_pedidos.pedidos(db, dados.email, dados.pin)]


@router.post("/meus-pedidos/esqueci-pin")
def esqueci_pin(dados: EsqueciPinEntrada, db: Session = Depends(get_db)):
    """Envia o link de troca de PIN (por enquanto, no log da API). A resposta é a mesma exista ou
    não o e-mail. linkDemo só vem com PIN_LINK_NA_RESPOSTA=true."""
    return {"enviado": True, "linkDemo": meus_pedidos.solicitar_novo_pin(db, dados.email)}


@router.post("/meus-pedidos/redefinir-pin")
def redefinir_pin(dados: RedefinirPinEntrada, db: Session = Depends(get_db)):
    """Link vencido ou já usado: 410."""
    return {"email": meus_pedidos.redefinir_pin(db, dados.token, dados.pin, dados.pin_confirmacao)}


@router.post("/meus-pedidos/solicitacoes/consulta")
def listar_solicitacoes(dados: IdentificacaoEntrada, db: Session = Depends(get_db)):
    """Chamados do e-mail, com a conversa e as fotos anexadas."""
    return [solicitacao_publica_saida(a) for a in meus_pedidos.solicitacoes(db, dados.email, dados.pin)]


@router.post("/meus-pedidos/solicitacoes", status_code=201)
def abrir_solicitacao(dados: SolicitacaoClienteEntrada, db: Session = Depends(get_db)):
    """Abre um chamado sobre um pedido do cliente. anexo (opcional): { nome, tipo, conteudoBase64 },
    imagem JPG, PNG ou WEBP de até 2 MB."""
    atendimento = meus_pedidos.abrir_solicitacao(
        db,
        dados.email,
        dados.pin,
        numero=dados.numero,
        tipo_solicitacao_id=dados.tipo_solicitacao_id,
        descricao=dados.descricao,
        anexo=dados.anexo,
    )
    return {"id": atendimento.id, "protocolo": atendimento.protocolo, "tipo": atendimento.tipo_solicitacao.titulo}


@router.post("/meus-pedidos/solicitacoes/{atendimento_id}/mensagens")
def responder_solicitacao(atendimento_id: int, dados: RespostaClienteEntrada, db: Session = Depends(get_db)):
    """Chamado encerrado: 409. Chamado de outro cliente: 404."""
    atendimento = meus_pedidos.responder(db, dados.email, dados.pin, atendimento_id, dados.conteudo)
    return solicitacao_publica_saida(atendimento)
