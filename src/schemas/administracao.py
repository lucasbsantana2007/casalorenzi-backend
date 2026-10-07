from pydantic import Field

from src import models as m
from src.schemas.comum import Entrada, loja_saida, usuario_resumo
from src.utils.datas import ms


class FuncionarioEntrada(Entrada):
    nome: str = ""
    email: str = ""
    papel: str = ""
    loja_id: int | None = None


class StatusFuncionarioEntrada(Entrada):
    ativo: bool


class LojaEntrada(Entrada):
    nome: str = ""
    cidade: str = ""
    uf: str = ""
    endereco: str = ""
    telefone: str = ""
    horarios: list[str] = Field(default_factory=list)
    ativa: bool = True


def funcionario_saida(usuario: m.Usuario) -> dict:
    """Nunca inclui o hash da senha: só se o convite ainda está pendente."""
    loja = usuario.loja
    return {
        "id": usuario.id,
        "nome": usuario.nome,
        "email": usuario.email,
        "papel": usuario.papel,
        "lojaId": usuario.loja_id,
        "loja": {"id": loja.id, "nome": loja.nome} if loja else None,
        "ativo": usuario.ativo,
        "convitePendente": usuario.convite_pendente,
    }


def loja_admin_saida(loja: m.Loja, funcionarios_ativos: dict[int, int], pecas: dict[int, int]) -> dict:
    return {
        **loja_saida(loja),
        "funcionariosAtivos": funcionarios_ativos.get(loja.id, 0),
        "pecasEmEstoque": pecas.get(loja.id, 0),
    }


def log_saida(registro: m.LogAcao) -> dict:
    referencia = {"tipo": registro.referencia_tipo, "id": registro.referencia_id} if registro.referencia_tipo else None
    return {
        "id": registro.id,
        "area": registro.area,
        "acao": registro.acao,
        "descricao": registro.descricao,
        "alteracoes": registro.alteracoes or [],
        "referencia": referencia,
        "usuarioId": registro.usuario_id,
        "usuario": usuario_resumo(registro.usuario),
        "criadoEm": ms(registro.criado_em),
    }
