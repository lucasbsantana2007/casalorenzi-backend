from src import models as m


def cliente_saida(cliente: m.Cliente | None) -> dict | None:
    """Nunca inclui o hash da senha: só se o cliente já tem conta."""
    if cliente is None:
        return None
    return {
        # id público = CPF (nulo na conta excluída, que tem os dados pessoais apagados)
        "id": cliente.cpf,
        "nome": cliente.nome,
        "email": cliente.email,
        "telefone": cliente.telefone,
        "clienteDesde": cliente.cliente_desde.isoformat() if cliente.cliente_desde else None,
        "lojaPreferidaId": cliente.loja_preferida_id,
        "cpf": cliente.cpf,
        "temConta": cliente.senha_hash is not None,
        "excluido": cliente.excluido_em is not None,
    }
