"""Carga única dos dados da Vulto na plataforma.

Fonte: o repositório da Vulto consertado pelo time (copy.vulto-legado-back), passado em --origem:
- data/vulto_corrigido.db: vendas, itens, pontos (pontos_mov), estoque em 01/10/2026 e entradas;
- data/vulto.db, tabelas padronizadas: catálogo, clientes, tipo e status das vendas, atendimentos,
  histórico do estoque e o registro de decisões 1 a 65;
- migracao/entrada/: a aba Resgates da planilha de fidelidade (desconto em reais de cada resgate,
  decisão 68) e a planilha manual da Batel (forma de pagamento das vendas feitas sem sistema).
Do próprio repositório vêm as decisões 66 em diante (docs/registro_decisoes_uniao.md).

Como cada dado vira dado da plataforma está em docs/banco_uniao_vulto.md (de/para).

Garantias:
- tudo numa transação só: ou entra tudo, ou nada;
- antes de gravar, confere os três números da diretoria contra a origem (faturamento jan/2025 a
  set/2026, estoque em 01/10/2026 e passivo de pontos) e as contagens de cada tabela; se algo não
  bater, desfaz tudo;
- roda uma vez só: se o de_para já tem registros da Vulto, recusa.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

from src import models as m
from src.entities.cliente import cpf_valido, normalizar_email
from src.entities.fidelidade import VALOR_PONTO
from src.entities.marca import VULTO

TZ = ZoneInfo("America/Sao_Paulo")
CENTAVO = Decimal("0.01")
INICIO_PERIODO = datetime(2025, 1, 1, tzinfo=TZ)
FIM_PERIODO = datetime(2026, 10, 1, tzinfo=TZ)  # exclusivo: jan/2025 a set/2026
DATA_POSICAO = datetime(2026, 10, 2, tzinfo=TZ)  # passivo "em 01/10/2026": tudo até o fim do dia
ULTIMO_ID_SISTEMA = 18598  # vendas acima disso no banco consertado são as manuais da Batel (BATEL-1 = 18599)

# Lojas da Vulto (id no sistema antigo → nome, cidade, UF, tipo). As "lojas" 5 (site) e 6 (app) viram canal.
LOJAS = {
    1: ("Vulto Pinheiros", "São Paulo", "SP", "LOJA"),
    2: ("Vulto Shopping Eldorado", "São Paulo", "SP", "LOJA"),
    3: ("Vulto Savassi", "Belo Horizonte", "MG", "LOJA"),
    4: ("Vulto Batel", "Curitiba", "PR", "LOJA"),
    7: ("CD Cajamar", "Cajamar", "SP", "CD"),
}
# Endereço, telefone e horários (a Vulto só guardava nome e cidade): dados de demonstração do case, para a
# página Lojas do site (/vulto/lojas). A migration b7a1c3d9e2f4 completa as lojas já carregadas.
CONTATO_LOJAS = {
    1: (
        "Rua dos Pinheiros, 1037 - Pinheiros, São Paulo - SP",
        "+55 11 94102-3381",
        ["Segunda a sábado: 10:00–21:00", "Domingo: 12:00–19:00"],
    ),
    2: (
        "Av. Rebouças, 3970, Piso Térreo - Pinheiros, São Paulo - SP",
        "+55 11 94102-3392",
        ["Segunda a sábado: 10:00–22:00", "Domingo: 14:00–20:00"],
    ),
    3: ("Rua Pernambuco, 1000 - Savassi, Belo Horizonte - MG", "+55 31 98820-4410", ["Segunda a sábado: 10:00–20:00"]),
    4: (
        "Av. do Batel, 1550 - Batel, Curitiba - PR",
        "+55 41 99731-2207",
        ["Segunda a sábado: 10:00–20:00", "Domingo: 12:00–18:00"],
    ),
}
LOJA_PELO_NOME = {"Pinheiros": 1, "Eldorado": 2, "Savassi": 3, "Batel": 4, "CD Cajamar": 7}
CD = 7
CANAL_PELA_LOJA = {5: "E-commerce", 6: "App"}

STATUS_VARIACAO = {
    "Ativo": "ATIVO",
    "Descontinuado": "DESCONTINUADO",
    "Fora do catálogo 2026": "FORA_DO_CATALOGO",
    "Só histórico": "SO_HISTORICO",
    "Criado na migração (contado sem cadastro)": "FORA_DO_CATALOGO",
}
# Decisão 70: margem mínima de 50% com o custo de nota (preço do modelo inteiro)
REAJUSTE_DECISAO_70 = {"ACE-004": "149.90", "CAL-008": "329.90", "CAL-020": "269.90", "CMS-003": "249.90"}

# Status da venda na Vulto → (status do pedido, status do pagamento). Decisão 73.
STATUS_VENDA = {
    "Concluída": ("ENTREGUE", "APROVADO"),
    "Sem status": ("ENTREGUE", "APROVADO"),
    "Cancelada": ("CANCELADO", "ESTORNADO"),
    "Aguardando pagamento": ("CANCELADO", "ESTORNADO"),
    "Estornada": ("CANCELADO", "ESTORNADO"),
    "Chargeback": ("CANCELADO", "CHARGEBACK"),
}
PAGAMENTO_BATEL = {
    "Pix": ("PIX", 1),
    "Crédito": ("CARTAO", 1),
    "Crédito 2x": ("CARTAO", 2),
    "Débito": ("DEBITO", 1),
    "Dinheiro": ("DINHEIRO", 1),
}
STATUS_ATENDIMENTO = {
    "Aberto": "ABERTO",
    "Em andamento": "EM_ANDAMENTO",
    "Aguardando cliente": "AGUARDANDO_CLIENTE",
    "Resolvido": "CONCLUIDO",
}
CANAL_ATENDIMENTO = {"WhatsApp": "WHATSAPP", "Instagram": "INSTAGRAM", "Email": "EMAIL"}
# Assunto da Vulto → tipo de solicitação que já existe na plataforma; os outros viram tipos novos, inativos
TIPO_PELO_ASSUNTO = {
    "Troca": "Troca de produto",
    "Devolução": "Devolução e reembolso",
    "Entrega e rastreio": "Acompanhamento de entrega",
    "Produto e estoque": "Dúvida sobre produto",
}
NOME_SEM_CADASTRO = "Cliente Vulto+ sem cadastro"

CAMPOS_DECISAO = ("numero", "oque", "onde", "quantos", "decidimos", "porque", "impacto", "tipo")
TIPO_DECISAO = {"automático": "AUTOMATICO", "padrão assumido": "PADRAO_ASSUMIDO", "negócio": "NEGOCIO"}
AREA_DECISAO = {
    **dict.fromkeys(range(1, 18), "VENDAS"),
    6: "FIDELIDADE",
    **dict.fromkeys(range(18, 22), "CLIENTES"),
    **dict.fromkeys(range(22, 27), "FIDELIDADE"),
    **dict.fromkeys(range(27, 38), "ESTOQUE"),
    35: "CATALOGO",
    37: "CATALOGO",
    38: "CATALOGO",
    39: "CATALOGO",
    40: "FIDELIDADE",
    41: "FIDELIDADE",
    42: "ATENDIMENTO",
    43: "ATENDIMENTO",
    44: "ESTOQUE",
    45: "ESTOQUE",
    46: "GERAL",
    **dict.fromkeys(range(47, 51), "FIDELIDADE"),
    50: "CLIENTES",
    51: "CLIENTES",
    52: "CLIENTES",
    53: "CLIENTES",
    54: "ESTOQUE",
    # 55 a 65: equipe (acesso, cargos e contas), e-mail de cliente e regras do catálogo
    **dict.fromkeys(range(55, 61), "GERAL"),
    61: "CLIENTES",
    **dict.fromkeys(range(62, 66), "CATALOGO"),
    # 66 em diante: registro da união (docs/registro_decisoes_uniao.md)
    **dict.fromkeys(range(66, 69), "FIDELIDADE"),
    **dict.fromkeys(range(69, 72), "CATALOGO"),
    72: "CLIENTES",
    73: "VENDAS",
    74: "VENDAS",
    75: "GERAL",
    76: "VENDAS",
    **dict.fromkeys(range(77, 81), "FIDELIDADE"),
}


class CargaRecusada(Exception):
    """A carga não pode seguir (já foi feita, falta arquivo ou um número não bateu). Nada foi gravado."""


# ---------- conversões (funções puras, testadas em tests/test_migracao_vulto.py) ----------


def dinheiro(valor) -> Decimal | None:
    """'1.234,56', '559,70', 219.8 → Decimal com 2 casas; vazio → None."""
    if valor in (None, ""):
        return None
    texto = str(valor).strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    return Decimal(texto).quantize(CENTAVO, ROUND_HALF_UP)


def digitos(valor: str | None) -> str:
    return "".join(c for c in (valor or "") if c.isdigit())


def momento(texto: str) -> datetime:
    """'2025-01-01 09:04:39' (hora de Brasília, já convertida pelo time) → datetime com fuso."""
    return datetime.fromisoformat(texto).replace(tzinfo=TZ)


def estacao_da_colecao(colecao: str | None) -> str | None:
    if not colecao:
        return None
    if colecao.startswith("Verão"):
        return "Verão"
    if colecao.startswith("Inverno"):
        return "Inverno"
    return "Atemporal" if colecao == "Atemporais" else None


def mais_12_meses(quando: datetime) -> date:
    dia = quando.date()
    try:
        return dia.replace(year=dia.year + 1)
    except ValueError:  # 29/02
        return dia.replace(year=dia.year + 1, day=28)


def movimento_de_estoque(tipo: str) -> tuple[str, bool]:
    """Tipo do histórico reconstruído da Vulto → (tipo de movimentação, quantidade estimada?)."""
    if tipo.startswith("Saldo inicial"):
        return "SALDO_INICIAL", True
    if tipo in ("Venda", "Troca (peça nova)"):
        return "VENDA", False
    if tipo == "Devolução":
        return "DEVOLUCAO", False
    if tipo == "Compra (NF)":
        return "ENTRADA", False
    if tipo.startswith("Envio"):
        return "TRANSFERENCIA_SAIDA", False
    if tipo.startswith("Recebido"):
        return "TRANSFERENCIA_ENTRADA", False
    if tipo.startswith("Ajuste de inventário"):
        return "INVENTARIO", False
    if tipo.startswith("Avaria estimada"):
        return "AVARIA", True
    if tipo.startswith("Avaria"):
        return "AVARIA", False
    return "AJUSTE", False


def movimento_de_pontos(tipo: str, quantidade: int, obs: str) -> tuple[str, int]:
    """pontos_mov da Vulto (C, D gravado positivo, E já negativo, AJ) → (tipo, quantidade com sinal)."""
    if tipo == "C":
        return "CREDITO", quantidade
    if tipo == "D":
        return "RESGATE", -abs(quantidade)
    if tipo == "E":
        return "ESTORNO", -abs(quantidade)
    if obs.startswith("saldo da planilha"):
        return "SALDO_INICIAL", quantidade
    if obs.startswith("pontos vencidos"):
        return "VENCIMENTO", quantidade
    return "AJUSTE", quantidade


def ordem_dos_pontos(cpf: str, quando: str, quantidade: int, ident: int) -> tuple:
    """No mesmo instante, entradas antes das saídas: o ajuste "resgate maior que o saldo" tem o horário do
    resgate, e na ordem do id o saldo ficaria negativo por um instante (decisão 77)."""
    return cpf, quando, quantidade < 0, ident


def ler_decisoes_do_markdown(caminho: Path) -> list[dict]:
    """Linhas da tabela do registro (| # | o que | onde | quantos | decidimos | por quê | impacto | tipo |)."""
    decisoes = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\| \d+ \|", linha):
            continue
        celulas = [c.strip().replace("**", "") for c in linha.strip().strip("|").split(" | ")]
        if len(celulas) != 8:
            raise CargaRecusada(f"Linha do registro de decisões fora do formato: {linha[:60]}")
        decisoes.append(dict(zip(CAMPOS_DECISAO, celulas, strict=True)))
    return decisoes


# ---------- carga ----------


@dataclass
class Relatorio:
    contagens: dict[str, int] = field(default_factory=dict)
    numeros: dict[str, tuple] = field(default_factory=dict)  # nome → (origem, plataforma)
    avisos: Counter = field(default_factory=Counter)

    def linhas(self) -> list[str]:
        saida = [f"  {nome}: {qtd}" for nome, qtd in self.contagens.items()]
        saida += [
            f"  {nome}: origem {o} · plataforma {p} {'OK' if o == p else 'NÃO BATE'}" for nome, (o, p) in self.numeros.items()
        ]
        saida += [f"  aviso: {nome} ({qtd})" for nome, qtd in self.avisos.items()]
        return saida


class Carga:
    def __init__(self, db: Session, origem: Path, registro_uniao: Path):
        self.db = db
        self.origem = origem
        self.registro_uniao = registro_uniao
        arquivos = {
            "corrigido": origem / "data" / "vulto_corrigido.db",
            "padronizado": origem / "data" / "vulto.db",
            "fidelidade": origem / "migracao" / "entrada" / "clientes_fidelidade_FINAL_v3 (1).xlsx",
            "batel": origem / "migracao" / "entrada" / "vendas_batel_MANUAL_marco (2).xlsx",
            "registro": registro_uniao,
        }
        faltando = [str(c) for c in arquivos.values() if not c.exists()]
        if faltando:
            raise CargaRecusada("Arquivos da origem não encontrados: " + ", ".join(faltando))
        self.arquivos = arquivos
        self.C = sqlite3.connect(f"file:{arquivos['corrigido']}?mode=ro", uri=True)
        self.D = sqlite3.connect(f"file:{arquivos['padronizado']}?mode=ro", uri=True)
        self.rel = Relatorio()
        self.de_para: list[dict] = []
        self.loja: dict[int, int] = {}  # id da loja na Vulto → id aqui
        self.variacao: dict[str, int] = {}  # SKU → id
        self.cliente_por_cpf: dict[str, int] = {}
        self.cliente_por_email: dict[str, int] = {}
        self.pedido: dict[str, int] = {}  # chave da venda (id ou BATEL-n) → id do pedido
        self.itens_do_pedido: dict[int, list[tuple[int, int, int]]] = defaultdict(list)  # pedido → (item, variação, qtd)

    # ----- utilidades -----
    def _mapear(self, origem: str, id_origem, tabela: str, id_destino: int) -> None:
        self.de_para.append({"origem": origem, "id_origem": str(id_origem), "tabela_destino": tabela, "id_destino": id_destino})

    def _inserir(self, modelo, linhas: list[dict]) -> list[int]:
        """Grava em lote e devolve os ids na ordem das linhas. Os ids saem da própria sequência da tabela,
        reservados de uma vez, e cada INSERT leva até mil linhas: no banco do Render, longe daqui, uma
        viagem por linha (o que o executemany faz) levaria horas."""
        if not linhas:
            return []
        ids = list(
            self.db.scalars(
                text(f"SELECT nextval(pg_get_serial_sequence('{modelo.__tablename__}', 'id')) FROM generate_series(1, :n)"),
                {"n": len(linhas)},
            )
        )
        for linha, ident in zip(linhas, ids, strict=True):
            linha["id"] = ident
        lote = max(1, min(1000, 30000 // len(linhas[0])))  # o PostgreSQL aceita até 65.535 parâmetros por comando
        for inicio in range(0, len(linhas), lote):
            self.db.execute(insert(modelo).values(linhas[inicio : inicio + lote]))
        return ids

    # ----- etapas -----
    def conferir_que_nao_rodou(self) -> None:
        ja = self.db.scalar(select(func.count()).select_from(m.DePara).where(m.DePara.origem.like("vulto%")))
        if ja:
            raise CargaRecusada(f"A carga da Vulto já foi feita ({ja} registros no de_para). Ela roda uma vez só.")
        nomes = {nome for nome, *_ in LOJAS.values()}
        if self.db.scalar(select(func.count()).select_from(m.Loja).where(m.Loja.nome.in_(nomes))):
            raise CargaRecusada("Já existem lojas com os nomes das lojas da Vulto. Confira o banco antes de carregar.")

    def lojas(self) -> None:
        for vid, (nome, cidade, uf, tipo) in LOJAS.items():
            endereco, telefone, horarios = CONTATO_LOJAS.get(vid, ("", "", []))
            loja = m.Loja(
                nome=nome,
                cidade=cidade,
                uf=uf,
                marca=VULTO,
                tipo=tipo,
                ativa=True,
                endereco=endereco,
                telefone=telefone,
                horarios=list(horarios),
            )
            self.db.add(loja)
            self.db.flush()
            self.loja[vid] = loja.id
            self._mapear("vulto_corrigido.db:lojas", vid, "lojas", loja.id)
        self.rel.contagens["lojas"] = len(self.loja)

    def catalogo(self) -> None:
        categorias = {c.nome: c.id for c in self.db.scalars(select(m.Categoria))}
        fornecedores = {f.nome: f.id for f in self.db.scalars(select(m.Fornecedor))}
        linhas = [
            list(r)
            for r in self.D.execute(
                "select sku, codigo_cd, modelo, produto, categoria, cor, tamanho, preco, custo, ean, fornecedor, colecao, "
                "status, obs from produtos_padronizados order by rowid"
            )
        ]
        # Decisão 70: custo estimado → último custo de nota do próprio SKU; margem mínima → +R$ 10 em 4 modelos
        notas = {}
        for sku, custo in self.C.execute(
            "select sku, custo_unit from entradas_estoque where custo_unit not in ('', 'NaN') and custo_unit is not null "
            "order by data, id"
        ):
            notas[sku] = dinheiro(custo)  # a última nota (em ordem de data) fica
        for linha in linhas:
            obs = linha[13] or ""
            linha.append(False)  # [14] custo estimado
            if "Custo estimado" in obs or "Custo de refer" in obs:
                nota = notas.get(linha[0])
                if nota is not None:
                    linha[13] = f"{obs} · Custo de nota do próprio SKU: R$ {nota} (era R$ {linha[8]}, decisão 70)".strip(" ·")
                    linha[8] = float(nota)
                else:
                    linha[14] = True
            if linha[2] in REAJUSTE_DECISAO_70 and linha[12] == "Ativo":
                novo = REAJUSTE_DECISAO_70[linha[2]]
                linha[13] = f"{linha[13] or ''} · Preço de R$ {linha[7]:.2f} para R$ {novo} (margem mínima, decisão 70)".strip(
                    " ·"
                )
                linha[7] = float(novo)
        por_produto = defaultdict(list)
        for linha in linhas:
            por_produto[(linha[2], linha[3])].append(linha)

        for skus in por_produto.values():
            categoria = skus[0][4] or "Peças não identificadas"
            if categoria not in categorias:
                nova = m.Categoria(nome=categoria)
                self.db.add(nova)
                self.db.flush()
                categorias[categoria] = nova.id
            fornecedor = skus[0][10]
            if fornecedor and fornecedor not in fornecedores:
                novo = m.Fornecedor(nome=fornecedor)
                self.db.add(novo)
                self.db.flush()
                fornecedores[fornecedor] = novo.id

        produtos, precos_base = [], []
        for (modelo, nome), skus in por_produto.items():
            precos = Counter(Decimal(str(s[7])).quantize(CENTAVO) for s in skus if s[7] is not None)
            preco_base = precos.most_common(1)[0][0] if precos else Decimal("0.00")
            precos_base.append(preco_base)
            colecoes = sorted({s[11] for s in skus if s[11]})
            colecao = colecoes[-1] if colecoes else None
            produtos.append(
                {
                    "nome": nome,
                    "categoria_id": categorias[skus[0][4] or "Peças não identificadas"],
                    "preco_base": preco_base,
                    "marca": VULTO,
                    "codigo_modelo": modelo or None,
                    "colecao": colecao,
                    "estacao": estacao_da_colecao(colecao),
                    "fornecedor_id": fornecedores.get(skus[0][10]),
                    "fornecedor_estimado": any("Fornecedor estimado" in (s[13] or "") for s in skus),
                    "ativo": any(STATUS_VARIACAO[s[12]] != "SO_HISTORICO" for s in skus),
                }
            )
        ids_produtos = self._inserir(m.Produto, produtos)

        variacoes = []
        for produto_id, preco_base, ((modelo, nome), skus) in zip(ids_produtos, precos_base, por_produto.items(), strict=True):
            self._mapear("vulto.db:produtos_padronizados", f"{modelo}|{nome}", "produtos", produto_id)
            for s in skus:
                preco = Decimal(str(s[7])).quantize(CENTAVO) if s[7] is not None else None
                variacoes.append(
                    {
                        "produto_id": produto_id,
                        "sku": s[0],
                        "tamanho": s[6] or "U",
                        "cor": s[5] or "-",
                        "preco_custo": Decimal(str(s[8])).quantize(CENTAVO) if s[8] is not None else None,
                        "custo_estimado": s[14],
                        "preco": preco if preco is not None and preco != preco_base else None,
                        "ean": s[9] or None,
                        "codigo_cd": s[1] or None,
                        "status": STATUS_VARIACAO[s[12]],
                        "observacao": s[13] or None,
                    }
                )
        for linha, variacao_id in zip(variacoes, self._inserir(m.Variacao, variacoes), strict=True):
            self.variacao[linha["sku"]] = variacao_id
            self._mapear("vulto.db:produtos_padronizados", linha["sku"], "variacoes", variacao_id)
        self.rel.contagens["produtos"] = len(produtos)
        self.rel.contagens["variações"] = len(self.variacao)

    def clientes(self) -> None:
        existentes = {c.cpf: c for c in self.db.scalars(select(m.Cliente).where(m.Cliente.cpf.is_not(None)))}
        primeiro_ponto = dict(self.C.execute("select cpf, min(criado_em) from pontos_mov group by cpf"))
        novos, cpfs_novos, vistos, unidos = [], [], set(), 0
        for cpf_fmt, nome, email, tel, desde, loja_nome, aceita, obs in self.D.execute(
            "select cpf, nome, e_mail, telefone, data_de_cadastro, loja_de_cadastro, aceita_mensagem, obs "
            "from clientes_padronizados order by rowid"
        ):
            cpf = digitos(cpf_fmt)
            email = normalizar_email(email) or None
            sem_cadastro = nome == "(sem cadastro na planilha)"
            loja_vid = LOJA_PELO_NOME.get(loja_nome)
            canal = {"Site": "E-commerce", "App": "App"}.get(loja_nome, "Loja física" if loja_vid else None)
            if cpf in existentes:  # mesmo CPF da Casa Lorenzi: o mesmo cliente (completa o que falta)
                cliente = existentes[cpf]
                cliente.email = cliente.email or email
                cliente.telefone = cliente.telefone or tel
                cliente.aceita_marketing = cliente.aceita_marketing or aceita == "Sim"
                if obs:
                    cliente.observacao = f"{cliente.observacao} · Vulto+: {obs}" if cliente.observacao else f"Vulto+: {obs}"
                self.cliente_por_cpf[cpf] = cliente.id
                self._mapear("vulto.db:clientes_padronizados", cpf_fmt, "clientes", cliente.id)
                unidos += 1
                continue
            if cpf in vistos:
                raise CargaRecusada(f"CPF repetido no cadastro da Vulto: {cpf_fmt}.")
            vistos.add(cpf)
            inicio = desde or primeiro_ponto.get(cpf_fmt)
            novos.append(
                {
                    "cpf": cpf,
                    "nome": NOME_SEM_CADASTRO if sem_cadastro else nome,
                    "email": email,
                    "telefone": tel or None,
                    "cliente_desde": date.fromisoformat(inicio[:10]) if inicio else INICIO_PERIODO.date(),
                    "loja_preferida_id": self.loja.get(loja_vid),
                    "canal_cadastro": canal,
                    "aceita_marketing": aceita == "Sim",
                    "atualizar_cadastro": sem_cadastro or not cpf_valido(cpf),
                    "observacao": obs or None,
                }
            )
            cpfs_novos.append(cpf_fmt)
        self.db.flush()
        for cpf_fmt, linha, cliente_id in zip(cpfs_novos, novos, self._inserir(m.Cliente, novos), strict=True):
            self.cliente_por_cpf[linha["cpf"]] = cliente_id
            self._mapear("vulto.db:clientes_padronizados", cpf_fmt, "clientes", cliente_id)
        novos = len(novos)
        emails = Counter(e for (e,) in self.db.execute(select(m.Cliente.email).where(m.Cliente.email.is_not(None))))
        self.cliente_por_email = {
            c.email: c.id for c in self.db.scalars(select(m.Cliente).where(m.Cliente.email.is_not(None))) if emails[c.email] == 1
        }
        self.rel.contagens["clientes novos"] = novos
        self.rel.contagens["clientes unidos a um cadastro da Casa Lorenzi (mesmo CPF)"] = unidos

    def _cliente_da_venda(self, cpf: str | None, ref: str | None) -> int | None:
        return self.cliente_por_cpf.get(digitos(cpf)) or self.cliente_por_email.get(normalizar_email(ref))

    def vendas(self) -> None:
        padron = {
            r[0]: r[1:] for r in self.D.execute("select id_venda, tipo, cliente_cpf, venda_original from vendas_padronizadas")
        }
        pagamento_batel = {}
        for linha in self._planilha(self.arquivos["batel"], "Vendas Março", inicio=5):
            if isinstance(linha[0], int) and linha[9]:
                pagamento_batel[f"BATEL-{linha[0]}"] = PAGAMENTO_BATEL[linha[9]]
        itens = defaultdict(list)
        for venda_id, sku, qtd, preco in self.C.execute("select venda_id, sku, qtd, preco_unit from itens_venda order by id"):
            itens[venda_id].append((sku, qtd, dinheiro(preco)))

        pedidos, devolucoes, chaves = [], [], []
        for vid, externo, loja, ref, vendedor, total, desconto, frete, status, criado, obs in self.C.execute(
            "select id, pedido_externo, loja_id, cliente_ref, vendedor, total, desconto, frete, status, criado_em, obs "
            "from vendas order by id"
        ):
            chave = str(vid) if vid <= ULTIMO_ID_SISTEMA else f"BATEL-{vid - ULTIMO_ID_SISTEMA}"
            tipo, cpf_cliente, original = padron[chave]
            total = dinheiro(total)
            if tipo == "Devolução":
                devolucoes.append((vid, chave, loja, total, status, criado, obs, original))
                continue
            if not itens[vid]:
                raise CargaRecusada(f"A venda {chave} não tem itens.")
            subtotal = sum((Decimal(q) * p for _, q, p in itens[vid]), Decimal("0.00"))
            desconto = dinheiro(desconto) or Decimal("0.00")
            frete = (dinheiro(frete) or Decimal("0.00")) if loja in CANAL_PELA_LOJA else None
            if subtotal - desconto + (frete or 0) != total:
                raise CargaRecusada(
                    f"A venda {chave} não fecha: itens {subtotal} − desconto {desconto} + frete {frete} ≠ {total}."
                )
            ship_from_store = loja == 5 and "pin" in (obs or "").lower()
            loja_aqui = self.loja[1] if ship_from_store else self.loja[loja if loja in LOJAS else CD]
            cliente = self._cliente_da_venda(cpf_cliente, ref)
            st_pedido, _ = STATUS_VENDA[status]
            numero = externo or (chave if chave.startswith("BATEL") else f"VLT-{vid}")
            pedidos.append(
                {
                    "numero": numero,
                    "cliente_id": cliente,
                    "cliente_contato": None if cliente else (ref or None),
                    "loja_id": loja_aqui,
                    "canal": CANAL_PELA_LOJA.get(loja, "Loja física"),
                    "tipo": "TROCA" if tipo == "Troca" else "VENDA",
                    "status": st_pedido,
                    "status_origem": status,
                    "subtotal": subtotal,
                    "desconto": desconto,
                    "frete_valor": frete,
                    "total": total,
                    "vendedor_nome": vendedor or None,
                    "observacao": obs or None,
                    "criado_em": momento(criado),
                }
            )
            chaves.append((vid, chave, status))
        ids = self._inserir(m.Pedido, pedidos)
        linhas_itens, pagamentos, dono_dos_itens = [], [], []
        for pedido_id, dados, (vid, chave, status) in zip(ids, pedidos, chaves, strict=True):
            self.pedido[chave] = pedido_id
            self._mapear("vulto_corrigido.db:vendas", vid, "pedidos", pedido_id)
            for sku, qtd, preco in itens[vid]:
                if sku not in self.variacao:
                    raise CargaRecusada(f"O item {sku} da venda {chave} não está no catálogo.")
                linhas_itens.append(
                    {"pedido_id": pedido_id, "variacao_id": self.variacao[sku], "quantidade": qtd, "preco_unitario": preco}
                )
                dono_dos_itens.append(pedido_id)
            metodo, parcelas = pagamento_batel.get(chave, ("NAO_INFORMADO", 1))
            pagamentos.append(
                {
                    "pedido_id": pedido_id,
                    "metodo": metodo,
                    "valor": dados["total"],
                    "parcelas": parcelas,
                    "status": STATUS_VENDA[status][1],
                    "criado_em": dados["criado_em"],
                    "atualizado_em": dados["criado_em"],
                }
            )
        for item_id, pedido_id, linha in zip(
            self._inserir(m.ItemPedido, linhas_itens), dono_dos_itens, linhas_itens, strict=True
        ):
            self.itens_do_pedido[pedido_id].append((item_id, linha["variacao_id"], linha["quantidade"]))
        self._inserir(m.Pagamento, pagamentos)
        self.rel.contagens["pedidos"] = len(ids)
        self.rel.contagens["itens de pedido"] = len(linhas_itens)
        self.rel.contagens["vendas sem cliente identificado"] = sum(1 for p in pedidos if p["cliente_id"] is None)
        self._devolucoes(devolucoes, itens)

    def _devolucoes(self, devolucoes, itens) -> None:
        linhas, origem = [], []
        devolvido_por_item = Counter()
        for vid, chave, loja, total, status, criado, obs, original in devolucoes:
            if status == "Estornada":  # não conta no faturamento (decisão 74)
                self.rel.avisos["devolução estornada, não entra"] += 1
                continue
            pecas = itens[vid]
            if not pecas:
                raise CargaRecusada(f"A devolução {chave} não tem itens.")
            base = sum((abs(Decimal(q) * p) for _, q, p in pecas), Decimal("0.00"))
            restante = abs(total)
            pedido_id = self.pedido.get(original) if original else None
            for i, (sku, qtd, preco) in enumerate(pecas):
                valor = (
                    restante
                    if i == len(pecas) - 1
                    else (abs(total) * abs(Decimal(qtd) * preco) / base).quantize(CENTAVO, ROUND_HALF_UP)
                )
                restante -= valor
                variacao = self.variacao[sku]
                item_id = None
                for item, var, comprado in self.itens_do_pedido.get(pedido_id, []):
                    if var == variacao and devolvido_por_item[item] + abs(qtd) <= comprado:
                        item_id = item
                        devolvido_por_item[item] += abs(qtd)
                        break
                linhas.append(
                    {
                        "item_pedido_id": item_id,
                        "pedido_id": pedido_id,
                        "variacao_id": variacao,
                        "loja_id": self.loja[loja if loja in LOJAS else CD],
                        "quantidade": abs(qtd),
                        "valor_devolvido": valor,
                        "motivo": obs or "",
                        "criada_em": momento(criado),
                    }
                )
                origem.append(f"{vid}:{i + 1}")
        for id_origem, novo in zip(origem, self._inserir(m.Devolucao, linhas), strict=True):
            self._mapear("vulto_corrigido.db:vendas", id_origem, "devolucoes", novo)
        self.rel.contagens["devoluções (peças)"] = len(linhas)
        self.rel.contagens["devoluções ligadas à venda original"] = sum(1 for d in linhas if d["pedido_id"])

    def estoque(self) -> None:
        oficial = {(loja, sku): qtd for sku, loja, qtd in self.C.execute("select sku, loja_id, qtd from estoque")}
        historico = self.D.execute(
            "select local, sku, data, tipo, qtd, saldo, origem from estoque_historico order by rowid"
        ).fetchall()
        final = {}
        for local, sku, _dia, _tipo, _qtd, saldo, _origem in historico:
            final[(LOJA_PELO_NOME[local], sku)] = saldo
        diferentes = [k for k in set(oficial) | set(final) if oficial.get(k, 0) != final.get(k, 0)]
        if diferentes:
            raise CargaRecusada(f"O histórico do estoque não fecha com a posição de 01/10 em {len(diferentes)} itens.")
        # Toda variação vendável existe, zerada, em todas as lojas da Vulto (como na Casa Lorenzi)
        vendaveis = [
            sku for (sku, status) in self.D.execute("select sku, status from produtos_padronizados") if status != "Só histórico"
        ]
        pares = sorted(set(oficial) | set(final) | {(loja, sku) for loja in LOJAS for sku in vendaveis})
        linhas = [
            {
                "loja_id": self.loja[loja],
                "variacao_id": self.variacao[sku],
                "quantidade": oficial.get((loja, sku), 0),
                "quantidade_min": 2,
                "atualizado_em": FIM_PERIODO,
            }
            for loja, sku in pares
        ]
        estoque_id = dict(zip(pares, self._inserir(m.Estoque, linhas), strict=True))
        movimentos = []
        for n, (local, sku, dia, tipo, qtd, saldo, origem) in enumerate(historico):
            tipo_aqui, estimado = movimento_de_estoque(tipo)
            pedido = self.pedido.get(origem[6:]) if origem.startswith("venda ") else None
            movimentos.append(
                {
                    "estoque_id": estoque_id[(LOJA_PELO_NOME[local], sku)],
                    "tipo": tipo_aqui,
                    "quantidade": qtd,
                    "origem": f"Vulto · {tipo} · {origem}"[:255],
                    "pedido_id": pedido,
                    "estimado": estimado,
                    "saldo_resultante": saldo,
                    # O histórico tem só o dia: meio-dia de Brasília, na ordem em que foi reconstruído
                    "criado_em": datetime.combine(date.fromisoformat(dia), time(12), TZ) + timedelta(microseconds=n),
                }
            )
        self._inserir(m.Movimentacao, movimentos)
        self.rel.contagens["itens de estoque"] = len(linhas)
        self.rel.contagens["movimentações de estoque"] = len(movimentos)

    def _planilha(self, arquivo: Path, aba: str, inicio: int):
        import openpyxl  # só a carga usa (requirements-dev.txt)

        livro = openpyxl.load_workbook(arquivo, read_only=True, data_only=True)
        return [(*r,) for r in livro[aba].iter_rows(min_row=inicio, values_only=True)]

    def pontos(self) -> None:
        # Resgates anotados pelas lojas: o desconto em reais e a loja de cada resgate (decisão 68)
        resgates = []
        for numero, linha in enumerate(self._planilha(self.arquivos["fidelidade"], "Resgates", inicio=2), start=2):
            data, cpf, _nome, pts, lancado, regra, _dif, loja = linha[:8]
            if data and cpf and pts:
                resgates.append(
                    {
                        "linha": numero,
                        "dia": data.date(),
                        "cpf": cpf,
                        "pontos": int(pts),
                        "lancado": dinheiro(lancado),
                        "regra": dinheiro(regra),
                        "loja": loja,
                        "usado": False,
                    }
                )
        por_linha = {r["linha"]: r for r in resgates}
        email_do_cpf = dict(self.D.execute("select cpf, e_mail from clientes_padronizados where e_mail <> ''"))
        descontos = defaultdict(list)  # (cpf ou e-mail, dia) → descontos das vendas
        for cpf, contato, data, desconto in self.D.execute(
            "select cliente_cpf, cliente_contato, data, desconto from vendas_padronizadas where tipo = 'Venda'"
        ):
            dia = datetime.strptime(data, "%d/%m/%Y").date()
            for chave in (cpf, contato):
                if chave:
                    descontos[(chave, dia)].append(dinheiro(desconto) or Decimal("0.00"))

        def valor_do_resgate(cpf: str, quando: datetime, pts: int, obs: str) -> tuple[Decimal | None, int | None]:
            achou = re.search(r"Resgates linha (\d+)", obs)
            planilha = por_linha.get(int(achou.group(1))) if achou else None
            if planilha is None:
                candidatos = [
                    r
                    for r in resgates
                    if not r["usado"] and r["cpf"] == cpf and r["pontos"] == pts and abs((r["dia"] - quando.date()).days) <= 45
                ]
                planilha = min(candidatos, key=lambda r: abs((r["dia"] - quando.date()).days), default=None)
            if planilha is not None:
                planilha["usado"] = True
            vendas = [
                d
                for k in (-1, 0, 1)
                for chave in (cpf, email_do_cpf.get(cpf))
                if chave
                for d in descontos.get((chave, quando.date() + timedelta(days=k)), [])
            ]
            esperados = {planilha["lancado"], planilha["regra"]} if planilha else {pts * VALOR_PONTO, pts * VALOR_PONTO * 2}
            da_venda = next((d for d in vendas if d in {e.quantize(CENTAVO) for e in esperados if e is not None}), None)
            valor = da_venda if da_venda is not None else (planilha["lancado"] if planilha else None)
            loja = self.loja.get(LOJA_PELO_NOME.get(planilha["loja"])) if planilha else None
            return valor, loja

        compra_venda = {c: v for v, c in self.C.execute("select id, compra_id from vendas where compra_id is not null")}
        linhas = sorted(
            self.C.execute("select id, cpf, tipo, qtd, compra_id, criado_em, obs from pontos_mov"),
            key=lambda r: ordem_dos_pontos(r[1], r[5], movimento_de_pontos(r[2], r[3], r[6] or "")[1], r[0]),
        )
        saldo = defaultdict(int)
        movimentos, origem = [], []
        for ident, cpf_fmt, tipo, qtd, compra_id, criado, obs in linhas:
            obs = obs or ""
            cpf = digitos(cpf_fmt)
            cliente = self.cliente_por_cpf.get(cpf)
            if cliente is None:
                raise CargaRecusada(f"Pontos do CPF {cpf_fmt} sem cliente no cadastro.")
            tipo_aqui, quantidade = movimento_de_pontos(tipo, qtd, obs)
            saldo[cliente] += quantidade
            if saldo[cliente] < 0:
                raise CargaRecusada(f"O saldo de pontos do CPF {cpf_fmt} ficaria negativo em {criado}.")
            quando = momento(criado)
            valor = loja = None
            if tipo_aqui == "RESGATE":
                valor, loja = valor_do_resgate(cpf_fmt, quando, -quantidade, obs)
            venda = compra_venda.get(compra_id)
            chave = (
                None if venda is None else (str(venda) if venda <= ULTIMO_ID_SISTEMA else f"BATEL-{venda - ULTIMO_ID_SISTEMA}")
            )
            movimentos.append(
                {
                    "cliente_id": cliente,
                    "tipo": tipo_aqui,
                    "quantidade": quantidade,
                    "saldo_resultante": saldo[cliente],
                    "vence_em": mais_12_meses(quando) if tipo_aqui in ("CREDITO", "SALDO_INICIAL") else None,
                    "pedido_id": self.pedido.get(chave) if chave else None,
                    "loja_id": loja,
                    "valor_desconto": valor,
                    "obs": obs,
                    "criado_em": quando,
                }
            )
            origem.append(ident)
        for ident, novo in zip(origem, self._inserir(m.MovimentoPontos, movimentos), strict=True):
            self._mapear("vulto_corrigido.db:pontos_mov", ident, "movimentos_pontos", novo)
        self.rel.contagens["movimentos de pontos"] = len(movimentos)
        self.rel.contagens["resgates com o desconto em reais"] = sum(1 for mv in movimentos if mv["valor_desconto"] is not None)

    def atendimento(self) -> None:
        tipos = {t.titulo: t.id for t in self.db.scalars(select(m.TipoSolicitacao))}
        ordem = (self.db.scalar(select(func.max(m.TipoSolicitacao.ordem_exibicao))) or 0) + 1
        loja_do_pedido = dict(
            self.db.execute(select(m.Pedido.id, m.Pedido.loja_id).where(m.Pedido.id.in_(list(self.pedido.values())))).all()
        )
        atendimentos, conversas = [], []
        for (
            aid,
            dia,
            hora,
            canal,
            contato,
            nome,
            cpf,
            assunto,
            msg,
            resp,
            status,
            atendente,
            citado,
            id_venda,
            confere,
            loja,
        ) in self.D.execute(
            "select id, data, hora, canal, contato, nome, cliente_cpf, assunto, mensagem_cliente, resposta_atendente, status, "
            "atendente, pedido, id_venda, venda_confere, loja_id from atendimentos_padronizados order by rowid"
        ):
            titulo = TIPO_PELO_ASSUNTO.get(assunto, assunto)
            if titulo not in tipos:
                novo = m.TipoSolicitacao(
                    titulo=titulo,
                    categoria="Atendimento Vulto",
                    descricao="",
                    exige_venda=False,
                    ordem_exibicao=ordem,
                    ativo=False,
                )
                self.db.add(novo)
                self.db.flush()
                tipos[titulo] = novo.id
                ordem += 1
            pedido = self.pedido.get(id_venda) if id_venda and not (confere or "").startswith("Não") else None
            quando = datetime.strptime(f"{dia} {hora}", "%d/%m/%Y %H:%M").replace(tzinfo=TZ)
            atendimentos.append(
                {
                    "protocolo": f"VLT-{aid}",
                    "cliente_id": self.cliente_por_cpf.get(digitos(cpf)),
                    "marca": VULTO,
                    "canal": CANAL_ATENDIMENTO[canal],
                    "contato": contato or None,
                    "contato_nome": None if nome in (None, "", "Não informado") else nome,
                    "pedido_citado": citado or None,
                    "pedido_id": pedido,
                    "loja_id": self.loja[loja] if loja in LOJAS else loja_do_pedido.get(pedido),
                    "tipo_solicitacao_id": tipos[titulo],
                    "status": STATUS_ATENDIMENTO[status],
                    "criado_em": quando,
                    "atualizado_em": quando,
                }
            )
            conversas.append((aid, quando, msg, resp, atendente))
        mensagens = []
        for (aid, quando, msg, resp, atendente), atendimento_id in zip(
            conversas, self._inserir(m.Atendimento, atendimentos), strict=True
        ):
            self._mapear("vulto.db:atendimentos_padronizados", aid, "atendimentos", atendimento_id)
            if msg:
                mensagens.append(
                    {
                        "atendimento_id": atendimento_id,
                        "autor_tipo": "CLIENTE",
                        "autor_nome": None,
                        "conteudo": msg,
                        "enviado_em": quando,
                    }
                )
            if resp:  # o "Bot Vulto" é automático: mensagem do sistema
                mensagens.append(
                    {
                        "atendimento_id": atendimento_id,
                        "autor_tipo": "SISTEMA" if atendente == "Bot Vulto" else "ATENDENTE",
                        "autor_nome": atendente or None,
                        "conteudo": resp,
                        "enviado_em": quando + timedelta(seconds=1),
                    }
                )
        self._inserir(m.Mensagem, mensagens)
        self.rel.contagens["atendimentos"] = len(atendimentos)
        self.rel.contagens["mensagens de atendimento"] = len(mensagens)

    def decisoes(self) -> None:
        decisoes = [
            dict(zip(CAMPOS_DECISAO, r, strict=True)) for r in self.D.execute("select * from registro_decisoes order by numero")
        ]
        decisoes += ler_decisoes_do_markdown(self.registro_uniao)
        numeros = [int(d["numero"]) for d in decisoes]
        if len(set(numeros)) != len(numeros):
            raise CargaRecusada("O registro de decisões tem números repetidos.")
        linhas = [
            {
                "numero": int(d["numero"]),
                "area": AREA_DECISAO.get(int(d["numero"]), "GERAL"),
                "o_que_encontramos": d["oque"],
                "onde": d["onde"],
                "quantos_registros": d["quantos"],
                "o_que_decidimos": d["decidimos"],
                "por_que": d["porque"],
                "impacto": d["impacto"],
                "tipo": TIPO_DECISAO[d["tipo"]],
                "situacao": "A_DECIDIR" if d["decidimos"].lstrip("*").startswith("A decidir") else "APLICADA",
            }
            for d in decisoes
        ]
        for linha, ident in zip(linhas, self._inserir(m.DecisaoMigracao, linhas), strict=True):
            self._mapear("registro_decisoes", linha["numero"], "decisoes_migracao", ident)
        self.rel.contagens["decisões no registro"] = len(decisoes)

    # ----- conferência -----
    def conferir(self) -> None:
        def periodo(s: str) -> bool:
            d = datetime.strptime(s, "%d/%m/%Y")
            return date(2025, 1, 1) <= d.date() < date(2026, 10, 1)

        fat_origem = sum(
            (
                dinheiro(v)
                for v, d in self.D.execute("select valor_total, data from vendas_padronizadas where entra_no_faturamento = 'Sim'")
                if periodo(d)
            ),
            Decimal("0.00"),
        )
        estoque_origem = self.C.execute("select sum(qtd) from estoque").fetchone()[0]
        passivo_origem = sum(
            movimento_de_pontos(t, q, o or "")[1] for t, q, o in self.C.execute("select tipo, qtd, obs from pontos_mov")
        )

        vendas = self.db.scalar(
            text(
                "SELECT COALESCE(SUM(p.total), 0) FROM pedidos p JOIN lojas l ON l.id = p.loja_id "
                "WHERE l.marca = 'VULTO' AND p.tipo = 'VENDA' AND p.status <> 'CANCELADO' "
                "AND p.criado_em >= :a AND p.criado_em < :b"
            ),
            {"a": INICIO_PERIODO, "b": FIM_PERIODO},
        )
        devolvido = self.db.scalar(
            text(
                "SELECT COALESCE(SUM(d.valor_devolvido), 0) FROM devolucoes d JOIN lojas l ON l.id = d.loja_id "
                "WHERE l.marca = 'VULTO' AND d.criada_em >= :a AND d.criada_em < :b"
            ),
            {"a": INICIO_PERIODO, "b": FIM_PERIODO},
        )
        estoque = self.db.scalar(
            text("SELECT COALESCE(SUM(e.quantidade), 0) FROM estoques e JOIN lojas l ON l.id = e.loja_id WHERE l.marca = 'VULTO'")
        )
        passivo = self.db.scalar(
            text(
                "SELECT COALESCE(SUM(saldo_resultante), 0) FROM (SELECT DISTINCT ON (mp.cliente_id) mp.saldo_resultante "
                "FROM movimentos_pontos mp WHERE mp.criado_em < :fim ORDER BY mp.cliente_id, mp.criado_em DESC, mp.id DESC) u"
            ),
            {"fim": DATA_POSICAO},
        )
        self.rel.numeros = {
            "faturamento jan/2025 a set/2026 (R$)": (fat_origem, vendas - devolvido),
            "estoque em 01/10/2026 (peças)": (int(estoque_origem), int(estoque)),
            "passivo Vulto+ em 01/10/2026 (pontos)": (int(passivo_origem), int(passivo)),
        }
        contagens = {
            "atendimentos": (
                self.D.execute("select count(*) from atendimentos_padronizados").fetchone()[0],
                self.rel.contagens["atendimentos"],
            ),
            "variações": (
                self.D.execute("select count(*) from produtos_padronizados").fetchone()[0],
                self.rel.contagens["variações"],
            ),
            "movimentos de pontos": (
                self.C.execute("select count(*) from pontos_mov").fetchone()[0],
                self.rel.contagens["movimentos de pontos"],
            ),
        }
        self.rel.numeros.update({f"contagem de {k}": v for k, v in contagens.items()})
        erradas = [nome for nome, (o, p) in self.rel.numeros.items() if o != p]
        if erradas:
            raise CargaRecusada("Não bateu com a origem: " + "; ".join(f"{n} {self.rel.numeros[n]}" for n in erradas))

    def executar(self, aviso=print) -> Relatorio:
        """aviso recebe uma linha por etapa concluída (com o tempo), para acompanhar a carga."""
        self.conferir_que_nao_rodou()
        etapas = (
            self.lojas,
            self.catalogo,
            self.clientes,
            self.vendas,
            self.estoque,
            self.pontos,
            self.atendimento,
            self.decisoes,
        )
        for etapa in etapas:
            inicio = monotonic()
            etapa()
            aviso(f"  {etapa.__name__}: {monotonic() - inicio:.0f}s")
        self._inserir(m.DePara, self.de_para)
        self.rel.contagens["registros no de_para"] = len(self.de_para)
        self.db.flush()
        self.conferir()
        return self.rel
