"""Central administrativa (só Administrador): funcionários, lojas e log de ações.

- Funcionário novo nasce sem senha: recebe por e-mail um convite (link de uso único, 7 dias) para
  criá-la. Antes disso não entra. Por enquanto o e-mail sai no log da API; com
  LINK_SENHA_NA_RESPOSTA=true (demonstração) o link volta na resposta.
- Sempre fica pelo menos um Administrador ativo, e ninguém desativa a própria conta.
- Loja nova nasce com estoque zerado de todas as variações; loja inativa sai do site e da expedição.
- Toda alteração vai para o log com quem fez (do token) e o que mudou.
"""

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from src import models as m
from src.config.settings import LINK_SENHA_NA_RESPOSTA
from src.entities.cliente import email_valido, normalizar_email
from src.entities.papeis import ADMINISTRADOR, PAPEIS
from src.repositories import (
    cadastro_repository,
    cliente_repository,
    estoque_repository,
    produto_repository,
    sessao,
    usuario_repository,
)
from src.use_cases import log_acoes
from src.use_cases.autenticacao import criar_link_senha
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos, NaoEncontrado
from src.utils.texto import chave_texto, corresponde

log = logging.getLogger("casalorenzi")

VALIDADE_CONVITE = timedelta(days=7)
NOMES_PAPEIS = {"ADMINISTRADOR": "Administrador", "LOJISTA": "Lojista", "OPERADOR": "Operador"}
UFS = (
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
)  # fmt: skip
MINIMO_DE_ADMIN = "É preciso manter pelo menos um Administrador ativo."


# ---------- Funcionários ----------


def listar_funcionarios(
    db: Session, *, busca: str | None = None, papel: str | None = None, loja_id: int | None = None, status: str | None = None
) -> list[m.Usuario]:
    """status: ATIVO ou INATIVO. Ativos primeiro, depois por nome."""
    lista = [
        u
        for u in usuario_repository.todos(db)
        if (not papel or u.papel == papel)
        and (not loja_id or u.loja_id == loja_id)
        and (not status or u.ativo == (status == "ATIVO"))
        and corresponde(busca, u.nome, u.email)
    ]
    lista.sort(key=lambda u: (not u.ativo, chave_texto(u.nome)))
    return lista


def _validar_funcionario(db: Session, dados, usuario_id: int | None = None) -> dict:
    nome = (dados.nome or "").strip()
    if not nome:
        raise DadosInvalidos("Informe o nome.")
    if len(nome) > 120:
        raise DadosInvalidos("O nome deve ter no máximo 120 caracteres.")
    email = normalizar_email(dados.email)
    if not email_valido(email):
        raise DadosInvalidos("Informe um e-mail válido.")
    outro = usuario_repository.por_email(db, email)
    if (outro is not None and outro.id != usuario_id) or cliente_repository.por_email(db, email) is not None:
        raise Conflito("Este e-mail já está em uso.")
    if dados.papel not in PAPEIS:
        raise DadosInvalidos("Selecione o cargo.")
    # Lojista e Operador trabalham numa loja; o Administrador governa a rede toda
    loja_id = None
    if dados.papel != ADMINISTRADOR:
        loja = cadastro_repository.loja(db, dados.loja_id) if dados.loja_id else None
        if loja is None:
            raise DadosInvalidos("Selecione a loja deste funcionário.")
        loja_id = loja.id
    return {"nome": nome, "email": email, "papel": dados.papel, "loja_id": loja_id}


def _nome_da_loja(db: Session, loja_id: int | None) -> str:
    loja = cadastro_repository.loja(db, loja_id) if loja_id else None
    return loja.nome if loja else "—"


def _convite(db: Session, usuario: m.Usuario) -> str | None:
    """Gera o link do convite e "envia" o e-mail (por enquanto, no log da API)."""
    link = criar_link_senha(db, VALIDADE_CONVITE, usuario=usuario)
    log.info(
        "Convite para %s (%s no painel da Casa Lorenzi): crie sua senha em %s (vale 7 dias)",
        usuario.email,
        NOMES_PAPEIS[usuario.papel],
        link,
    )
    return link if LINK_SENHA_NA_RESPOSTA else None


def criar_funcionario(db: Session, autor: m.Usuario, dados) -> tuple[m.Usuario, str | None]:
    """(funcionário, link do convite só na demonstração)."""
    campos = _validar_funcionario(db, dados)
    usuario = m.Usuario(**campos, senha_hash=None, ativo=True, criado_em=agora())
    sessao.adicionar(db, usuario)
    sessao.gerar_ids(db)
    link = _convite(db, usuario)
    loja = f" · {_nome_da_loja(db, usuario.loja_id)}" if usuario.loja_id else ""
    log_acoes.registrar(
        db,
        autor,
        "FUNCIONARIOS",
        "CADASTROU",
        f"Cadastrou {usuario.nome} como {NOMES_PAPEIS[usuario.papel]}{loja}",
        referencia=("funcionario", usuario.id),
    )
    sessao.confirmar(db, usuario)
    return usuario, link


def _funcionario(db: Session, usuario_id: int) -> m.Usuario:
    usuario = usuario_repository.por_id(db, usuario_id)
    if usuario is None:
        raise NaoEncontrado("Funcionário não encontrado.")
    return usuario


def atualizar_funcionario(db: Session, autor: m.Usuario, usuario_id: int, dados) -> m.Usuario:
    usuario = _funcionario(db, usuario_id)
    campos = _validar_funcionario(db, dados, usuario.id)
    deixa_de_ser_admin = usuario.papel == ADMINISTRADOR and campos["papel"] != ADMINISTRADOR
    if deixa_de_ser_admin and usuario.ativo and not usuario_repository.administradores_ativos(db, exceto_id=usuario.id):
        raise DadosInvalidos(MINIMO_DE_ADMIN)
    antes = {"nome": usuario.nome, "email": usuario.email, "papel": usuario.papel, "loja_id": usuario.loja_id}
    alteracoes = log_acoes.mudancas(
        antes,
        campos,
        {"nome": "Nome", "email": "E-mail", "papel": "Cargo", "loja_id": "Loja"},
        {"papel": lambda v: NOMES_PAPEIS.get(v, "—"), "loja_id": lambda v: _nome_da_loja(db, v)},
    )
    for campo, valor in campos.items():
        setattr(usuario, campo, valor)
    if alteracoes:
        log_acoes.registrar(
            db,
            autor,
            "FUNCIONARIOS",
            "EDITOU",
            f"Editou o cadastro de {usuario.nome}",
            alteracoes,
            referencia=("funcionario", usuario.id),
        )
    sessao.confirmar(db, usuario)
    return usuario


def alterar_status_funcionario(db: Session, autor: m.Usuario, usuario_id: int, ativo: bool) -> m.Usuario:
    """Desativado não entra mais no painel (e a sessão aberta deixa de valer)."""
    usuario = _funcionario(db, usuario_id)
    if not ativo and usuario.id == autor.id:
        raise DadosInvalidos("Você não pode desativar a sua própria conta.")
    if not ativo and usuario.papel == ADMINISTRADOR and not usuario_repository.administradores_ativos(db, exceto_id=usuario.id):
        raise DadosInvalidos(MINIMO_DE_ADMIN)
    if usuario.ativo == ativo:
        return usuario
    usuario.ativo = ativo
    log_acoes.registrar(
        db,
        autor,
        "FUNCIONARIOS",
        "REATIVOU" if ativo else "DESATIVOU",
        f"{'Reativou' if ativo else 'Desativou'} o acesso de {usuario.nome}",
        referencia=("funcionario", usuario.id),
    )
    sessao.confirmar(db, usuario)
    return usuario


def reenviar_convite(db: Session, autor: m.Usuario, usuario_id: int) -> str | None:
    usuario = _funcionario(db, usuario_id)
    if not usuario.convite_pendente:
        raise DadosInvalidos("Este funcionário já criou a senha.")
    if not usuario.ativo:
        raise DadosInvalidos("Reative o funcionário antes de reenviar o convite.")
    link = _convite(db, usuario)
    log_acoes.registrar(
        db,
        autor,
        "FUNCIONARIOS",
        "REENVIOU",
        f"Reenviou o convite de acesso para {usuario.nome}",
        referencia=("funcionario", usuario.id),
    )
    sessao.confirmar(db)
    return link


# ---------- Lojas ----------


def listar_lojas(db: Session) -> tuple[list[m.Loja], dict[int, int], dict[int, int]]:
    """(lojas, funcionários ativos por loja, peças em estoque por loja). Ativas primeiro."""
    lojas = sorted(cadastro_repository.lojas(db), key=lambda loja: (not loja.ativa, chave_texto(loja.nome)))
    return lojas, usuario_repository.ativos_por_loja(db), estoque_repository.pecas_por_loja(db)


def _validar_loja(db: Session, dados, loja_id: int | None = None) -> dict:
    nome = (dados.nome or "").strip()
    if not nome:
        raise DadosInvalidos("Informe o nome da loja.")
    if len(nome) > 120:
        raise DadosInvalidos("O nome da loja deve ter no máximo 120 caracteres.")
    outra = cadastro_repository.loja_por_nome(db, nome)
    if outra is not None and outra.id != loja_id:
        raise Conflito("Já existe uma loja com este nome.")
    cidade = (dados.cidade or "").strip()
    if not cidade:
        raise DadosInvalidos("Informe a cidade.")
    if dados.uf not in UFS:
        raise DadosInvalidos("Selecione o estado.")
    endereco = (dados.endereco or "").strip()
    telefone = (dados.telefone or "").strip()
    horarios = [h.strip() for h in dados.horarios or [] if h and h.strip()]
    if (
        len(cidade) > 120
        or len(endereco) > 255
        or len(telefone) > 30
        or len(horarios) > 10
        or any(len(h) > 120 for h in horarios)
    ):
        raise DadosInvalidos("Algum campo da loja passou do tamanho permitido.")
    return {
        "nome": nome,
        "cidade": cidade,
        "uf": dados.uf,
        "endereco": endereco,
        "telefone": telefone,
        "horarios": horarios,
        "ativa": dados.ativa is not False,
    }


_ROTULOS_LOJA = {
    "nome": "Nome",
    "cidade": "Cidade",
    "uf": "Estado",
    "endereco": "Endereço",
    "telefone": "Telefone",
    "horarios": "Horários",
    "ativa": "Ativa",
}
_FORMATOS_LOJA = {"ativa": lambda v: "Sim" if v else "Não"}


def criar_loja(db: Session, autor: m.Usuario, dados) -> m.Loja:
    loja = m.Loja(**_validar_loja(db, dados))
    sessao.adicionar(db, loja)
    sessao.gerar_ids(db)
    # Estoque zerado de todas as variações, para a loja já poder receber transferências
    momento = agora()
    for variacao in produto_repository.todas_variacoes(db):
        sessao.adicionar(
            db, m.Estoque(loja_id=loja.id, variacao_id=variacao.id, quantidade=0, quantidade_min=2, atualizado_em=momento)
        )
    log_acoes.registrar(
        db, autor, "LOJAS", "CADASTROU", f"Cadastrou a loja {loja.nome} ({loja.cidade}, {loja.uf})", referencia=("loja", loja.id)
    )
    sessao.confirmar(db, loja)
    return loja


def atualizar_loja(db: Session, autor: m.Usuario, loja_id: int, dados) -> m.Loja:
    loja = cadastro_repository.loja(db, loja_id)
    if loja is None:
        raise NaoEncontrado("Loja não encontrada.")
    campos = _validar_loja(db, dados, loja.id)
    antes = {campo: getattr(loja, campo) for campo in _ROTULOS_LOJA}
    antes["horarios"] = list(antes["horarios"] or [])
    alteracoes = log_acoes.mudancas(antes, campos, _ROTULOS_LOJA, _FORMATOS_LOJA)
    nome_anterior = loja.nome
    for campo, valor in campos.items():
        setattr(loja, campo, valor)
    if alteracoes:
        status = ""
        if antes["ativa"] != campos["ativa"]:
            status = " e reativou" if campos["ativa"] else " e desativou"
        log_acoes.registrar(
            db, autor, "LOJAS", "EDITOU", f"Editou{status} a loja {nome_anterior}", alteracoes, referencia=("loja", loja.id)
        )
    sessao.confirmar(db, loja)
    return loja
