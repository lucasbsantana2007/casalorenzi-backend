from src import models as m
from src.schemas.comum import Entrada


class AcessoEntrada(Entrada):
    """E-mail para onde vai o link de criar a senha."""

    email: str = ""


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
        # Calculados do cadastro: o que só o cliente pode corrigir (CPF_INVALIDO, SEM_EMAIL, TELEFONE_SEM_DDD...)
        "dadosValidos": cliente.dados_validos,
        "problemasCadastro": cliente.problemas_cadastro,
        # Precisa corrigir o cadastro no próximo login para continuar usando os benefícios (decisão 52)
        "atualizarCadastro": cliente.atualizar_cadastro,
    }
