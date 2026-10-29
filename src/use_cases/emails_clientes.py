"""Aba Automações do Assistente IA (decisão 127): os e-mails automáticos aos clientes.

Para cada envio (aviso de pontos a vencer, lembrete de sacola e Avise-me), o painel mostra se está ligado, o modo
(TESTE: tudo vai para o e-mail do time, com o cliente no assunto; REAL: para o cliente), quantos clientes já
receberam hoje e quantos esperam agora, e a lista dos últimos e-mails que saíram, lida dos registros que cada
envio já grava (avisos_pontos, avisos_estoque e sacolas).

O botão do painel roda todas as automações (POST /automacoes/todas/executar). Os e-mails saem e, junto, rodam as
rotinas internas, que continuam alimentando o Assistente IA (alertas), a retenção das conversas e o WhatsApp.
Só lê: nada aqui manda e-mail.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src import models as m
from src.integrations import email as envio
from src.use_cases import automacoes, avisos_cliente, avisos_pontos
from src.use_cases.assistente.formatacao import numero
from src.utils.datas import ms

# Os envios aos clientes, na ordem da tela, com a variável que liga cada um no servidor
EMAILS = {
    "aviso_pontos": "AVISO_PONTOS_ENVIAR",
    "lembrete_sacola": "LEMBRETE_SACOLA_ENVIAR",
    "aviso_estoque": "AVISO_ESTOQUE_ENVIAR",
}
ULTIMOS_ENVIOS = 30


def painel(db: Session) -> dict:
    situacoes = {s["nome"]: s for s in automacoes.situacao(db)}
    envios = {
        "aviso_pontos": avisos_pontos.situacao(db),
        "lembrete_sacola": avisos_cliente.situacao_lembretes(db),
        "aviso_estoque": avisos_cliente.situacao_avisos_estoque(db),
    }
    return {
        # Sem a chave do Resend, o e-mail vai só para o log da API (ambiente local)
        "resend": bool(envio.RESEND_API_KEY),
        "emails": [
            {"nome": nome, "chave": chave, **envios[nome], "ultima": situacoes[nome]["ultima"]} for nome, chave in EMAILS.items()
        ],
        "rotinas": [s for nome, s in situacoes.items() if nome not in EMAILS],
        "envios": ultimos_envios(db),
    }


def ultimos_envios(db: Session, limite: int = ULTIMOS_ENVIOS) -> list[dict]:
    """Os últimos e-mails que saíram, um por linha. Um aviso de pontos ou de peça de volta pode cobrir mais de um
    vencimento ou peça: as linhas gravadas no mesmo instante para o mesmo cliente são um e-mail só."""
    pontos = db.execute(
        select(
            m.AvisoPontos.cliente_id,
            m.AvisoPontos.enviado_em,
            m.AvisoPontos.modo,
            m.AvisoPontos.email,
            func.sum(m.AvisoPontos.pontos),
            func.bool_or(m.AvisoPontos.sem_numeros),
        )
        .group_by(m.AvisoPontos.cliente_id, m.AvisoPontos.enviado_em, m.AvisoPontos.modo, m.AvisoPontos.email)
        .order_by(m.AvisoPontos.enviado_em.desc())
        .limit(limite)
    ).all()
    pecas = db.execute(
        select(m.AvisoEstoque.cliente_id, m.AvisoEstoque.avisado_em, m.AvisoEstoque.modo, m.AvisoEstoque.email, func.count())
        .where(m.AvisoEstoque.avisado_em.is_not(None))
        .group_by(m.AvisoEstoque.cliente_id, m.AvisoEstoque.avisado_em, m.AvisoEstoque.modo, m.AvisoEstoque.email)
        .order_by(m.AvisoEstoque.avisado_em.desc())
        .limit(limite)
    ).all()
    # A sacola guarda só o último lembrete, sem o endereço: no modo REAL é o e-mail do cliente
    sacolas = db.execute(
        select(m.Sacola.cliente_id, m.Sacola.lembrete_em, m.Sacola.lembrete_modo)
        .where(m.Sacola.lembrete_em.is_not(None))
        .order_by(m.Sacola.lembrete_em.desc())
        .limit(limite)
    ).all()

    linhas = (
        [
            {
                "tipo": "aviso_pontos",
                "clienteId": cliente_id,
                "em": em,
                "modo": modo,
                "para": para,
                "resumo": "Sem o saldo (e-mail de mais de uma conta)" if sem_numeros else f"{numero(total)} pontos vencendo",
            }
            for cliente_id, em, modo, para, total, sem_numeros in pontos
        ]
        + [
            {
                "tipo": "aviso_estoque",
                "clienteId": cliente_id,
                "em": em,
                "modo": modo,
                "para": para,
                "resumo": "1 peça de volta" if total == 1 else f"{numero(total)} peças de volta",
            }
            for cliente_id, em, modo, para, total in pecas
        ]
        + [
            {
                "tipo": "lembrete_sacola",
                "clienteId": cliente_id,
                "em": em,
                "modo": modo,
                "para": None,
                "resumo": "Peças paradas na sacola",
            }
            for cliente_id, em, modo in sacolas
        ]
    )
    linhas = sorted(linhas, key=lambda linha: linha["em"], reverse=True)[:limite]

    ids = {linha["clienteId"] for linha in linhas}
    clientes = {c.id: c for c in db.scalars(select(m.Cliente).where(m.Cliente.id.in_(ids)))} if ids else {}
    saida = []
    for linha in linhas:
        cliente = clientes.get(linha["clienteId"])
        ativo = cliente is not None and cliente.excluido_em is None
        para = linha["para"]
        if linha["tipo"] == "lembrete_sacola" and linha["modo"] == "REAL" and ativo:
            para = cliente.email
        saida.append(
            {
                "tipo": linha["tipo"],
                "cliente": cliente.nome if ativo else None,
                "para": para,
                "modo": linha["modo"],
                "resumo": linha["resumo"],
                "enviadoEm": ms(linha["em"]),
            }
        )
    return saida
