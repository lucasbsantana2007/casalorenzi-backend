"""Ferramentas dos assistentes: as únicas consultas que um assistente (o modelo ou as regras) consegue fazer.

Cada ferramenta tem um contrato tipado (Pydantic, sem campo extra), diz o que exige (cliente logado ou um
módulo da equipe, pela tabela ACESSO de src/entities/papeis.py) e roda numa sessão própria do banco: só
leitura, salvo a ferramenta marcada com escrita (a dos pontos, que lança o vencimento como o resto da
plataforma). Não existe ferramenta de SQL livre, de alterar estoque ou de finalizar compra.

O que chega do modelo é dado não confiável: nome inexistente, parâmetro inválido, parâmetro a mais (um
cliente_id, por exemplo) ou falta de permissão viram uma resposta de erro para o modelo, nunca uma exceção,
e ficam registrados na auditoria (chamadas_ferramenta). Quem é o usuário vem sempre do token (Contexto),
nunca de um parâmetro.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session

from src.database.connection import SessionLeitura, SessionLocal
from src.entities.papeis import pode_acessar
from src.utils.erros import ErroDeNegocio

log = logging.getLogger("casalorenzi.assistente")

ROTULO_PAPEL = {"ADMINISTRADOR": "Administrador", "LOJISTA": "Lojista", "OPERADOR": "Operador"}
ROTULO_MODULO = {
    "financeiro": "dados financeiros (vendas, faturamento e Helo)",
    "estoque": "estoque",
    "transferencias": "transferências",
    "atendimento": "dados de clientes e do Helo",
    "dashboard": "indicadores do painel",
}


@dataclass
class Contexto:
    """Quem pergunta, de onde e o que a conversa já sabe. Montado pelo backend a partir do token."""

    tipo: str
    conversa_id: str
    origem: str  # LLM, REGRAS ou CONTINGENCIA
    cliente_id: int | None = None
    usuario_id: int | None = None
    papel: str | None = None
    # Equipe: a marca que a pessoa vê (None = as duas)
    marca_escopo: str | None = None
    # Site: a vitrine aberta (LORENZI ou VULTO)
    marca_site: str | None = None
    memoria: dict = field(default_factory=dict)
    # Botão da tela que acompanhou a mensagem (ex.: "Quero esta" num card = FOCAR_PRODUTO)
    acao: dict | None = None


@dataclass
class Resultado:
    # Para o modelo: JSON compacto, com os valores já formatados (ele copia, não calcula)
    dados: dict
    # Para a tela: cards, tabelas, gráficos e botões, desenhados com estes dados
    blocos: list[dict] = field(default_factory=list)
    # O que a conversa passa a lembrar (peça em foco, última busca...)
    memoria: dict = field(default_factory=dict)
    # Resposta pronta em português, usada quando não há modelo (regras)
    texto: str | None = None


class FalhaFerramenta(Exception):
    """A consulta não pôde ser feita por um motivo que o modelo e o usuário podem entender."""

    def __init__(self, mensagem: str):
        super().__init__(mensagem)
        self.mensagem = mensagem


class Entrada(BaseModel):
    """Base dos parâmetros: campo desconhecido é recusado (o modelo não injeta cliente_id nem SQL)."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    descricao: str
    entrada: type[Entrada]
    funcao: Callable[[Session, Contexto, Any], Resultado]
    # Módulo da equipe exigido (tabela ACESSO); None = qualquer um do assistente
    modulo: str | None = None
    # Dado pessoal: só com cliente logado, e sempre o do token
    exige_cliente: bool = False
    # Pode gravar (só o vencimento dos pontos, pela regra oficial do Helo)
    escrita: bool = False

    def esquema(self) -> dict:
        """Definição da ferramenta no formato da API do modelo (name, description, input_schema)."""
        schema = self.entrada.model_json_schema()
        schema.pop("title", None)
        for propriedade in schema.get("properties", {}).values():
            propriedade.pop("title", None)
        return {"name": self.nome, "description": self.descricao, "input_schema": schema}


@dataclass
class Execucao:
    nome: str
    argumentos: Any
    resultado: Resultado | None
    erro: str | None
    duracao_ms: int
    negada: bool = False
    banco_indisponivel: bool = False
    # Quem pediu a consulta (LLM, REGRAS ou CONTINGENCIA), para a auditoria
    origem: str = ""

    @property
    def sucesso(self) -> bool:
        return self.erro is None


def motivo_da_recusa(ferramenta: Ferramenta, ctx: Contexto) -> str | None:
    """Por que este usuário não pode usar a ferramenta (None = pode). Conferido a cada chamada."""
    if ferramenta.exige_cliente and ctx.cliente_id is None:
        return "LOGIN_NECESSARIO: para ver essa informação, o cliente precisa entrar na conta."
    if ferramenta.modulo is not None:
        if ctx.papel is None:
            return "SEM_PERMISSAO: consulta exclusiva da equipe."
        if not pode_acessar(ctx.papel, ferramenta.modulo):
            papel = ROTULO_PAPEL.get(ctx.papel, ctx.papel)
            assunto = ROTULO_MODULO.get(ferramenta.modulo, ferramenta.modulo)
            return f"SEM_PERMISSAO: o perfil {papel} não tem acesso a {assunto}."
    return None


def _resumo_validacao(erro: ValidationError) -> str:
    partes = []
    for item in erro.errors()[:4]:
        campo = ".".join(str(p) for p in item.get("loc", ())) or "parâmetros"
        if item.get("type") == "extra_forbidden":
            partes.append(f"{campo}: parâmetro não existe nesta ferramenta")
        else:
            partes.append(f"{campo}: {item.get('msg', 'inválido')}")
    return "; ".join(partes)[:220]


def executar(registro: dict[str, Ferramenta], nome: Any, argumentos: Any, ctx: Contexto) -> Execucao:
    """Valida, confere a permissão e roda a ferramenta. Nunca levanta exceção: o erro volta na Execucao."""
    inicio = time.perf_counter()

    def fim(resultado: Resultado | None = None, erro: str | None = None, **extra) -> Execucao:
        duracao = int((time.perf_counter() - inicio) * 1000)
        return Execucao(str(nome)[:60], argumentos, resultado, erro, duracao, **extra)

    ferramenta = registro.get(nome) if isinstance(nome, str) else None
    if ferramenta is None:
        return fim(erro=f"FERRAMENTA_INEXISTENTE: '{str(nome)[:40]}' não existe. Use só as ferramentas oferecidas.")
    if motivo := motivo_da_recusa(ferramenta, ctx):
        return fim(erro=motivo, negada=True)
    if argumentos is None:
        argumentos = {}
    if not isinstance(argumentos, dict):
        return fim(erro="PARAMETROS_INVALIDOS: os parâmetros precisam ser um objeto JSON.")
    try:
        entrada = ferramenta.entrada.model_validate(argumentos)
    except ValidationError as erro:
        return fim(erro=f"PARAMETROS_INVALIDOS: {_resumo_validacao(erro)}")

    db = SessionLocal() if ferramenta.escrita else SessionLeitura()
    try:
        resultado = ferramenta.funcao(db, ctx, entrada)
        if ferramenta.escrita:
            db.commit()
        return fim(resultado=resultado)
    except (FalhaFerramenta, ErroDeNegocio) as erro:
        db.rollback()
        return fim(erro=erro.mensagem)
    except (OperationalError, InterfaceError):
        db.rollback()
        log.exception("Banco indisponível na ferramenta %s (conversa %s)", nome, ctx.conversa_id)
        return fim(
            erro="BANCO_INDISPONIVEL: o banco de dados não respondeu. Tente de novo em instantes.", banco_indisponivel=True
        )
    except Exception:
        db.rollback()
        log.exception("Falha na ferramenta %s (conversa %s)", nome, ctx.conversa_id)
        return fim(erro="FALHA_INTERNA: não consegui fazer essa consulta agora.")
    finally:
        db.close()


def registro_de(ferramentas: list[Ferramenta]) -> dict[str, Ferramenta]:
    return {f.nome: f for f in ferramentas}


def oferecidas(ferramentas: list[Ferramenta], ctx: Contexto) -> list[Ferramenta]:
    """Ferramentas que o modelo recebe: só as que este usuário pode usar (a execução confere de novo).
    As de dado pessoal ficam na lista mesmo sem login, para o modelo saber pedir o login."""
    return [f for f in ferramentas if f.exige_cliente or motivo_da_recusa(f, ctx) is None]
