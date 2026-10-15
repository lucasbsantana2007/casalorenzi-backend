"""Domínio clientes: as pessoas da Vulto viram clientes da plataforma (cliente não tem marca).

Origens, da mais confiável para a menos: aba Clientes da planilha de fidelidade (congelada em
01/01/2025), aba clientes antigos (programa de 2023), cliente_ref das vendas e das compras do
Vulto+ (CPF, e-mail ou telefone, "depende de quem cadastrou") e os contatos do CSV de atendimento.

- Deduplicação: CPF válido → e-mail → telefone. Dois CPFs diferentes nunca viram uma pessoa só,
  mesmo com e-mail ou telefone em comum (família, casal): o e-mail fica com o cadastro mais recente.
  Também contra os clientes da Casa Lorenzi: a mesma pessoa vira um registro só.
- Divergência de nome ou telefone entre duplicatas: vale o registro mais recente. O nome do
  atendimento é apelido ("nicole"): só entra sem nome de cadastro. Sem nome nenhum (comprou depois
  de jan/25 e só existe nas vendas): nome provisório, com ocorrência.
- Consentimento (LGPD): só aceita mensagem com "1", "x", "sim" ou "S"; "N", vazio ou "não ligar"
  na observação é sem consentimento. Na Casa Lorenzi, o "não" da Vulto vale; o "sim" não.
- Telefone sem DDD fica sem telefone (não se adivinha o DDD); o original continua no staging.
- Conta Vulto+ para quem tem CPF, com a categoria declarada na planilha (a pela regra vem com a
  migração da fidelidade, que limpa os pontos antes).
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src import models as m
from src.entities.cliente import telefone_e164
from src.migracao_vulto import lojas as lojas_vulto
from src.migracao_vulto import normalizacao as n
from src.migracao_vulto.relatorio import Resultado
from src.repositories import migracao_repository

DOMINIO = "clientes"
NOME_PROVISORIO = "Cliente Vulto (sem nome)"
ORIGEM_CLIENTES = "clientes.xlsx:Clientes"
ORIGEM_ANTIGOS = "clientes.xlsx:clientes antigos (NAO APAGAR)"
ORIGEM_REFERENCIA = "vulto.db:cliente_ref"  # id_origem = "cpf:...", "email:..." ou "telefone:..."
ORIGEM_CONTATO = "atendimentos.csv:contato"
# Marca os clientes criados pela migração (os outros são da Casa Lorenzi e nunca são sobrescritos)
ORIGEM_CRIADO = "vulto:cliente"
ORIGENS_CADASTRO = (ORIGEM_CLIENTES, ORIGEM_ANTIGOS)
CONSENTIMENTO_ORIGEM = "vulto:aceita_msg"
SEM_CONTATO = "nao ligar"  # observação da planilha que vale como recusa de contato

# Loja de cadastro (texto livre da planilha) → loja do legado; site, e-commerce e app ficam sem loja
LOJA_POR_TEXTO = (("pinheiros", 1), ("eldorado", 2), ("savassi", 3), ("bh", 3), ("batel", 4), ("cwb", 4))


@dataclass
class Registro:
    """Uma aparição de uma pessoa numa origem."""

    origem: str
    id_origem: str
    quando: datetime | None = None
    nome: str | None = None
    nome_de_cadastro: bool = False  # planilha (nome completo) × atendimento (apelido)
    cpf: str | None = None
    email: str | None = None
    telefone: str | None = None
    aceita: bool | None = None
    categoria_declarada: str | None = None
    loja_legado: int | None = None

    @property
    def recencia(self) -> datetime:
        return self.quando or datetime.min.replace(tzinfo=n.FUSO_ORIGEM)


@dataclass
class Grupo:
    """Registros que são a mesma pessoa."""

    registros: list[Registro] = field(default_factory=list)
    regras: set[str] = field(default_factory=set)  # CPF, EMAIL, TELEFONE

    def valores(self, campo: str) -> set[str]:
        return {getattr(r, campo) for r in self.registros if getattr(r, campo)}

    def mais_recente(self, campo: str, filtro=lambda r: True):
        candidatos = [r for r in self.registros if getattr(r, campo) and filtro(r)]
        return getattr(max(candidatos, key=lambda r: r.recencia), campo) if candidatos else None


class Contexto:
    def __init__(self, db: Session):
        self.db = db
        self.resultado = Resultado(DOMINIO)
        self.corrigidos: set[tuple[str, str]] = set()

    def ocorrencia(self, codigo, origem, descricao, acao, *, id_origem=None, original=None, final=None):
        migracao_repository.registrar_ocorrencia(
            self.db,
            codigo_problema=codigo,
            dominio=DOMINIO,
            origem=origem,
            id_origem=id_origem,
            descricao=descricao,
            acao_tomada=acao,
            valor_original=None if original is None else str(original),
            valor_final=None if final is None else str(final),
        )
        if acao == "CORRIGIDO" and id_origem:
            self.corrigidos.add((origem, id_origem))

    def campo(self, funcao, valor, codigo, origem, id_origem, descricao, **kwargs):
        """Normaliza um campo; se não der, registra a ocorrência e devolve None."""
        try:
            return funcao(valor, **kwargs)
        except n.ValorInvalido as erro:
            self.ocorrencia(codigo, origem, f"{descricao} ({erro}).", "DESCARTADO", id_origem=id_origem, original=valor)
            return None


# ---------- Leitura ----------


def _loja(texto: str | None) -> int | None:
    chave = n.sem_acento(str(texto or "")).strip().lower()
    return next((loja for termo, loja in LOJA_POR_TEXTO if termo == chave or (len(termo) > 3 and termo in chave)), None)


def _registros_planilha(ctx: Contexto) -> list[Registro]:
    registros = []
    consulta = text(
        "SELECT _linha, nome, cpf, e_mail, tel, data_cadastro, categoria, obs, aceita_msg, loja_cadastro, _tipos "
        "FROM legado_vulto.clientes__clientes ORDER BY _linha"
    )
    for linha, nome, cpf, email, tel, cadastro, categoria, obs, aceita, loja, tipos in ctx.db.execute(consulta):
        tipos = json.loads(tipos or "{}")
        idl = str(linha)
        quando = ctx.campo(
            n.data_hora,
            cadastro,
            "DATA_CADASTRO_INVALIDA",
            ORIGEM_CLIENTES,
            idl,
            "Data de cadastro ilegível",
            serial_excel=tipos.get("data_cadastro") == "int",
        )
        consentimento = ctx.campo(
            n.booleano, aceita, "ACEITA_MSG_INVALIDO", ORIGEM_CLIENTES, idl, "aceita_msg ilegível: sem consentimento"
        )
        if obs and SEM_CONTATO in n.sem_acento(obs).lower():
            if consentimento:
                ctx.ocorrencia(
                    "NAO_LIGAR_COM_ACEITE",
                    ORIGEM_CLIENTES,
                    'aceita_msg diz sim, mas a observação diz "não ligar": fica sem consentimento (LGPD, na dúvida).',
                    "CORRIGIDO",
                    id_origem=idl,
                    original=f"aceita_msg={aceita} · obs={obs}",
                    final="sem consentimento",
                )
            consentimento = False
        registros.append(
            Registro(
                ORIGEM_CLIENTES,
                idl,
                quando.momento if quando else None,
                nome=n.nome_pessoa(nome),
                nome_de_cadastro=True,
                cpf=ctx.campo(
                    n.cpf,
                    cpf,
                    "CPF_INVALIDO",
                    ORIGEM_CLIENTES,
                    idl,
                    "CPF inválido: o cliente entra sem CPF",
                    numero_excel=tipos.get("cpf") == "int",
                ),
                email=ctx.campo(
                    n.email, email, "EMAIL_INVALIDO", ORIGEM_CLIENTES, idl, "E-mail inválido: o cliente entra sem e-mail"
                ),
                telefone=ctx.campo(
                    n.telefone,
                    tel,
                    "TELEFONE_INVALIDO",
                    ORIGEM_CLIENTES,
                    idl,
                    "Telefone sem DDD ou inválido: o cliente entra sem telefone",
                ),
                aceita=consentimento,
                categoria_declarada=(categoria or "").strip() or None,
                loja_legado=_loja(loja),
            )
        )
    return registros


def _registros_antigos(ctx: Contexto) -> list[Registro]:
    registros = []
    consulta = text(
        "SELECT _linha, nome_completo, cpf_cnpj, ult_compra, _tipos FROM legado_vulto.clientes__clientes_antigos_nao_apagar"
    )
    for linha, nome, cpf, ultima, tipos in ctx.db.execute(consulta):
        tipos = json.loads(tipos or "{}")
        quando = ctx.campo(n.data_hora, ultima, "DATA_INVALIDA", ORIGEM_ANTIGOS, str(linha), "Data da última compra ilegível")
        documento = ctx.campo(
            n.cpf, cpf, "CPF_INVALIDO", ORIGEM_ANTIGOS, str(linha), "CPF inválido", numero_excel=tipos.get("cpf_cnpj") == "int"
        )
        registros.append(
            Registro(
                ORIGEM_ANTIGOS,
                str(linha),
                quando.momento if quando else None,
                nome=n.nome_pessoa(nome),
                nome_de_cadastro=True,
                cpf=documento,
            )
        )
    return registros


def _registros_referencias(ctx: Contexto, conhecidos: dict[str, set[str]]) -> list[Registro]:
    """cliente_ref das vendas e das compras: um registro por identificador distinto, com a última data."""
    ultimas: dict[tuple[str, str], datetime] = {}
    invalidas: Counter = Counter()
    ambiguas: Counter = Counter()
    for tabela in ("db__vendas", "db__compras"):
        for ref, criado in ctx.db.execute(text(f"SELECT cliente_ref, criado_em FROM legado_vulto.{tabela}")):
            try:
                referencia = n.referencia_cliente(ref)
            except n.ValorInvalido:
                invalidas[ref.strip()] += 1
                continue
            if referencia is None:
                continue
            tipo, valor = referencia.tipo, referencia.valor
            if referencia.ambigua:
                fone = n.telefone(ref)
                if valor not in conhecidos["cpf"] and fone in conhecidos["telefone"]:
                    tipo, valor = "telefone", fone
                elif valor not in conhecidos["cpf"]:
                    ambiguas[ref.strip()] += 1
            momento = n.data_hora(criado).momento
            ultimas[(tipo, valor)] = max(momento, ultimas.get((tipo, valor), momento))
    for ref, vezes in sorted(invalidas.items()):
        ctx.ocorrencia(
            "REFERENCIA_SEM_CLIENTE",
            "vulto.db:vendas/compras.cliente_ref",
            f"Referência de cliente que não identifica ninguém ({vezes} vendas/compras): ficam sem cliente.",
            "DESCARTADO",
            id_origem=ref[:80],
            original=ref,
        )
        ctx.resultado.descartados += 1
    for ref, vezes in sorted(ambiguas.items()):
        ctx.ocorrencia(
            "REFERENCIA_AMBIGUA",
            "vulto.db:vendas/compras.cliente_ref",
            f"11 dígitos que são CPF válido e "
            f"também têm cara de celular ({vezes} registros): tratado como CPF (o dígito verificador bate).",
            "MANTIDO",
            id_origem=ref,
            original=ref,
        )
    return [Registro(ORIGEM_REFERENCIA, f"{tipo}:{valor}", quando, **{tipo: valor}) for (tipo, valor), quando in ultimas.items()]


def _registros_contatos(ctx: Contexto) -> list[Registro]:
    """Contatos (telefone ou e-mail) do atendimento, com o nome que a pessoa usou. Instagram não casa."""
    por_contato: dict[tuple[str, str], Registro] = {}
    for contato, nome, quando in ctx.db.execute(text("SELECT contato, nome_contato, data_hora FROM legado_vulto.atendimentos")):
        if not contato or contato.strip().startswith("@"):
            continue
        try:
            referencia = n.referencia_cliente(contato)
        except n.ValorInvalido:
            continue  # sem DDD ou ilegível: tratado na migração do atendimento
        if referencia is None or referencia.tipo == "cpf":
            continue
        momento = n.data_hora(quando).momento
        chave = (referencia.tipo, referencia.valor)
        atual = por_contato.get(chave)
        if atual is None or momento > atual.recencia:
            por_contato[chave] = Registro(
                ORIGEM_CONTATO,
                f"{referencia.tipo}:{referencia.valor}",
                momento,
                nome=n.nome_pessoa(nome),
                **{referencia.tipo: referencia.valor},
            )
    return list(por_contato.values())


# ---------- Deduplicação ----------


def agrupar(registros: list[Registro]) -> list[Grupo]:
    """CPF → e-mail → telefone; nunca junta grupos com CPFs diferentes, nem (no telefone) com e-mails diferentes."""
    grupos: list[Grupo] = [Grupo([r]) for r in registros]
    dono: dict[int, Grupo] = {id(r): g for g, r in zip(grupos, registros, strict=True)}

    def juntar(a: Grupo, b: Grupo, regra: str) -> Grupo:
        if a is b:
            return a
        a.registros += b.registros
        a.regras |= b.regras | {regra}
        for r in b.registros:
            dono[id(r)] = a
        b.registros = []
        return a

    def compativel(a: Grupo, b: Grupo, campos: tuple[str, ...]) -> bool:
        return all(not (a.valores(c) and b.valores(c)) or a.valores(c) & b.valores(c) for c in campos)

    for campo, regra, barreiras in (("cpf", "CPF", ()), ("email", "EMAIL", ("cpf",)), ("telefone", "TELEFONE", ("cpf", "email"))):
        por_valor: dict[str, list[Registro]] = defaultdict(list)
        for r in registros:
            if getattr(r, campo):
                por_valor[getattr(r, campo)].append(r)
        for mesmos in por_valor.values():
            base = dono[id(mesmos[0])]
            for r in mesmos[1:]:
                outro = dono[id(r)]
                if outro is not base and compativel(base, outro, barreiras):
                    base = juntar(base, outro, regra)
    return [g for g in grupos if g.registros]


# ---------- Carga ----------


def _criados_pela_migracao(db: Session) -> set[int]:
    return set(
        db.scalars(select(m.DePara.id_destino).where(m.DePara.origem == ORIGEM_CRIADO, m.DePara.tabela_destino == "clientes"))
    )


def _clientes_da_lorenzi(db: Session, criados: set[int]) -> list[m.Cliente]:
    return [c for c in db.scalars(select(m.Cliente).where(m.Cliente.excluido_em.is_(None))) if c.id not in criados]


def _ja_migrado(db: Session, grupo: Grupo) -> m.Cliente | None:
    for r in sorted(grupo.registros, key=lambda r: (r.origem not in ORIGENS_CADASTRO, r.origem, r.id_origem)):
        cliente_id = migracao_repository.destino(db, r.origem, r.id_origem, "clientes")
        if cliente_id:
            return db.get(m.Cliente, cliente_id)
    return None


def _da_lorenzi(indices: dict[str, dict[str, m.Cliente]], grupo: Grupo) -> m.Cliente | None:
    for campo in ("cpf", "email", "telefone"):
        for valor in grupo.valores(campo):
            if (cliente := indices[campo].get(valor)) is not None:
                cpf_vulto = grupo.valores("cpf")
                if not cliente.cpf or not cpf_vulto or cliente.cpf in cpf_vulto:
                    return cliente
    return None


def migrar(db: Session) -> Resultado:
    ctx = Contexto(db)
    migracao_repository.limpar_ocorrencias(db, DOMINIO)

    cadastros = _registros_planilha(ctx) + _registros_antigos(ctx)
    conhecidos = {campo: {getattr(r, campo) for r in cadastros if getattr(r, campo)} for campo in ("cpf", "email", "telefone")}
    referencias = _registros_referencias(ctx, conhecidos)
    contatos = _registros_contatos(ctx)
    registros = cadastros + referencias + contatos
    ctx.resultado.lidos = len(registros) + ctx.resultado.descartados

    grupos = agrupar(registros)
    _distribuir_emails(ctx, grupos)

    criados = _criados_pela_migracao(db)
    lorenzi = _clientes_da_lorenzi(db, criados)
    # Telefone da Casa Lorenzi vem com máscara ("(11) 98422-1937"): compara pela forma E.164
    indices = {campo: {getattr(c, campo): c for c in lorenzi if getattr(c, campo)} for campo in ("cpf", "email")}
    indices["telefone"] = {telefone_e164(c.telefone): c for c in lorenzi if telefone_e164(c.telefone)}
    lojas = {i: lojas_vulto.loja_da_vulto(db, i) for i in lojas_vulto.LOJAS}
    contas = sem_nome = mesclados = 0
    for grupo in sorted(grupos, key=lambda g: min((r.origem, r.id_origem) for r in g.registros)):
        cliente = _ja_migrado(db, grupo) or _da_lorenzi(indices, grupo)
        if cliente is not None and cliente.id not in criados:
            mesclados += 1
            _completar_lorenzi(ctx, cliente, grupo)
        else:
            cliente = _gravar_vulto(ctx, cliente, grupo, lojas)
            db.flush()
            migracao_repository.vincular(db, ORIGEM_CRIADO, _id_grupo(grupo), "clientes", cliente.id)
            criados.add(cliente.id)
            sem_nome += cliente.nome == NOME_PROVISORIO
        db.flush()
        for r in grupo.registros:
            migracao_repository.vincular(db, r.origem, r.id_origem, "clientes", cliente.id)
        _registrar_fusao(ctx, grupo, cliente)
        if cliente.cpf:
            contas += _conta_pontos(db, cliente, grupo)

    db.flush()
    ctx.resultado.carregados = len(grupos)
    ctx.resultado.corrigidos = len(ctx.corrigidos)
    ctx.resultado.ocorrencias = migracao_repository.ocorrencias_por_acao(db, DOMINIO)
    ctx.resultado.notas = [
        f"registros lidos: {len(cadastros)} de cadastro, {len(referencias)} referências de vendas/compras, "
        f"{len(contatos)} contatos do atendimento",
        f"clientes: {len(grupos)} ({mesclados} já eram da Casa Lorenzi, {sem_nome} com nome provisório)",
        f"contas Vulto+ (clientes com CPF): {contas}",
    ]
    return ctx.resultado


def _distribuir_emails(ctx: Contexto, grupos: list[Grupo]) -> None:
    """E-mail é único: o mesmo e-mail em grupos diferentes (CPFs diferentes) fica com o mais recente."""
    donos: dict[str, list[tuple[datetime, Grupo]]] = defaultdict(list)
    for g in grupos:
        for email in g.valores("email"):
            recencia = max(r.recencia for r in g.registros if r.email == email)
            donos[email].append((recencia, g))
    for email, lista in donos.items():
        if len(lista) < 2:
            continue
        lista.sort(key=lambda par: par[0])
        for _, g in lista[:-1]:
            for r in g.registros:
                if r.email == email:
                    r.email = None
            ctx.ocorrencia(
                "EMAIL_DE_OUTRA_PESSOA",
                ORIGEM_CLIENTES,
                "O mesmo e-mail em cadastros com CPFs diferentes (duas pessoas): o e-mail fica com o cadastro mais recente.",
                "CORRIGIDO",
                id_origem=_id_grupo(g),
                original=email,
                final=None,
            )


def _id_grupo(grupo: Grupo) -> str:
    cpf = sorted(grupo.valores("cpf"))
    return f"cpf:{cpf[0]}" if cpf else min(f"{r.origem}#{r.id_origem}" for r in grupo.registros)[:80]


def _nome(ctx: Contexto, grupo: Grupo) -> str:
    de_cadastro = {n.sem_acento(r.nome).lower() for r in grupo.registros if r.nome and r.nome_de_cadastro}
    if len(de_cadastro) > 1:
        ctx.ocorrencia(
            "NOME_DIVERGE_ENTRE_DUPLICATAS",
            ORIGEM_CLIENTES,
            "A mesma pessoa com nomes diferentes nos cadastros: vale o mais recente.",
            "MANTIDO",
            id_origem=_id_grupo(grupo),
            original=" · ".join(sorted(de_cadastro)),
        )
    nome = grupo.mais_recente("nome", lambda r: r.nome_de_cadastro) or grupo.mais_recente("nome")
    if nome:
        return nome[:120]
    ctx.ocorrencia(
        "CLIENTE_SEM_NOME",
        ORIGEM_REFERENCIA,
        f"Cliente que só aparece nas vendas (cadastrou depois de jan/25): "
        f'entra com o nome "{NOME_PROVISORIO}" até alguém completar.',
        "PENDENTE",
        id_origem=_id_grupo(grupo),
    )
    return NOME_PROVISORIO


def _consentimento(grupo: Grupo) -> tuple[bool, datetime | None]:
    respostas = [r for r in grupo.registros if r.aceita is not None]
    if not respostas or any(r.aceita is False for r in respostas):
        return False, None
    sim = max(respostas, key=lambda r: r.recencia)
    return True, sim.quando


def _gravar_vulto(ctx: Contexto, cliente: m.Cliente | None, grupo: Grupo, lojas: dict) -> m.Cliente:
    db = ctx.db
    telefones = grupo.valores("telefone")
    if len(telefones) > 1:
        ctx.ocorrencia(
            "TELEFONE_DIVERGE_ENTRE_DUPLICATAS",
            ORIGEM_CLIENTES,
            "A mesma pessoa com telefones diferentes: vale o mais recente.",
            "MANTIDO",
            id_origem=_id_grupo(grupo),
            original=" · ".join(sorted(telefones)),
        )
    emails = grupo.valores("email")
    email = grupo.mais_recente("email")
    if (
        email
        and (outro := db.scalar(select(m.Cliente).where(m.Cliente.email == email)))
        and (cliente is None or outro.id != cliente.id)
    ):
        ctx.ocorrencia(
            "EMAIL_JA_USADO",
            ORIGEM_CLIENTES,
            "E-mail já usado por outro cliente da plataforma: este entra sem e-mail.",
            "CORRIGIDO",
            id_origem=_id_grupo(grupo),
            original=email,
        )
        email = None
    if len(emails) > 1:
        ctx.ocorrencia(
            "EMAIL_DIVERGE_ENTRE_DUPLICATAS",
            ORIGEM_CLIENTES,
            "A mesma pessoa com e-mails diferentes: fica o mais recente (os outros continuam ligados a ela no de_para).",
            "MANTIDO",
            id_origem=_id_grupo(grupo),
            original=" · ".join(sorted(emails)),
            final=email,
        )
    if cliente is None:
        cliente = m.Cliente()
        db.add(cliente)
    datas = [r.quando.date() for r in grupo.registros if r.quando]
    aceita, aceita_em = _consentimento(grupo)
    loja = grupo.mais_recente("loja_legado")
    cliente.nome = _nome(ctx, grupo)
    cliente.cpf = next(iter(grupo.valores("cpf")), None)
    cliente.email = email
    cliente.telefone = grupo.mais_recente("telefone")
    cliente.cliente_desde = min(datas) if datas else date.today()
    cliente.loja_preferida_id = lojas[loja].id if loja and lojas.get(loja) else None
    cliente.aceita_marketing = aceita
    cliente.aceita_marketing_em = aceita_em
    cliente.aceita_marketing_origem = CONSENTIMENTO_ORIGEM if aceita else None
    return cliente


def _completar_lorenzi(ctx: Contexto, cliente: m.Cliente, grupo: Grupo) -> None:
    """Cliente que já era da Casa Lorenzi: nada dele é apagado ou trocado; só os campos vazios são
    completados. O "não" da Vulto para mensagens vale; o "sim" não (consentimento é por empresa, na dúvida não)."""
    completados = []
    if not cliente.cpf and (cpf := next(iter(grupo.valores("cpf")), None)):
        cliente.cpf = cpf
        completados.append("CPF")
    if not cliente.telefone and (telefone := grupo.mais_recente("telefone")):
        cliente.telefone = telefone
        completados.append("telefone")
    if any(r.aceita is False for r in grupo.registros) and cliente.aceita_marketing:
        cliente.aceita_marketing, cliente.aceita_marketing_em = False, None
        cliente.aceita_marketing_origem = CONSENTIMENTO_ORIGEM
        completados.append("recusa de mensagens")
    ctx.ocorrencia(
        "CLIENTE_JA_DA_LORENZI",
        ORIGEM_CLIENTES,
        "A pessoa já era cliente da Casa Lorenzi: os dados da Vulto "
        "ficam ligados a ela, sem trocar nada do cadastro (só completa o que estava vazio).",
        "MANTIDO",
        id_origem=_id_grupo(grupo),
        final=", ".join(completados) or "nada a completar",
    )


def _registrar_fusao(ctx: Contexto, grupo: Grupo, cliente: m.Cliente) -> None:
    """Fusão: mais de um cadastro (planilha) virou um cliente só. Ligação: um cadastro (ou nenhum) e
    os e-mails/telefones das vendas e do atendimento juntados a ele pela regra de e-mail ou telefone."""
    cadastros = [r for r in grupo.registros if r.origem in ORIGENS_CADASTRO]
    regras = ", ".join(sorted(grupo.regras)) or "CPF"
    if len(cadastros) >= 2:
        ctx.ocorrencia(
            "CADASTROS_FUNDIDOS",
            ORIGEM_CLIENTES,
            f"Cadastros duplicados da mesma pessoa viraram um cliente só (regras: {regras}).",
            "CORRIGIDO",
            id_origem=_id_grupo(grupo),
            original=" · ".join(f"{r.origem.split(':')[1]} linha {r.id_origem}" for r in cadastros),
            final=f"cliente {cliente.id}",
        )
    elif grupo.regras - {"CPF"}:
        ctx.ocorrencia(
            "IDENTIFICADORES_LIGADOS",
            ORIGEM_REFERENCIA,
            f"E-mail/telefone das vendas ou do atendimento ligados ao mesmo cliente (regras: {regras}).",
            "MANTIDO",
            id_origem=_id_grupo(grupo),
            original=" · ".join(sorted(f"{r.origem.split(':')[-1]} {r.id_origem}" for r in grupo.registros))[:2000],
            final=f"cliente {cliente.id}",
        )


def _conta_pontos(db: Session, cliente: m.Cliente, grupo: Grupo) -> int:
    conta = db.scalar(select(m.ContaPontos).where(m.ContaPontos.cliente_id == cliente.id))
    if conta is None:
        conta = m.ContaPontos(cliente_id=cliente.id, saldo=0)
        db.add(conta)
    conta.categoria_declarada = grupo.mais_recente("categoria_declarada")
    return 1
