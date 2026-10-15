"""Domínio atendimento: o CSV de atendimento da Vulto vira atendimentos + mensagens.

O que os dados mostraram: cada linha já é um atendimento inteiro (a conversa vem dentro da mensagem,
"[Atendente]: ...", "[Cliente]: ...", "[Bot]: ..."), com 17 linhas repetidas pela exportação.

Decisões aprovadas:
- Linhas do mesmo contato e do mesmo tipo a até 72 h uma da outra são o mesmo atendimento.
- Contato que não identifica ninguém (@ do Instagram, telefone sem DDD) e sem pedido: atendimento sem
  cliente (cliente_id nulo), com o contato guardado.
- Atendente do SAC → usuário (inativo) como responsável; bot e "time insta" ficam só no texto.

Regras (default proposto, registradas):
- Cliente: o do contato (telefone ou e-mail, pelo vínculo que a migração de clientes gravou); sem ele, o
  cliente do pedido citado.
- Pedido: a coluna pedido ("S104033" e "APP-7004819" são o número no site/app; "15723", "#15723",
  "pedido 15723" são o id da venda; "7011230", sete dígitos, é o do app sem o "APP-"); vazia, o pedido
  citado no texto.
- Loja: a do pedido; sem pedido, o CD Cajamar (a operação online da Vulto).
- Tipo pelo assunto (vazio: pelas tags). "troca/devolução" é devolução quando o texto fala em devolver,
  reembolso ou dinheiro de volta. Tipos que faltavam são criados inativos (não aparecem para o cliente no
  site até alguém ativar).
- Status: ok, resolvido, fechado, finalizado → CONCLUIDO; vazio, pendente, aberto → ABERTO.
- Spam e mensagens de teste ficam de fora.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from src import models as m
from src.entities.atendimento import protocolo
from src.entities.cliente import telefone_e164
from src.migracao_vulto import lojas
from src.migracao_vulto import normalizacao as n
from src.migracao_vulto.clientes import ORIGEM_CONTATO
from src.migracao_vulto.relatorio import Resultado
from src.migracao_vulto.usuarios import SEM_USUARIO, atendente, usuario_do_atendente
from src.migracao_vulto.vendas import ORIGEM_VENDAS
from src.repositories import migracao_repository

DOMINIO = "atendimento"
ORIGEM = "atendimentos.csv"
JANELA = timedelta(hours=72)

CANAL_POR_TEXTO = {
    "whatsapp": "WHATSAPP", "wpp": "WHATSAPP",
    "instagram": "INSTAGRAM", "insta": "INSTAGRAM", "instagram dm": "INSTAGRAM",
    "e-mail": "EMAIL", "email": "EMAIL",
}  # fmt: skip
STATUS_POR_TEXTO = {
    "ok": "CONCLUIDO", "resolvido": "CONCLUIDO", "fechado": "CONCLUIDO", "finalizado": "CONCLUIDO",
    "aguardando cliente": "AGUARDANDO_CLIENTE", "em andamento": "EM_ANDAMENTO",
    "pendente": "ABERTO", "aberto": "ABERTO", "": "ABERTO",
}  # fmt: skip

TROCA, DEVOLUCAO, ENTREGA = "Troca de produto", "Devolução e reembolso", "Acompanhamento de entrega"
DUVIDA, RECLAMACAO = "Dúvida sobre produto", "Reclamação"
PONTOS, PAGAMENTO, CANCELAMENTO, ELOGIO, LOJA = "Pontos Vulto+", "Pagamento", "Cancelamento", "Elogio", "Informações da loja"
# Tipos que a Casa Lorenzi não tinha: (categoria, descrição)
TIPOS_NOVOS = {
    PONTOS: ("Vulto+", "Saldo, resgate e categoria do programa de pontos da Vulto."),
    PAGAMENTO: ("Pedidos", "Pagamento não aprovado, cobrança ou estorno."),
    CANCELAMENTO: ("Pedidos", "Pedido de cancelamento de uma compra."),
    ELOGIO: ("Qualidade", "Elogio ao produto ou ao atendimento."),
    LOJA: ("Informações", "Endereço, horário e serviços das lojas."),
}
TIPO_POR_ASSUNTO = {
    "troca": TROCA, "devolucao": DEVOLUCAO, "devolução": DEVOLUCAO,
    "atraso entrega": ENTREGA, "entrega": ENTREGA, "pedido": ENTREGA,
    "dúvida produto": DUVIDA, "duvida produto": DUVIDA, "estoque": DUVIDA,
    "pontos": PONTOS, "pontos vulto+": PONTOS, "fidelidade": PONTOS,
    "pagamento": PAGAMENTO, "cancelamento": CANCELAMENTO, "reclamação": RECLAMACAO, "reclamacao": RECLAMACAO,
    "elogio": ELOGIO, "loja": LOJA,
}  # fmt: skip
TIPO_POR_TAG = (("troca", TROCA), ("entrega", ENTREGA), ("atraso", ENTREGA), ("vulto+", PONTOS), ("pontos", PONTOS),
                ("pagamento", PAGAMENTO), ("financeiro", PAGAMENTO), ("pre-venda", DUVIDA), ("loja", LOJA))  # fmt: skip
ASSUNTO_AMBIGUO = "troca/devolução"
FALA_EM_DEVOLVER = re.compile(r"devolv|devolu|reembols|dinheiro de volta|estorn", re.IGNORECASE)
DESCARTAR_ASSUNTO = {"spam"}

AUTOR_POR_MARCADOR = {"Cliente": "CLIENTE", "Atendente": "ATENDENTE", "Bot": "SISTEMA"}
MARCADOR = re.compile(r"\n\s*\[(Cliente|Atendente|Bot)\]:\s*")
# Pedido citado no texto: número do site/app, ou "pedido 15723" / "#15723"
PEDIDO_NO_TEXTO = re.compile(r"\b(S\d{6}|APP-\d{4,7})\b|(?:pedido\s*(?:n[º°o]\.?\s*)?#?|#)(\d{3,7})\b", re.IGNORECASE)


@dataclass
class Linha:
    id: str
    momento: datetime
    canal: str
    contato: str | None  # normalizado (E.164, e-mail, @handle) ou o texto original
    chave: str | None  # para juntar e achar o cliente: "telefone:...", "email:...", "instagram:..."
    nome: str | None
    tipo: str
    status: str
    atendente: str
    pedido_texto: str
    mensagem: str
    tags: str


@dataclass
class Grupo:
    linhas: list[Linha] = field(default_factory=list)

    @property
    def ultima(self) -> Linha:
        return self.linhas[-1]


class Contexto:
    def __init__(self, db: Session):
        self.db = db
        self.resultado = Resultado(DOMINIO)

    def ocorrencia(self, codigo, descricao, acao, *, id_origem=None, original=None, final=None):
        migracao_repository.registrar_ocorrencia(
            self.db, codigo_problema=codigo, dominio=DOMINIO, origem=ORIGEM, id_origem=id_origem, descricao=descricao,
            acao_tomada=acao, valor_original=None if original is None else str(original)[:500],
            valor_final=None if final is None else str(final),
        )  # fmt: skip


def _contato(texto: str | None) -> tuple[str | None, str | None]:
    """(contato para guardar, chave) — sem chave quando não identifica (telefone sem DDD)."""
    bruto = (texto or "").strip()
    if not bruto:
        return None, None
    try:
        if bruto.startswith("@"):
            handle = n.instagram(bruto)
            return f"@{handle}", f"instagram:{handle}"
        if "@" in bruto:
            email = n.email(bruto)
            return email, f"email:{email}"
        fone = n.telefone(bruto)
        return fone, f"telefone:{fone}"
    except n.ValorInvalido:
        return bruto, None


def tipo_do_atendimento(assunto: str | None, tags: str | None, mensagem: str | None) -> str | None:
    chave = (assunto or "").strip().lower()
    if chave == ASSUNTO_AMBIGUO or (not chave and "troca" in (tags or "").lower()):
        return DEVOLUCAO if FALA_EM_DEVOLVER.search(mensagem or "") else TROCA
    if chave:
        return TIPO_POR_ASSUNTO.get(chave)
    etiquetas = [t.strip() for t in re.split(r"[;,]", (tags or "").lower()) if t.strip()]
    return next((tipo for tag, tipo in TIPO_POR_TAG if tag in etiquetas), None)


def mensagens(texto: str) -> list[tuple[str, str]]:
    """A conversa embutida: [(autor_tipo, conteúdo)]. O primeiro trecho é do cliente."""
    partes = MARCADOR.split("\n" + (texto or "").strip())
    conversa = [("CLIENTE", partes[0].strip())]
    conversa += [
        (AUTOR_POR_MARCADOR[autor], conteudo.strip()) for autor, conteudo in zip(partes[1::2], partes[2::2], strict=True)
    ]
    return [(autor, conteudo) for autor, conteudo in conversa if conteudo]


# ---------- Leitura ----------


def _linhas(ctx: Contexto) -> list[Linha]:
    vistas: set[tuple] = set()
    linhas = []
    registros = ctx.db.execute(
        text(
            "SELECT id, data_hora, canal, contato, nome_contato, assunto, mensagem, status, atendente, pedido, tags "
            "FROM legado_vulto.atendimentos ORDER BY _linha"
        )
    ).mappings()
    for r in registros:
        ctx.resultado.lidos += 1
        repetida = ((r["contato"] or "").strip(), r["data_hora"], (r["mensagem"] or "").strip())
        if repetida in vistas:
            ctx.ocorrencia("ATENDIMENTO_REPETIDO", "Linha repetida na exportação (mesmo contato, hora e mensagem): entra uma "
                           "vez.", "DESCARTADO", id_origem=r["id"], original=r["contato"])  # fmt: skip
            ctx.resultado.descartados += 1
            continue
        vistas.add(repetida)
        if (r["assunto"] or "").strip().lower() in DESCARTAR_ASSUNTO:
            ctx.ocorrencia("ATENDIMENTO_SPAM", "Spam ou mensagem de teste: fora do atendimento.", "DESCARTADO",
                           id_origem=r["id"], original=(r["mensagem"] or "")[:120])  # fmt: skip
            ctx.resultado.descartados += 1
            continue
        tipo = tipo_do_atendimento(r["assunto"], r["tags"], r["mensagem"])
        if tipo is None:
            ctx.ocorrencia("ASSUNTO_SEM_TIPO", "Sem assunto nem tag reconhecida: entra como dúvida sobre produto.", "CORRIGIDO",
                           id_origem=r["id"], original=f"{r['assunto']} · {r['tags']}", final=DUVIDA)  # fmt: skip
            tipo = DUVIDA
        elif not (r["assunto"] or "").strip():
            ctx.ocorrencia("TIPO_PELAS_TAGS", "Sem assunto: tipo pelas tags.", "CORRIGIDO", id_origem=r["id"],
                           original=r["tags"], final=tipo)  # fmt: skip
        elif (r["assunto"] or "").strip().lower() == ASSUNTO_AMBIGUO:
            ctx.ocorrencia("TROCA_OU_DEVOLUCAO", '"troca/devolução": devolução quando o texto fala em devolver ou reembolso.',
                           "CORRIGIDO", id_origem=r["id"], original=r["assunto"], final=tipo)  # fmt: skip
        status_texto = (r["status"] or "").strip().lower()
        if not status_texto:
            ctx.ocorrencia("STATUS_VAZIO", "Atendimento sem status: entra como ABERTO, para alguém conferir.", "CORRIGIDO",
                           id_origem=r["id"], final="ABERTO")  # fmt: skip
        contato, chave = _contato(r["contato"])
        nome = n.nome_pessoa(r["nome_contato"])
        linhas.append(
            Linha(
                id=r["id"], momento=n.data_hora(r["data_hora"]).momento,
                canal=CANAL_POR_TEXTO[(r["canal"] or "").strip().lower()], contato=contato, chave=chave,
                nome=nome, tipo=tipo, status=STATUS_POR_TEXTO[status_texto],
                atendente=(r["atendente"] or "").strip(), pedido_texto=(r["pedido"] or "").strip(),
                mensagem=r["mensagem"] or "", tags=r["tags"] or "",
            )
        )  # fmt: skip
    return linhas


def agrupar(linhas: list[Linha]) -> list[Grupo]:
    """Mesmo contato e mesmo tipo, a até 72 h da linha anterior: o mesmo atendimento."""
    grupos: list[Grupo] = []
    abertos: dict[tuple[str, str], Grupo] = {}
    for linha in sorted(linhas, key=lambda li: (li.momento, int(li.id))):
        chave = (linha.chave or linha.contato or f"linha:{linha.id}", linha.tipo)
        grupo = abertos.get(chave)
        if grupo is None or linha.momento - grupo.ultima.momento > JANELA:
            grupo = Grupo()
            grupos.append(grupo)
            abertos[chave] = grupo
        grupo.linhas.append(linha)
    return grupos


# ---------- Cliente e pedido ----------


class Vinculos:
    """Contato → cliente e referência de pedido → pedido da Vulto."""

    def __init__(self, db: Session):
        self.db = db
        self.cliente_do_contato = {
            id_origem: int(destino)
            for id_origem, destino in db.execute(
                select(m.DePara.id_origem, m.DePara.id_destino).where(m.DePara.origem == ORIGEM_CONTATO)
            )
        }
        # Contatos que a migração de clientes não ligou (ex.: celular que também passa como CPF): pelo cadastro
        por_telefone: dict[str, set[int]] = defaultdict(set)
        por_email: dict[str, set[int]] = defaultdict(set)
        for cid, fone, email in db.execute(select(m.Cliente.id, m.Cliente.telefone, m.Cliente.email)):
            if fone and (e164 := telefone_e164(fone)):
                por_telefone[e164].add(cid)
            if email:
                por_email[email].add(cid)
        self.por_cadastro = {f"telefone:{k}": v for k, v in por_telefone.items()} | {
            f"email:{k}": v for k, v in por_email.items()
        }
        vulto = select(m.Loja.id).where(m.Loja.marca == "VULTO")
        self.pedido_externo = dict(
            db.execute(
                select(func.upper(m.Pedido.pedido_externo), m.Pedido.id).where(
                    m.Pedido.pedido_externo.is_not(None), m.Pedido.loja_id.in_(vulto)
                )
            ).all()
        )
        self.pedido_da_venda = {
            id_origem: int(destino)
            for id_origem, destino in db.execute(
                select(m.DePara.id_origem, m.DePara.id_destino).where(
                    m.DePara.origem == ORIGEM_VENDAS, m.DePara.tabela_destino == "pedidos"
                )
            )
        }

    def cliente(self, chave: str | None) -> tuple[int | None, bool]:
        """(cliente, ambíguo)."""
        if not chave or chave.startswith("instagram:"):
            return None, False
        if chave in self.cliente_do_contato:
            return self.cliente_do_contato[chave], False
        candidatos = self.por_cadastro.get(chave, set())
        return (next(iter(candidatos)), False) if len(candidatos) == 1 else (None, len(candidatos) > 1)

    def pedido(self, referencia: str) -> int | None:
        texto = referencia.strip().upper()
        if texto in self.pedido_externo:
            return self.pedido_externo[texto]
        numero = re.sub(r"\D", "", texto)
        if not numero:
            return None
        if len(numero) >= 7:  # o app numera com 7 dígitos; o "APP-" ficou de fora
            return self.pedido_externo.get(f"APP-{numero}")
        # Id da venda no sistema da Vulto (também quando veio com "APP-" ou "S" na frente)
        return self.pedido_da_venda.get(str(int(numero)))


def _pedido(ctx: Contexto, vinculos: Vinculos, grupo: Grupo) -> int | None:
    for linha in grupo.linhas:
        if linha.pedido_texto:
            pedido = vinculos.pedido(linha.pedido_texto)
            if pedido is None:
                ctx.ocorrencia("PEDIDO_NAO_ENCONTRADO", "O pedido informado não corresponde a nenhuma venda migrada.", "PENDENTE",
                               id_origem=linha.id, original=linha.pedido_texto)  # fmt: skip
            return pedido
    for linha in grupo.linhas:
        citado = PEDIDO_NO_TEXTO.search(linha.mensagem)
        if citado and (pedido := vinculos.pedido(citado[1] or citado[2])):
            ctx.ocorrencia("PEDIDO_PELO_TEXTO", "Coluna pedido vazia: pedido citado na mensagem.", "CORRIGIDO",
                           id_origem=linha.id, original=citado[0], final=pedido)  # fmt: skip
            return pedido
    return None


# ---------- Carga ----------


def _ja_migrado(db: Session, grupo: Grupo) -> m.Atendimento | None:
    for linha in grupo.linhas:
        if destino := migracao_repository.destino(db, ORIGEM, linha.id, "atendimentos"):
            return db.get(m.Atendimento, destino)
    return None


def _tipos(ctx: Contexto) -> dict[str, int]:
    """Título → id, criando (inativos) os tipos que a Casa Lorenzi não tinha."""
    tipos = dict(ctx.db.execute(select(m.TipoSolicitacao.titulo, m.TipoSolicitacao.id)).all())
    ordem = ctx.db.scalar(select(func.coalesce(func.max(m.TipoSolicitacao.ordem_exibicao), 0)))
    for titulo, (categoria, descricao) in TIPOS_NOVOS.items():
        if titulo in tipos:
            continue
        ordem += 1
        tipo = m.TipoSolicitacao(
            titulo=titulo, categoria=categoria, descricao=descricao, exige_venda=False, ordem_exibicao=ordem, ativo=False
        )
        ctx.db.add(tipo)
        ctx.db.flush()
        tipos[titulo] = tipo.id
        ctx.ocorrencia("TIPO_CRIADO", "Tipo de solicitação que a Casa Lorenzi não tinha: criado inativo (não aparece no site "
                       "até alguém ativar).", "CORRIGIDO", final=titulo)  # fmt: skip
    return tipos


def migrar(db: Session) -> Resultado:
    ctx = Contexto(db)
    migracao_repository.limpar_ocorrencias(db, DOMINIO)
    linhas = _linhas(ctx)
    grupos = agrupar(linhas)
    tipos = _tipos(ctx)
    vinculos = Vinculos(db)
    cd = lojas.loja_da_vulto(db, lojas.ID_LEGADO_CD)
    usados: set[int] = set()
    contagem = defaultdict(int)

    for grupo in grupos:
        primeira, ultima = grupo.linhas[0], grupo.ultima
        if len(grupo.linhas) > 1:
            contagem["juntados"] += len(grupo.linhas) - 1
            ctx.ocorrencia("LINHAS_JUNTADAS", f"{len(grupo.linhas)} linhas do mesmo contato e assunto a menos de 72 h: um "
                           "atendimento só.", "CORRIGIDO", id_origem=primeira.id,
                           original=", ".join(li.id for li in grupo.linhas))  # fmt: skip
        pedido_id = _pedido(ctx, vinculos, grupo)
        pedido = db.get(m.Pedido, pedido_id) if pedido_id else None
        cliente_id, ambiguo = vinculos.cliente(primeira.chave)
        if ambiguo:
            ctx.ocorrencia("CONTATO_AMBIGUO", "O contato é de mais de um cliente: fica sem cliente (ou o do pedido).", "PENDENTE",
                           id_origem=primeira.id, original=primeira.contato)  # fmt: skip
        if cliente_id is None and pedido is not None and pedido.cliente_id is not None:
            cliente_id = pedido.cliente_id
            contagem["cliente_pelo_pedido"] += 1
            ctx.ocorrencia("CLIENTE_PELO_PEDIDO", "O contato não identifica o cliente (@ do Instagram, telefone sem DDD): "
                           "cliente do pedido citado.", "CORRIGIDO", id_origem=primeira.id, original=primeira.contato,
                           final=pedido.numero)  # fmt: skip
        elif cliente_id is not None and pedido is not None and pedido.cliente_id not in (None, cliente_id):
            ctx.ocorrencia("PEDIDO_DE_OUTRO_CLIENTE", "O pedido citado é de outro cliente: ficam o cliente do contato e o "
                           "pedido, para a equipe conferir.", "PENDENTE", id_origem=primeira.id,
                           original=f"{primeira.contato} · {pedido.numero}")  # fmt: skip
        if cliente_id is None:
            contagem["sem_cliente"] += 1
            ctx.ocorrencia("ATENDIMENTO_SEM_CLIENTE", "Contato que não identifica nenhum cliente e sem pedido que identifique: "
                           "fica sem cliente, com o contato guardado.", "MANTIDO", id_origem=primeira.id,
                           original=primeira.contato)  # fmt: skip
        if pedido is not None:
            contagem["com_pedido"] += 1

        responsavel = usuario_do_atendente(db, ultima.atendente)
        if responsavel is None and ultima.atendente.lower() not in SEM_USUARIO and atendente(ultima.atendente) is None:
            ctx.ocorrencia("ATENDENTE_DESCONHECIDO", "Atendente que não é do SAC: sem responsável.", "MANTIDO",
                           id_origem=ultima.id, original=ultima.atendente)  # fmt: skip

        atendimento = _ja_migrado(db, grupo)
        if atendimento is None:
            atendimento = m.Atendimento(protocolo=f"VLT-TMP-{primeira.id}")
            db.add(atendimento)
            ctx.resultado.carregados += 1
        else:
            db.execute(delete(m.Mensagem).where(m.Mensagem.atendimento_id == atendimento.id))
        atendimento.cliente_id = cliente_id
        atendimento.contato = primeira.contato
        atendimento.contato_nome = next((li.nome for li in reversed(grupo.linhas) if li.nome), None)
        atendimento.canal = primeira.canal
        atendimento.tipo_solicitacao_id = tipos[primeira.tipo]
        atendimento.status = ultima.status
        atendimento.pedido_id = pedido.id if pedido else None
        atendimento.loja_id = pedido.loja_id if pedido else cd.id
        atendimento.responsavel_id = responsavel
        atendimento.criado_em = primeira.momento
        db.flush()
        atendimento.protocolo = protocolo(atendimento.id)
        quando = primeira.momento
        for linha in grupo.linhas:
            quando = max(quando, linha.momento)
            for i, (autor, conteudo) in enumerate(mensagens(linha.mensagem)):
                db.add(
                    m.Mensagem(
                        atendimento_id=atendimento.id, autor_tipo=autor,
                        autor_id=responsavel if autor == "ATENDENTE" else None,
                        conteudo=conteudo, enviado_em=linha.momento + timedelta(seconds=i),
                    )
                )  # fmt: skip
                quando = max(quando, linha.momento + timedelta(seconds=i))
            migracao_repository.vincular(db, ORIGEM, linha.id, "atendimentos", atendimento.id)
        atendimento.atualizado_em = quando
        usados.add(atendimento.id)

    # Atendimento migrado antes que não existe mais (o agrupamento mudou): sai
    antigos = {
        int(destino)
        for (destino,) in db.execute(
            select(m.DePara.id_destino).where(m.DePara.origem == ORIGEM, m.DePara.tabela_destino == "atendimentos")
        )
    } - usados
    if antigos:
        db.execute(delete(m.Mensagem).where(m.Mensagem.atendimento_id.in_(antigos)))
        db.execute(delete(m.DePara).where(m.DePara.origem == ORIGEM, m.DePara.id_destino.in_(antigos)))
        db.execute(delete(m.Atendimento).where(m.Atendimento.id.in_(antigos)))
    db.flush()

    ctx.resultado.ocorrencias = migracao_repository.ocorrencias_por_acao(db, DOMINIO)
    ctx.resultado.corrigidos = contagem["cliente_pelo_pedido"]
    ctx.resultado.notas = [
        f"atendimentos: {len(grupos)} (de {len(linhas)} linhas; {contagem['juntados']} juntadas pela janela de 72 h)",
        f"com pedido: {contagem['com_pedido']} · cliente pelo pedido: {contagem['cliente_pelo_pedido']} · "
        f"sem cliente: {contagem['sem_cliente']}",
    ]
    return ctx.resultado
