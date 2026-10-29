"""Alertas operacionais (criados pelas automações) e as automações. Cada tipo de alerta pede o módulo do
assunto (src/entities/assistente.py, MODULO_DO_ALERTA) e respeita a marca do token. Rodar automação, ver o
log das execuções e os e-mails automáticos aos clientes (aba Automações, decisão 127): só Administrador.
Os alertas saíram da tela, mas continuam sendo criados: o Assistente IA e o MCP os consultam."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities import assistente as regra
from src.entities.marca import na_marca
from src.entities.papeis import pode_acessar
from src.middlewares.autenticacao import escopo_marca, exigir_modulo
from src.repositories import alerta_repository, sessao
from src.schemas.comum import Entrada, loja_saida, usuario_resumo
from src.use_cases import automacoes, emails_clientes
from src.utils.datas import agora, ms
from src.utils.erros import DadosInvalidos, NaoEncontrado

router = APIRouter(tags=["Alertas e automações"])
acesso = exigir_modulo("inteligencia")
admin = exigir_modulo("administracao")


class AtualizarAlerta(Entrada):
    status: Literal["RESOLVIDO", "DESCARTADO"]


def _tipos_visiveis(usuario: m.Usuario) -> list[str]:
    return [tipo for tipo, modulo in regra.MODULO_DO_ALERTA.items() if pode_acessar(usuario.papel, modulo)]


def alerta_saida(alerta: m.Alerta) -> dict:
    return {
        "id": alerta.id,
        "tipo": alerta.tipo,
        "titulo": alerta.titulo,
        "descricao": alerta.descricao,
        "dados": alerta.dados,
        "severidade": alerta.severidade,
        "status": alerta.status,
        "marca": alerta.marca,
        "loja": loja_saida(alerta.loja),
        "variacaoId": alerta.variacao_id,
        "criadoEm": ms(alerta.criado_em),
        "atualizadoEm": ms(alerta.atualizado_em),
        "resolvidoEm": ms(alerta.resolvido_em),
        "resolvidoPor": usuario_resumo(alerta.resolvido_por),
    }


@router.get("/alertas")
def listar(
    tipo: Literal["ESTOQUE_BAIXO", "ESTOQUE_PARADO", "SUGESTAO_TRANSFERENCIA", "PONTOS_A_VENCER"] | None = None,
    status: Literal["ABERTO", "RESOLVIDO", "DESCARTADO"] = "ABERTO",
    lojaId: int | None = None,
    limite: int = 200,
    db: Session = Depends(get_db),
    usuario: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """Alertas que o perfil pode ver, mais graves primeiro, com a contagem por tipo e a última execução."""
    tipos = _tipos_visiveis(usuario)
    if tipo is not None:
        tipos = [t for t in tipos if t == tipo]
    alertas = alerta_repository.listar(
        db, tipos=tipos, status=status, marca=marca, loja_id=lojaId, limite=max(1, min(limite, 500))
    )
    contagem = {t: 0 for t in _tipos_visiveis(usuario)}
    for (t, marca_alerta), total in alerta_repository.contagem_abertos(db).items():
        if t in contagem and (marca_alerta is None or na_marca(marca, marca_alerta)):
            contagem[t] += total
    return {
        "alertas": [alerta_saida(a) for a in alertas],
        "abertosPorTipo": contagem,
        "automacoes": automacoes.situacao(db),
    }


@router.patch("/alertas/{alerta_id}")
def atualizar(
    alerta_id: int,
    dados: AtualizarAlerta,
    db: Session = Depends(get_db),
    usuario: m.Usuario = Depends(acesso),
    marca: str | None = Depends(escopo_marca),
):
    """Resolver (a equipe agiu) ou descartar (não vale ação: a situação não volta a alertar por 7 dias).
    Tipo que o perfil não vê ou de outra marca: 404."""
    alerta = alerta_repository.obter(db, alerta_id, travar=True)
    if (
        alerta is None
        or alerta.tipo not in _tipos_visiveis(usuario)
        or not (alerta.marca is None or na_marca(marca, alerta.marca))
    ):
        raise NaoEncontrado("Alerta não encontrado.")
    if alerta.status != regra.ABERTO:
        raise DadosInvalidos("Este alerta já foi encerrado.")
    alerta.status = dados.status
    alerta.resolvido_em = agora()
    alerta.atualizado_em = alerta.resolvido_em
    alerta.resolvido_por_id = usuario.id
    sessao.confirmar(db, alerta)
    return alerta_saida(alerta)


@router.get("/automacoes")
def listar_automacoes(db: Session = Depends(get_db), _: m.Usuario = Depends(admin)):
    return automacoes.situacao(db)


@router.post("/automacoes/{nome}/executar")
def executar(nome: str, usuario: m.Usuario = Depends(admin)):
    """Roda agora (Administrador). Outra execução em andamento ou terminada há menos de 1 minuto: IGNORADA."""
    if nome != "todas" and nome not in automacoes.AUTOMACOES:
        raise NaoEncontrado("Automação não encontrada.")
    execucoes = automacoes.executar_todas(usuario.id) if nome == "todas" else [automacoes.executar(nome, usuario_id=usuario.id)]
    return [
        {
            "automacao": e.automacao,
            "status": e.status,
            "criados": e.criados,
            "atualizados": e.atualizados,
            "resolvidos": e.resolvidos,
            "detalhe": e.detalhe,
            "iniciadaEm": ms(e.iniciada_em),
            "terminadaEm": ms(e.terminada_em),
        }
        for e in execucoes
    ]


@router.get("/automacoes/emails")
def emails_aos_clientes(db: Session = Depends(get_db), _: m.Usuario = Depends(admin)):
    """Aba Automações (decisão 127): os e-mails automáticos aos clientes (ligado, modo, fila e envios de hoje), as
    rotinas internas que rodam junto e os últimos e-mails que saíram. Só lê."""
    return emails_clientes.painel(db)


@router.get("/automacoes/execucoes")
def execucoes(db: Session = Depends(get_db), _: m.Usuario = Depends(admin)):
    return [
        {
            "id": e.id,
            "automacao": e.automacao,
            "status": e.status,
            "iniciadaEm": ms(e.iniciada_em),
            "terminadaEm": ms(e.terminada_em),
            "criados": e.criados,
            "atualizados": e.atualizados,
            "resolvidos": e.resolvidos,
            "detalhe": e.detalhe,
            "disparadaPor": e.disparada_por_id,
        }
        for e in alerta_repository.execucoes(db)
    ]
