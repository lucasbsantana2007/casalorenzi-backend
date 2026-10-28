"""Automações operacionais: transformam as análises em alertas para a equipe agir, sem modelo de linguagem.

- estoque_baixo: item no mínimo ou zerado que vendeu no local na janela (ALERTA_ESTOQUE_BAIXO_JANELA_DIAS);
- estoque_parado: por loja, os itens com saldo e sem venda há ALERTA_ESTOQUE_PARADO_DIAS dias ou mais;
- sugestoes_transferencia: sobra num local, falta com demanda em outro da mesma marca (só sugestão);
- pontos_a_vencer: pontos Lupe+ que vencem em ALERTA_PONTOS_DIAS dias (números agregados, para a equipe);
- aviso_pontos: e-mail a cada cliente 30 dias antes de os pontos vencerem (decisão 82; use_cases/avisos_pontos.py).
  Desligado por padrão (AVISO_PONTOS_ENVIAR). Aqui "criados" é o número de avisos enviados;
- aviso_estoque: e-mail a quem pediu "Avise-me quando chegar" e a peça voltou (decisão 99; use_cases/avisos_cliente.py);
- lembrete_sacola: lembrete de sacola abandonada, só para quem aceita marketing (decisão 100). Os dois desligados
  por padrão (AVISO_ESTOQUE_ENVIAR, LEMBRETE_SACOLA_ENVIAR); "criados" é o número de e-mails enviados;
- limpeza_conversas: apaga as conversas dos assistentes sem atividade além da retenção (IA_RETENCAO_DIAS).

Garantias: uma execução por vez de cada automação (trava do Postgres, vale entre servidores); a mesma situação
nunca tem dois alertas abertos (índice único) e não é recriada logo depois de descartada; situação que acabou
tem o alerta resolvido sozinho; cada execução fica no log (execucoes_automacao), com o erro resumido se falhar.
Rodam pela linha de comando (python -m src.automacoes, para um agendador) ou pelo painel (Administrador).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m
from src.config import settings
from src.database.connection import SessionLocal
from src.entities import assistente as regra
from src.repositories import alerta_repository
from src.use_cases import analises, avisos_cliente, avisos_pontos
from src.use_cases.assistente import conversas
from src.use_cases.assistente.formatacao import brl, cru, numero
from src.utils.datas import agora, ms
from src.utils.erros import DadosInvalidos

log = logging.getLogger("casalorenzi.automacoes")

# Descartado pela equipe: a mesma situação só volta a virar alerta depois disso
SILENCIO_DESCARTADO_DIAS = 7


@dataclass
class Desejado:
    chave: str
    titulo: str
    descricao: str
    dados: dict
    severidade: str = "MEDIA"
    marca: str | None = None
    loja_id: int | None = None
    variacao_id: int | None = None


@dataclass
class Placar:
    criados: int = 0
    atualizados: int = 0
    resolvidos: int = 0
    detalhe: list[str] = field(default_factory=list)


def _descartados_recentes(db: Session, tipo: str) -> set[str]:
    desde = agora() - timedelta(days=SILENCIO_DESCARTADO_DIAS)
    consulta = select(m.Alerta.chave).where(
        m.Alerta.tipo == tipo, m.Alerta.status == regra.DESCARTADO, m.Alerta.resolvido_em >= desde
    )
    return set(db.scalars(consulta))


def sincronizar(db: Session, tipo: str, desejados: list[Desejado]) -> Placar:
    """Deixa os alertas abertos do tipo iguais à situação atual: cria os novos, atualiza os que continuam e
    resolve os que acabaram. Rodar duas vezes seguidas não muda nada na segunda (idempotente)."""
    placar = Placar()
    momento = agora()
    abertos = alerta_repository.abertos_do_tipo(db, tipo)
    silenciados = _descartados_recentes(db, tipo)
    vistos = set()
    for d in desejados:
        if d.chave in vistos:
            continue
        vistos.add(d.chave)
        alerta = abertos.get(d.chave)
        if alerta is None:
            if d.chave in silenciados:
                continue
            db.add(
                m.Alerta(
                    tipo=tipo,
                    chave=d.chave,
                    marca=d.marca,
                    loja_id=d.loja_id,
                    variacao_id=d.variacao_id,
                    titulo=d.titulo[:200],
                    descricao=d.descricao,
                    dados=cru(d.dados),
                    severidade=d.severidade,
                    status=regra.ABERTO,
                    criado_em=momento,
                    atualizado_em=momento,
                )
            )
            placar.criados += 1
        else:
            alerta.titulo, alerta.descricao, alerta.dados = d.titulo[:200], d.descricao, cru(d.dados)
            alerta.severidade, alerta.atualizado_em = d.severidade, momento
            placar.atualizados += 1
    for chave, alerta in abertos.items():
        if chave not in vistos:
            alerta.status = regra.RESOLVIDO
            alerta.resolvido_em = momento
            alerta.atualizado_em = momento
            placar.resolvidos += 1
    return placar


# ---------- As automações ----------


def _estoque_baixo(db: Session) -> Placar:
    janela = settings.ALERTA_ESTOQUE_BAIXO_JANELA_DIAS
    itens = analises.estoque_baixo(db, marca=None, somente_com_demanda=True, janela_dias=janela, limite=100_000)["itens"]
    desejados = [
        Desejado(
            chave=f"{regra.ALERTA_ESTOQUE_BAIXO}:{i['lojaId']}:{i['variacaoId']}",
            titulo=f"{'Sem estoque' if i['status'] == 'SEM_ESTOQUE' else 'Estoque baixo'}: {i['produto']} ({i['cor']}, {i['tamanho']}) na {i['loja']}",
            descricao=(
                f"Saldo {i['quantidade']} (mínimo {i['minimo']}), {i['livre']} livre para venda; "
                f"vendeu {i['vendasJanela']} peça(s) neste local nos últimos {janela} dias."
            ),
            dados={
                k: i[k]
                for k in (
                    "produtoId",
                    "produto",
                    "sku",
                    "cor",
                    "tamanho",
                    "loja",
                    "quantidade",
                    "minimo",
                    "livre",
                    "vendasJanela",
                    "status",
                )
            },
            severidade="ALTA" if i["status"] == "SEM_ESTOQUE" else "MEDIA",
            marca=i["marca"],
            loja_id=i["lojaId"],
            variacao_id=i["variacaoId"],
        )
        for i in itens
    ]
    placar = sincronizar(db, regra.ALERTA_ESTOQUE_BAIXO, desejados)
    placar.detalhe.append(f"{len(desejados)} itens no mínimo ou zerados com venda nos últimos {janela} dias")
    return placar


def _estoque_parado(db: Session) -> Placar:
    dias = settings.ALERTA_ESTOQUE_PARADO_DIAS
    r = analises.estoque_parado(db, marca=None, dias=dias, limite=100_000)
    desejados = []
    for loja in r["porLoja"]:
        maiores = [i for i in r["itens"] if i["lojaId"] == loja["lojaId"]][:10]
        desejados.append(
            Desejado(
                chave=f"{regra.ALERTA_ESTOQUE_PARADO}:{loja['lojaId']}",
                titulo=f"{loja['loja']}: {numero(loja['itens'])} itens sem venda há {dias} dias ou mais",
                descricao=f"{numero(loja['pecas'])} peças paradas, {brl(loja['valor'])} a preço de venda. Candidatas a ação comercial ou transferência.",
                dados={
                    "dias": dias,
                    "itens": loja["itens"],
                    "pecas": loja["pecas"],
                    "valor": loja["valor"],
                    "maiores": [
                        {k: i[k] for k in ("produto", "sku", "quantidade", "diasSemVenda", "valor", "nuncaVendeuNoLocal")}
                        for i in maiores
                    ],
                },
                severidade="ALTA" if loja["itens"] >= 100 else ("MEDIA" if loja["itens"] >= 10 else "BAIXA"),
                marca=loja["marca"],
                loja_id=loja["lojaId"],
            )
        )
    placar = sincronizar(db, regra.ALERTA_ESTOQUE_PARADO, desejados)
    placar.detalhe.append(f"{numero(r['total'])} itens parados em {len(desejados)} locais")
    return placar


def _sugestoes_transferencia(db: Session) -> Placar:
    sugestoes = analises.sugestoes_transferencia(db, marca=None, janela_dias=settings.ALERTA_ESTOQUE_BAIXO_JANELA_DIAS, limite=30)
    desejados = [
        Desejado(
            chave=f"{regra.ALERTA_TRANSFERENCIA}:{s['variacaoId']}:{s['origemId']}:{s['destinoId']}",
            titulo=f"Sugestão: {s['quantidade']} un. de {s['produto']} ({s['sku']}) de {s['origem']} para {s['destino']}",
            descricao=(
                f"{s['destino']} tem {s['livreDestino']} livre (mínimo {s['minimoDestino']}) e vendeu {s['vendasDestino']} nos últimos "
                f"{settings.ALERTA_ESTOQUE_BAIXO_JANELA_DIAS} dias; {s['origem']} tem {s['saldoOrigem']} em estoque. Para análise: nada foi transferido."
            ),
            dados=s,
            marca=s["marca"],
            loja_id=s["destinoId"],
            variacao_id=s["variacaoId"],
        )
        for s in sugestoes
    ]
    placar = sincronizar(db, regra.ALERTA_TRANSFERENCIA, desejados)
    placar.detalhe.append(f"{len(desejados)} sugestões de transferência")
    return placar


def _pontos_a_vencer(db: Session) -> Placar:
    dias = settings.ALERTA_PONTOS_DIAS
    r = analises.fidelidade(db, dias_a_vencer=dias, com_ids=True)
    desejados = []
    if r["clientesAVencer"]:
        ids = r["idsAVencer"]
        aceitam = 0
        for inicio in range(0, len(ids), 1000):
            lote = ids[inicio : inicio + 1000]
            aceitam += len(
                list(
                    db.scalars(
                        select(m.Cliente.id).where(
                            m.Cliente.id.in_(lote), m.Cliente.aceita_marketing.is_(True), m.Cliente.excluido_em.is_(None)
                        )
                    )
                )
            )
        desejados.append(
            Desejado(
                chave=f"{regra.ALERTA_PONTOS}:{dias}d",
                titulo=f"{numero(r['clientesAVencer'])} clientes têm {numero(r['pontosAVencer'])} pontos Lupe+ vencendo em {dias} dias",
                descricao=(
                    f"{brl(r['valorAVencer'])} em desconto vencem até {(r['referencia'] + timedelta(days=dias)):%d/%m/%Y}. "
                    f"{numero(aceitam)} desses clientes aceitam receber mensagens de marketing. "
                    + (
                        "Cada cliente com e-mail válido recebe um aviso 30 dias antes do vencimento (automação aviso_pontos)."
                        if settings.AVISO_PONTOS_ENVIAR
                        else "O aviso por e-mail aos clientes está desligado (AVISO_PONTOS_ENVIAR)."
                    )
                ),
                dados={
                    "dias": dias,
                    "clientes": r["clientesAVencer"],
                    "pontos": r["pontosAVencer"],
                    "valor": r["valorAVencer"],
                    "aceitamContato": aceitam,
                    "porCategoria": r["clientesAVencerPorCategoria"],
                },
                severidade="ALTA" if r["valorAVencer"] >= 10000 else "MEDIA",
            )
        )
    placar = sincronizar(db, regra.ALERTA_PONTOS, desejados)
    placar.detalhe.append(f"{numero(r['clientesAVencer'])} clientes com pontos vencendo em {dias} dias")
    return placar


def _aviso_pontos(db: Session) -> Placar:
    resultado = avisos_pontos.enviar_pendentes(db)
    return Placar(criados=resultado.enviados, detalhe=resultado.detalhe)


def _aviso_estoque(db: Session) -> Placar:
    resultado = avisos_cliente.enviar_avisos_estoque(db)
    return Placar(criados=resultado.enviados, detalhe=resultado.detalhe)


def _lembrete_sacola(db: Session) -> Placar:
    resultado = avisos_cliente.enviar_lembretes_sacola(db)
    return Placar(criados=resultado.enviados, detalhe=resultado.detalhe)


def _limpeza(db: Session) -> Placar:
    apagadas = conversas.apagar_vencidas(db)
    return Placar(resolvidos=0, detalhe=[f"{apagadas} conversa(s) apagada(s) pela retenção de {settings.IA_RETENCAO_DIAS} dias"])


AUTOMACOES: dict[str, Callable[[Session], Placar]] = {
    "estoque_baixo": _estoque_baixo,
    "estoque_parado": _estoque_parado,
    "sugestoes_transferencia": _sugestoes_transferencia,
    "pontos_a_vencer": _pontos_a_vencer,
    "aviso_pontos": _aviso_pontos,
    "aviso_estoque": _aviso_estoque,
    "lembrete_sacola": _lembrete_sacola,
    "limpeza_conversas": _limpeza,
}
DESCRICOES = {
    "estoque_baixo": "Itens no mínimo ou zerados que venderam no local na janela",
    "estoque_parado": "Por loja, itens com saldo e sem venda há muitos dias",
    "sugestoes_transferencia": "Sobra num local e falta com demanda em outro (só sugestão)",
    "pontos_a_vencer": "Pontos Lupe+ que vencem em breve (números agregados)",
    "aviso_pontos": "E-mail aos clientes 30 dias antes de os pontos vencerem (desligado por padrão)",
    "aviso_estoque": "E-mail a quem pediu \"Avise-me\" quando a peça volta ao estoque (desligado por padrão)",
    "lembrete_sacola": "Lembrete de sacola parada há 24 h, para quem aceita e-mails (desligado por padrão)",
    "limpeza_conversas": "Apaga conversas dos assistentes além da retenção",
}


def _registrar(
    status: str, nome: str, inicio, usuario_id: int | None, detalhe: str, placar: Placar | None = None
) -> m.ExecucaoAutomacao:
    with SessionLocal() as db:
        execucao = m.ExecucaoAutomacao(
            automacao=nome,
            status=status,
            iniciada_em=inicio,
            terminada_em=agora(),
            criados=placar.criados if placar else 0,
            atualizados=placar.atualizados if placar else 0,
            resolvidos=placar.resolvidos if placar else 0,
            detalhe=detalhe[:500],
            disparada_por_id=usuario_id,
        )
        db.add(execucao)
        db.commit()
        db.refresh(execucao)
        return execucao


def executar(nome: str, *, usuario_id: int | None = None, forcar: bool = False) -> m.ExecucaoAutomacao:
    """Roda a automação numa transação só. Outra execução dela em andamento (ou terminada há menos de
    INTERVALO_MINIMO_SEGUNDOS, sem forcar) deixa esta como IGNORADA."""
    if nome not in AUTOMACOES:
        raise DadosInvalidos("Automação desconhecida.")
    inicio = agora()
    with SessionLocal() as db:
        if not alerta_repository.travar_automacao(db, nome):
            db.rollback()
            return _registrar("IGNORADA", nome, inicio, usuario_id, "Outra execução desta automação estava em andamento.")
        recente = inicio - timedelta(seconds=regra.INTERVALO_MINIMO_SEGUNDOS)
        if not forcar and alerta_repository.terminada_desde(db, nome, recente):
            db.rollback()
            return _registrar("IGNORADA", nome, inicio, usuario_id, "Rodou há menos de um minuto.")
        try:
            placar = AUTOMACOES[nome](db)
            execucao = m.ExecucaoAutomacao(
                automacao=nome,
                status="SUCESSO",
                iniciada_em=inicio,
                terminada_em=agora(),
                criados=placar.criados,
                atualizados=placar.atualizados,
                resolvidos=placar.resolvidos,
                detalhe="; ".join(placar.detalhe)[:500],
                disparada_por_id=usuario_id,
            )
            db.add(execucao)
            db.commit()
            db.refresh(execucao)
            log.info(
                "Automação %s: %s criados, %s atualizados, %s resolvidos",
                nome,
                placar.criados,
                placar.atualizados,
                placar.resolvidos,
            )
            return execucao
        except Exception as erro:
            db.rollback()
            log.exception("Automação %s falhou", nome)
            return _registrar("ERRO", nome, inicio, usuario_id, f"Falhou: {type(erro).__name__}. Detalhes no log do servidor.")


def executar_todas(usuario_id: int | None = None) -> list[m.ExecucaoAutomacao]:
    return [executar(nome, usuario_id=usuario_id) for nome in AUTOMACOES]


def situacao(db: Session) -> list[dict]:
    """Cada automação com a última execução (para o painel)."""
    saida = []
    for nome in AUTOMACOES:
        ultima = alerta_repository.ultima_execucao(db, nome)
        saida.append(
            {
                "nome": nome,
                "descricao": DESCRICOES[nome],
                "ultima": None
                if ultima is None
                else {
                    "status": ultima.status,
                    "iniciadaEm": ms(ultima.iniciada_em),
                    "terminadaEm": ms(ultima.terminada_em),
                    "criados": ultima.criados,
                    "atualizados": ultima.atualizados,
                    "resolvidos": ultima.resolvidos,
                    "detalhe": ultima.detalhe,
                },
            }
        )
    return saida
