"""Avisos ao cliente por e-mail, sem modelo de linguagem: são regras.

"Avise-me quando chegar" (decisão 99)
- Na página da peça esgotada, o cliente logado pede o aviso daquela cor e tamanho.
- Quando a peça volta a ter saldo livre no site (o mesmo "disponível" da página do produto), o cliente recebe um
  e-mail, uma vez por pedido de aviso. Peças que voltam juntas vão no mesmo e-mail.
- Na hora: entrada de estoque, transferência recebida, devolução ou pedido cancelado marcam a peça como liberada,
  e a conferência roda em segundo plano depois que a transação é confirmada. A automação aviso_estoque confere
  tudo de novo (pega o que tiver escapado, como uma falha do Resend).

Lembrete de sacola abandonada (decisão 100)
- O site guarda uma cópia da sacola de quem está logado (tabela sacolas).
- Sacola parada há SACOLA_LEMBRETE_HORAS hora (decisão 129), e não mais que SACOLA_LEMBRETE_MAX_DIAS dias, recebe um lembrete,
  só se o cliente aceita e-mails de marketing, não comprou depois e ainda há peças disponíveis. No máximo um
  lembrete por mudança da sacola e um a cada SACOLA_LEMBRETE_INTERVALO_DIAS dias.

Os dois seguem o aviso de pontos (decisão 82): desligados por padrão (AVISO_ESTOQUE_ENVIAR, LEMBRETE_SACOLA_ENVIAR),
modo teste para o e-mail do time (AVISOS_TESTE_PARA, até AVISOS_TESTE_POR_DIA por dia), limite diário, e o aviso
só é gravado depois que o e-mail saiu. Cada cliente é processado com a linha travada (FOR UPDATE SKIP LOCKED):
duas execuções ao mesmo tempo não mandam o mesmo e-mail duas vezes.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session

from src import models as m
from src.config import settings
from src.database.connection import SessionLocal
from src.entities import fidelidade as regra_pontos
from src.entities.cliente import email_valido, recebe_email_real
from src.integrations import email as envio
from src.integrations import modelos_email
from src.use_cases.assistente.catalogo import caminho_do_produto
from src.utils.datas import agora, hoje, inicio_do_dia
from src.utils.erros import Conflito, DadosInvalidos, NaoEncontrado

log = logging.getLogger("casalorenzi.avisos")

PAUSA_ENTRE_ENVIOS = 0.6
# Pedidos de aviso pendentes por cliente
AVISOS_ESTOQUE_POR_CLIENTE = 30
# Sacola: o que o site aceita (o mesmo limite do navegador)
SACOLA_MAX_ITENS = 30
SACOLA_MAX_POR_ITEM = 5
# Decisão 128: 1 hora parada já é sacola abandonada (antes, 24 horas)
SACOLA_LEMBRETE_HORAS = 1
SACOLA_LEMBRETE_MAX_DIAS = 7
SACOLA_LEMBRETE_INTERVALO_DIAS = 7

# Peças liberadas na transação atual (session.info), conferidas depois do commit
CHAVE_LIBERADAS = "avisos_estoque_liberadas"


@dataclass
class Resultado:
    ligado: bool
    modo: str | None = None
    enviados: int = 0
    falhas: int = 0
    adiados: int = 0
    detalhe: list[str] = field(default_factory=list)


def _modo() -> str:
    return "TESTE" if settings.AVISOS_TESTE_PARA else "REAL"


def _para_o_teste(email: envio.Email) -> envio.Email:
    if not settings.AVISOS_TESTE_PARA:
        return email
    assunto = f"[Teste · para {email.para}] {email.assunto}"
    return envio.Email(para=settings.AVISOS_TESTE_PARA, assunto=assunto, texto=email.texto, html=email.html)


def _enviar_de_verdade(email: envio.Email) -> None:
    """Espera a resposta do Resend (o aviso só é gravado se saiu). Sem RESEND_API_KEY, vai para o log."""
    if not envio.RESEND_API_KEY:
        log.info("Aviso ao cliente (sem RESEND_API_KEY, não enviado) para %s · %s\n%s", email.para, email.assunto, email.texto)
        return
    envio.enviar_agora(email)


def _teto(limite_real: int) -> int:
    return regra_pontos.AVISOS_TESTE_POR_DIA if settings.AVISOS_TESTE_PARA else limite_real


def disponiveis_no_site(db: Session, variacao_ids: Iterable[int]) -> dict[int, int]:
    """O mesmo "disponível" da página do produto, só de peças que estão à venda no site."""
    # Import aqui: pedidos importa este módulo (para marcar as peças liberadas no cancelamento)
    from src.use_cases.pedidos import disponiveis_na_rede

    ids = list(set(variacao_ids))
    if not ids:
        return {}
    a_venda = set(
        db.scalars(
            select(m.Variacao.id)
            .join(m.Variacao.produto)
            .where(m.Variacao.id.in_(ids), m.Produto.ativo.is_(True), m.Produto.removido_em.is_(None))
        )
    )
    return {v: q for v, q in disponiveis_na_rede(db, list(a_venda)).items() if q > 0}


def _pecas(db: Session, quantidades: dict[int, int]) -> list[modelos_email.PecaEmail]:
    variacoes = db.scalars(select(m.Variacao).where(m.Variacao.id.in_(quantidades)).order_by(m.Variacao.id))
    return [
        modelos_email.PecaEmail(
            nome=v.produto.nome,
            cor=v.cor,
            tamanho=v.tamanho,
            preco=Decimal(v.produto.preco_base),
            caminho=caminho_do_produto(v.produto),
            quantidade=quantidades[v.id],
        )
        for v in variacoes
    ]


def _cliente_recebe(cliente: m.Cliente | None) -> bool:
    """No modo real, só quem criou a conta no site (decisão 128); no modo teste tudo vai para o e-mail do time."""
    if cliente is None or cliente.excluido_em is not None or not email_valido(cliente.email):
        return False
    return _modo() == "TESTE" or recebe_email_real(cliente)


# ---------- "Avise-me quando chegar" ----------


def pendentes_do_cliente(db: Session, cliente_id: int) -> list[int]:
    consulta = select(m.AvisoEstoque.variacao_id).where(
        m.AvisoEstoque.cliente_id == cliente_id, m.AvisoEstoque.avisado_em.is_(None)
    )
    return sorted(db.scalars(consulta))


def pedir_aviso(db: Session, cliente_id: int, variacao_id: int) -> None:
    """Pedir de novo a mesma peça não duplica. Peça disponível agora: 409 (pode comprar)."""
    variacao = db.get(m.Variacao, variacao_id)
    if variacao is None or not variacao.produto.ativo or variacao.produto.removido_em is not None:
        raise NaoEncontrado("Peça não encontrada.")
    if disponiveis_no_site(db, [variacao_id]):
        raise Conflito("Esta peça está disponível: você já pode colocá-la na sacola.")
    pendentes = pendentes_do_cliente(db, cliente_id)
    if variacao_id in pendentes:
        return
    if len(pendentes) >= AVISOS_ESTOQUE_POR_CLIENTE:
        raise DadosInvalidos(f"Você já tem {AVISOS_ESTOQUE_POR_CLIENTE} avisos pedidos. Cancele algum para pedir outro.")
    db.add(m.AvisoEstoque(cliente_id=cliente_id, variacao_id=variacao_id, criado_em=agora()))
    db.commit()


def cancelar_aviso(db: Session, cliente_id: int, variacao_id: int) -> None:
    db.execute(
        delete(m.AvisoEstoque).where(
            m.AvisoEstoque.cliente_id == cliente_id,
            m.AvisoEstoque.variacao_id == variacao_id,
            m.AvisoEstoque.avisado_em.is_(None),
        )
    )
    db.commit()


def marcar_liberadas(db: Session, variacao_ids: Iterable[int]) -> None:
    """Chamado por quem aumenta o saldo livre de uma peça (antes do commit). A conferência roda depois do commit."""
    db.info.setdefault(CHAVE_LIBERADAS, set()).update(variacao_ids)


_fila = ThreadPoolExecutor(max_workers=1, thread_name_prefix="avisos-estoque")


@event.listens_for(Session, "after_commit")
def _depois_do_commit(session: Session) -> None:
    liberadas = session.info.pop(CHAVE_LIBERADAS, None)
    if liberadas and settings.AVISO_ESTOQUE_ENVIAR:
        _fila.submit(_conferir_em_segundo_plano, sorted(liberadas))


@event.listens_for(Session, "after_rollback")
def _depois_do_rollback(session: Session) -> None:
    session.info.pop(CHAVE_LIBERADAS, None)


def _conferir_em_segundo_plano(variacao_ids: list[int]) -> None:
    try:
        with SessionLocal() as db:
            resultado = enviar_avisos_estoque(db, variacao_ids=variacao_ids)
        if resultado.enviados or resultado.falhas:
            log.info("Avise-me: %s", "; ".join(resultado.detalhe))
    except Exception:
        log.exception("Falha ao conferir os avisos de estoque")


def _pedidos_com_peca_de_volta(db: Session, variacao_ids: list[int] | None = None) -> dict[int, list[int]]:
    """Pedidos de aviso ainda não atendidos cuja peça está disponível no site, por cliente (os mais antigos primeiro).
    variacao_ids: só essas peças."""
    consulta = select(m.AvisoEstoque.cliente_id, m.AvisoEstoque.variacao_id).where(m.AvisoEstoque.avisado_em.is_(None))
    if variacao_ids is not None:
        consulta = consulta.where(m.AvisoEstoque.variacao_id.in_(variacao_ids))
    pedidos = db.execute(consulta.order_by(m.AvisoEstoque.criado_em)).all()
    disponiveis = disponiveis_no_site(db, (v for _, v in pedidos))
    por_cliente: dict[int, list[int]] = defaultdict(list)
    for cliente_id, variacao_id in pedidos:
        if variacao_id in disponiveis:
            por_cliente[cliente_id].append(variacao_id)
    return por_cliente


def _avisados_hoje(db: Session, modo: str) -> int:
    consulta = select(func.count(func.distinct(m.AvisoEstoque.cliente_id))).where(
        m.AvisoEstoque.modo == modo, m.AvisoEstoque.avisado_em >= inicio_do_dia(hoje())
    )
    return int(db.scalar(consulta) or 0)


def enviar_avisos_estoque(
    db: Session, *, variacao_ids: list[int] | None = None, enviar: Callable[[envio.Email], None] | None = None
) -> Resultado:
    """Avisa quem pediu e cuja peça está disponível. variacao_ids: só essas peças (conferência na hora)."""
    if not settings.AVISO_ESTOQUE_ENVIAR:
        return Resultado(ligado=False, detalhe=["envio desligado (AVISO_ESTOQUE_ENVIAR)"])
    enviar = enviar or _enviar_de_verdade
    modo = _modo()
    por_cliente = _pedidos_com_peca_de_volta(db, variacao_ids)
    vagas = max(_teto(settings.AVISO_ESTOQUE_LIMITE_DIA) - _avisados_hoje(db, modo), 0)
    resultado = Resultado(ligado=True, modo=modo, adiados=max(len(por_cliente) - vagas, 0))
    for indice, (cliente_id, variacoes) in enumerate(list(por_cliente.items())[:vagas]):
        if indice:
            time.sleep(PAUSA_ENTRE_ENVIOS)
        resultado.enviados += _avisar_cliente(cliente_id, variacoes, modo, enviar, resultado)
    resultado.detalhe.append(
        f"modo {modo}: {resultado.enviados} cliente(s) avisado(s)"
        + (f", {resultado.falhas} falha(s)" if resultado.falhas else "")
        + (f", {resultado.adiados} para os próximos dias (limite diário)" if resultado.adiados else "")
    )
    return resultado


def _avisar_cliente(cliente_id: int, variacoes: list[int], modo: str, enviar, resultado: Resultado) -> int:
    """Numa transação própria, com os pedidos do cliente travados: manda e grava, ou não grava nada."""
    with SessionLocal() as db:
        avisos = db.scalars(
            select(m.AvisoEstoque)
            .where(
                m.AvisoEstoque.cliente_id == cliente_id,
                m.AvisoEstoque.variacao_id.in_(variacoes),
                m.AvisoEstoque.avisado_em.is_(None),
            )
            .with_for_update(skip_locked=True)
        ).all()
        cliente = db.get(m.Cliente, cliente_id)
        if not avisos or not _cliente_recebe(cliente):
            db.rollback()
            return 0
        email = _para_o_teste(
            modelos_email.peca_disponivel(cliente.email, cliente.nome, _pecas(db, {a.variacao_id: 1 for a in avisos}))
        )
        try:
            enviar(email)
        except Exception:
            db.rollback()
            resultado.falhas += 1
            log.exception("Falha ao avisar o cliente %s de peça disponível", cliente_id)
            return 0
        momento = agora()
        for aviso in avisos:
            aviso.avisado_em, aviso.modo, aviso.email = momento, modo, email.para
        db.commit()
        return 1


# ---------- Sacola ----------


def salvar_sacola(db: Session, cliente_id: int, itens: list[tuple[int, int]]) -> None:
    """Guarda a cópia da sacola. Vazia apaga. Peças que não existem são ignoradas."""
    if len(itens) > SACOLA_MAX_ITENS:
        raise DadosInvalidos(f"A sacola aceita até {SACOLA_MAX_ITENS} peças diferentes.")
    existentes = set(db.scalars(select(m.Variacao.id).where(m.Variacao.id.in_([v for v, _ in itens])))) if itens else set()
    limpos: dict[int, int] = {}
    for variacao_id, quantidade in itens:
        if variacao_id in existentes:
            limpos[variacao_id] = min(max(quantidade, 1), SACOLA_MAX_POR_ITEM)
    novos = [{"variacaoId": v, "quantidade": q} for v, q in sorted(limpos.items())]
    sacola = db.get(m.Sacola, cliente_id, with_for_update=True)
    if not novos:
        if sacola is not None:
            db.delete(sacola)
    elif sacola is None:
        db.add(m.Sacola(cliente_id=cliente_id, itens=novos, atualizada_em=agora()))
    elif sacola.itens != novos:
        sacola.itens, sacola.atualizada_em = novos, agora()
    db.commit()


def sacola_do_cliente(db: Session, cliente_id: int) -> list[dict]:
    """Os itens no formato da sacola do site (para abrir a sacola em outro aparelho). Só peças à venda."""
    sacola = db.get(m.Sacola, cliente_id)
    if sacola is None:
        return []
    quantidades = {i["variacaoId"]: i["quantidade"] for i in sacola.itens}
    from src.schemas.produtos import imagem_url

    variacoes = db.scalars(
        select(m.Variacao)
        .join(m.Variacao.produto)
        .where(m.Variacao.id.in_(quantidades), m.Produto.ativo.is_(True), m.Produto.removido_em.is_(None))
        .order_by(m.Variacao.id)
    )
    return [
        {
            "variacaoId": v.id,
            "produtoId": v.produto.id,
            "nome": v.produto.nome,
            "cor": v.cor,
            "tamanho": v.tamanho,
            "sku": v.sku,
            "preco": float(v.produto.preco_base),
            "imagemUrl": imagem_url(v.produto),
            "marca": v.produto.marca,
            "codigoModelo": v.produto.codigo_modelo,
            "quantidade": quantidades[v.id],
        }
        for v in variacoes
    ]


def _lembretes_hoje(db: Session, modo: str) -> int:
    consulta = select(func.count()).where(m.Sacola.lembrete_modo == modo, m.Sacola.lembrete_em >= inicio_do_dia(hoje()))
    return int(db.scalar(consulta) or 0)


def _sacolas_paradas(db: Session) -> list[int]:
    momento = agora()
    consulta = (
        select(m.Sacola.cliente_id)
        .join(m.Cliente, m.Cliente.id == m.Sacola.cliente_id)
        .where(
            m.Sacola.atualizada_em <= momento - timedelta(hours=SACOLA_LEMBRETE_HORAS),
            m.Sacola.atualizada_em >= momento - timedelta(days=SACOLA_LEMBRETE_MAX_DIAS),
            m.Cliente.aceita_marketing.is_(True),
            m.Cliente.excluido_em.is_(None),
        )
        .order_by(m.Sacola.atualizada_em)
    )
    return list(db.scalars(consulta))


def _pode_lembrar(sacola: m.Sacola) -> bool:
    if sacola.lembrete_em is None:
        return True
    intervalo = agora() - timedelta(days=SACOLA_LEMBRETE_INTERVALO_DIAS)
    return sacola.lembrete_em < sacola.atualizada_em and sacola.lembrete_em <= intervalo


def enviar_lembretes_sacola(db: Session, enviar: Callable[[envio.Email], None] | None = None) -> Resultado:
    if not settings.LEMBRETE_SACOLA_ENVIAR:
        return Resultado(ligado=False, detalhe=["envio desligado (LEMBRETE_SACOLA_ENVIAR)"])
    enviar = enviar or _enviar_de_verdade
    modo = _modo()
    candidatas = _sacolas_paradas(db)
    vagas = max(_teto(settings.LEMBRETE_SACOLA_LIMITE_DIA) - _lembretes_hoje(db, modo), 0)
    resultado = Resultado(ligado=True, modo=modo)
    for cliente_id in candidatas:
        if resultado.enviados >= vagas:
            resultado.adiados += 1
            continue
        if resultado.enviados:
            time.sleep(PAUSA_ENTRE_ENVIOS)
        resultado.enviados += _lembrar(cliente_id, modo, enviar, resultado)
    resultado.detalhe.append(
        f"modo {modo}: {resultado.enviados} lembrete(s) enviado(s)"
        + (f", {resultado.falhas} falha(s)" if resultado.falhas else "")
        + (f", {resultado.adiados} para os próximos dias (limite diário)" if resultado.adiados else "")
    )
    return resultado


def _pecas_do_lembrete(db: Session, sacola: m.Sacola | None, cliente: m.Cliente | None) -> dict[int, int]:
    """As peças (variação: quantidade) que entram no lembrete. Vazio quando a sacola não recebe lembrete agora: já
    lembrada, cliente sem e-mail válido ou sem consentimento, compra depois da sacola ou nenhuma peça disponível."""
    if sacola is None or not _pode_lembrar(sacola) or not _cliente_recebe(cliente) or not cliente.aceita_marketing:
        return {}
    # Comprou depois de mexer na sacola: não é sacola abandonada
    comprou = db.scalar(select(func.count()).where(m.Pedido.cliente_id == cliente.id, m.Pedido.criado_em >= sacola.atualizada_em))
    quantidades = {i["variacaoId"]: i["quantidade"] for i in sacola.itens}
    disponiveis = disponiveis_no_site(db, quantidades)
    if comprou or not disponiveis:
        return {}
    return {v: q for v, q in quantidades.items() if v in disponiveis}


def _lembrar(cliente_id: int, modo: str, enviar, resultado: Resultado) -> int:
    with SessionLocal() as db:
        sacola = db.get(m.Sacola, cliente_id, with_for_update={"skip_locked": True})
        cliente = db.get(m.Cliente, cliente_id)
        escolhidas = _pecas_do_lembrete(db, sacola, cliente)
        if not escolhidas:
            db.rollback()
            return 0
        pecas = _pecas(db, escolhidas)
        loja = "/vulto" if all(p.caminho.startswith("/vulto/") for p in pecas) else "/"
        email = _para_o_teste(modelos_email.lembrete_sacola(cliente.email, cliente.nome, pecas, loja))
        try:
            enviar(email)
        except Exception:
            db.rollback()
            resultado.falhas += 1
            log.exception("Falha ao mandar o lembrete de sacola do cliente %s", cliente_id)
            return 0
        sacola.lembrete_em, sacola.lembrete_modo = agora(), modo
        db.commit()
        return 1


# ---------- Situação para o painel (decisão 127) ----------


def situacao_avisos_estoque(db: Session) -> dict:
    """Avise-me na aba Automações: ligado ou não, o modo, o teto do dia, quantos clientes já receberam hoje e
    quantos têm peça de volta esperando o e-mail. Só lê: não manda nada."""
    modo = _modo()
    por_cliente = _pedidos_com_peca_de_volta(db)
    clientes = db.scalars(select(m.Cliente).where(m.Cliente.id.in_(por_cliente))) if por_cliente else []
    return {
        "ligado": settings.AVISO_ESTOQUE_ENVIAR,
        "modo": modo,
        "testePara": settings.AVISOS_TESTE_PARA or None,
        "limiteDia": _teto(settings.AVISO_ESTOQUE_LIMITE_DIA),
        "enviadosHoje": _avisados_hoje(db, modo),
        "naFila": sum(1 for cliente in clientes if _cliente_recebe(cliente)),
    }


def situacao_lembretes(db: Session) -> dict:
    """Lembrete de sacola na aba Automações, com as mesmas regras do envio para contar quem está na fila."""
    modo = _modo()
    na_fila = sum(
        1
        for cliente_id in _sacolas_paradas(db)
        if _pecas_do_lembrete(db, db.get(m.Sacola, cliente_id), db.get(m.Cliente, cliente_id))
    )
    return {
        "ligado": settings.LEMBRETE_SACOLA_ENVIAR,
        "modo": modo,
        "testePara": settings.AVISOS_TESTE_PARA or None,
        "limiteDia": _teto(settings.LEMBRETE_SACOLA_LIMITE_DIA),
        "enviadosHoje": _lembretes_hoje(db, modo),
        "naFila": na_fila,
    }


# ---------- Conta excluída ----------


def apagar_do_cliente(db: Session, cliente_id: int) -> None:
    """Exclusão da conta: os pedidos de aviso e a sacola guardada saem junto (sem confirmar)."""
    db.execute(delete(m.AvisoEstoque).where(m.AvisoEstoque.cliente_id == cliente_id))
    db.execute(delete(m.Sacola).where(m.Sacola.cliente_id == cliente_id))
