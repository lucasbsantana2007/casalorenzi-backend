from src import models as m


def cliente_saida(cliente: m.Cliente | None) -> dict | None:
    """Nunca inclui hash de senha ou PIN nem o controle de tentativas: só se o cliente tem conta e PIN."""
    if cliente is None:
        return None
    return {
        "id": cliente.id,
        "nome": cliente.nome,
        "email": cliente.email,
        "telefone": cliente.telefone,
        "clienteDesde": cliente.cliente_desde.isoformat() if cliente.cliente_desde else None,
        "lojaPreferidaId": cliente.loja_preferida_id,
        "cpf": cliente.cpf,
        "temConta": cliente.senha_hash is not None,
        "temPin": cliente.pin_hash is not None,
        "excluido": cliente.excluido_em is not None,
    }
