from src import models as m


def cliente_saida(cliente: m.Cliente | None) -> dict | None:
    """Nunca inclui o hash do PIN nem o controle de tentativas: só se o cliente já tem PIN."""
    if cliente is None:
        return None
    return {
        "id": cliente.id,
        "nome": cliente.nome,
        "email": cliente.email,
        "telefone": cliente.telefone,
        "clienteDesde": cliente.cliente_desde.isoformat() if cliente.cliente_desde else None,
        "lojaPreferidaId": cliente.loja_preferida_id,
        "temPin": cliente.pin_hash is not None,
    }
