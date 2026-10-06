"""Monta o histórico de demonstração com o mesmo gerador pseudoaleatório do frontend
(mulberry32, mesmas sementes): estoque, transferências, pedidos e atendimentos ficam idênticos aos mocks."""

import math
import unicodedata
from datetime import datetime

from src.config.settings import FUSO
from src.database.seed.dados import CLIENTES, DIA, HISTORICO_DIAS, LOJAS, PRODUTOS, ROTEIROS, USUARIOS

# ---------------------------------------------------------------------------
# Gerador pseudoaleatório idêntico ao do frontend (src/data/seed/random.js)
# ---------------------------------------------------------------------------


def _i32(x: int) -> int:
    x &= 0xFFFFFFFF
    return x - 0x1_0000_0000 if x & 0x8000_0000 else x


def _imul(a: int, b: int) -> int:
    return _i32((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF))


def _ushr(x: int, n: int) -> int:
    return (x & 0xFFFFFFFF) >> n


class Aleatorio:
    """mulberry32, com os mesmos helpers int/pick/chance do frontend."""

    def __init__(self, semente: int):
        self.a = semente

    def __call__(self) -> float:
        self.a = _i32(self.a + 0x6D2B79F5)
        t = _imul(_i32(self.a ^ _ushr(self.a, 15)), 1 | self.a)
        t = _i32(_i32(t + _imul(_i32(t ^ _ushr(t, 7)), 61 | t)) ^ t)
        return _ushr(_i32(t ^ _ushr(t, 14)), 0) / 4294967296

    def int(self, minimo: int, maximo: int) -> int:
        return math.floor(self() * (maximo - minimo + 1)) + minimo

    def pick(self, lista):
        return lista[math.floor(self() * len(lista))]

    def chance(self, p: float) -> bool:
        return self() < p


class Relogio:
    """Datas relativas ao momento da carga, como o daysAgo() do frontend (em ms)."""

    def __init__(self):
        self.agora = int(datetime.now(FUSO).timestamp() * 1000)

    def dias_atras(self, dias: int, hora: int = 10, minuto: int = 0) -> int:
        d = datetime.fromtimestamp((self.agora - dias * DIA) / 1000, FUSO)
        d = d.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        t = int(d.timestamp() * 1000)
        # Horários de hoje que ainda não chegaram são distribuídos nas últimas horas
        if t > self.agora - 60_000:
            return self.agora - (((hora * 60 + minuto) % 240) + 3) * 60_000
        return t


def _arredonda_js(x: float) -> int:
    return math.floor(x + 0.5)


def _codigo_cor(cor: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", cor) if unicodedata.category(c) != "Mn")
    return sem_acento[:3].upper()


def montar_variacoes() -> list[dict]:
    variacoes, vid = [], 1
    for produto in PRODUTOS:
        for cor in produto["cores"]:
            for tamanho in produto["tamanhos"]:
                sufixo = "U" if tamanho == "Único" else tamanho
                variacoes.append(
                    dict(
                        id=vid,
                        produto_id=produto["id"],
                        sku=f"CL-{produto['codigo']}-{_codigo_cor(cor)}-{sufixo}",
                        tamanho=tamanho,
                        cor=cor,
                    )
                )
                vid += 1
    return variacoes


def _produto(produto_id: int) -> dict:
    return next(p for p in PRODUTOS if p["id"] == produto_id)


def _lojista(loja_id: int) -> int:
    return next(u[0] for u in USUARIOS if u[3] == "LOJISTA" and u[4] == loja_id)


def _operador(loja_id: int) -> int:
    return 6 if loja_id <= 2 else 7


def _nome_loja(loja_id: int) -> str:
    return next(nome for lid, nome, *_ in LOJAS if lid == loja_id)


def _montar_transferencias(rand: Aleatorio, relogio: Relogio, variacoes: list[dict]) -> list[dict]:
    roteiro = [
        (38, "CONCLUIDA"),
        (34, "CONCLUIDA"),
        (31, "CONCLUIDA"),
        (27, "CONCLUIDA"),
        (24, "CANCELADA"),
        (21, "CONCLUIDA"),
        (18, "CONCLUIDA"),
        (15, "CONCLUIDA"),
        (12, "CONCLUIDA"),
        (9, "CONCLUIDA"),
        (6, "CONCLUIDA"),
        (4, "EM_TRANSITO"),
        (3, "EM_TRANSITO"),
        (2, "EM_TRANSITO"),
        (1, "SOLICITADA"),
        (0, "SOLICITADA"),
    ]
    elegiveis = [v for v in variacoes if v["produto_id"] != 13]
    transferencias = []
    for indice, (dias, status) in enumerate(roteiro):
        origem = rand.int(1, len(LOJAS))
        destino = rand.int(1, len(LOJAS))
        if destino == origem:
            destino = (origem % len(LOJAS)) + 1
        hora = rand.int(9, 12)
        minuto = rand.int(0, 59)
        criado = relogio.dias_atras(dias, hora, minuto)
        recebido = criado + rand.int(20, 60) * 3_600_000 if status == "CONCLUIDA" else None
        variacao_id = rand.pick(elegiveis)["id"]
        quantidade = rand.int(1, 3)
        solicitante = rand.pick([1, 2, 3, 4, 5, 8])
        observacao = rand.pick(["Cliente aguardando na loja de destino", "Reposição de grade", "Ajuste de mix para vitrine", ""])
        transferencias.append(
            dict(
                id=indice + 1,
                codigo=f"TRF-{indice + 1:04d}",
                variacao_id=variacao_id,
                loja_origem_id=origem,
                loja_destino_id=destino,
                quantidade=quantidade,
                status=status,
                solicitante_id=solicitante,
                responsavel_id=_operador(origem),
                criado=criado,
                enviado=criado + 2 * 3_600_000 if status in ("EM_TRANSITO", "CONCLUIDA") else None,
                recebido=recebido,
                observacao=observacao,
            )
        )
    return transferencias


def _eventos_aleatorios(rand: Aleatorio, relogio: Relogio, loja_id: int, produto: dict) -> list[dict]:
    eventos = []
    ativo = produto.get("ativo", True)
    intensidade = {1: 0.13, 2: 0.11, 3: 0.1, 4: 0.07, 5: 0.09}[loja_id] * (1 if ativo else 0.3)
    for dia in range(HISTORICO_DIAS - 1, -1, -1):
        if rand.chance(intensidade):
            quantidade = -(1 if rand.chance(0.85) else 2)
            hora, minuto = rand.int(10, 21), rand.int(0, 59)
            criado = relogio.dias_atras(dia, hora, minuto)
            eventos.append(
                dict(
                    tipo="VENDA",
                    quantidade=quantidade,
                    criado=criado,
                    origem=f"Venda PDV · cupom {rand.int(100000, 999999)}",
                    usuario_id=_lojista(loja_id),
                )
            )
        if rand.chance(0.012):
            hora, minuto = rand.int(11, 19), rand.int(0, 59)
            eventos.append(
                dict(
                    tipo="DEVOLUCAO",
                    quantidade=1,
                    criado=relogio.dias_atras(dia, hora, minuto),
                    origem="Devolução de cliente · troca de tamanho",
                    usuario_id=_lojista(loja_id),
                )
            )
    if ativo:
        for base in (55, 30, 9):
            if rand.chance(0.6):
                quantidade = rand.int(3, 6)
                dias = base + rand.int(-4, 4)
                minuto = rand.int(0, 59)
                criado = relogio.dias_atras(dias, 8, minuto)
                eventos.append(
                    dict(
                        tipo="ENTRADA",
                        quantidade=quantidade,
                        criado=criado,
                        origem=f"Recebimento do CD · NF {rand.int(40000, 49999)}",
                        usuario_id=_operador(loja_id),
                    )
                )
    if rand.chance(0.15):
        quantidade = rand.pick([-1, 1, -2])
        eventos.append(
            dict(
                tipo="AJUSTE",
                quantidade=quantidade,
                criado=relogio.dias_atras(rand.int(3, 40), 18, 30),
                origem="Inventário rotativo",
                usuario_id=_operador(loja_id),
            )
        )
    return eventos


def montar_estoque(relogio: Relogio, variacoes: list[dict]):
    """Estoques e histórico completo: o saldo atual é sempre a soma das movimentações."""
    rand = Aleatorio(20260405)
    transferencias = _montar_transferencias(rand, relogio, variacoes)
    estoques, movimentacoes = [], []
    estoque_id = mov_id = 1

    for loja_id, *_ in LOJAS:
        for variacao in variacoes:
            produto = _produto(variacao["produto_id"])
            eid = estoque_id
            estoque_id += 1
            eventos = _eventos_aleatorios(rand, relogio, loja_id, produto)
            for t in transferencias:
                if t["variacao_id"] != variacao["id"]:
                    continue
                rota = f"{t['codigo']} · {_nome_loja(t['loja_origem_id'])} → {_nome_loja(t['loja_destino_id'])}"
                if t["loja_origem_id"] == loja_id and t["enviado"]:
                    eventos.append(
                        dict(
                            tipo="TRANSFERENCIA_SAIDA",
                            quantidade=-t["quantidade"],
                            criado=t["enviado"],
                            origem=rota,
                            usuario_id=t["responsavel_id"],
                            transferencia_id=t["id"],
                        )
                    )
                if t["loja_destino_id"] == loja_id and t["recebido"]:
                    eventos.append(
                        dict(
                            tipo="TRANSFERENCIA_ENTRADA",
                            quantidade=t["quantidade"],
                            criado=t["recebido"],
                            origem=rota,
                            usuario_id=_operador(loja_id),
                            transferencia_id=t["id"],
                        )
                    )
            eventos.sort(key=lambda e: e["criado"])

            saldo = rand.int(5, 10) if produto.get("ativo", True) else rand.int(2, 5)
            registros = [
                dict(
                    tipo="ENTRADA",
                    quantidade=saldo,
                    criado=relogio.dias_atras(HISTORICO_DIAS, 8, 0),
                    origem="Carga inicial de inventário",
                    usuario_id=1,
                )
            ]
            for evento in eventos:
                if saldo + evento["quantidade"] < 0:
                    if evento["tipo"] != "TRANSFERENCIA_SAIDA":
                        continue
                    registros.append(
                        dict(
                            tipo="ENTRADA",
                            quantidade=-evento["quantidade"],
                            criado=evento["criado"] - 3_600_000,
                            origem="Recebimento do CD · reposição urgente",
                            usuario_id=_operador(loja_id),
                        )
                    )
                    saldo -= evento["quantidade"]
                registros.append(evento)
                saldo += evento["quantidade"]

            corrente = 0
            for registro in registros:
                corrente += registro["quantidade"]
                movimentacoes.append(dict(id=mov_id, estoque_id=eid, saldo=corrente, **registro))
                mov_id += 1

            minimo = 2 if produto["categoria"] == "Acessórios" else rand.int(2, 3)
            estoques.append(
                dict(
                    id=eid,
                    loja_id=loja_id,
                    variacao_id=variacao["id"],
                    quantidade=corrente,
                    minimo=minimo,
                    atualizado=registros[-1]["criado"],
                )
            )

    return estoques, movimentacoes, transferencias


def montar_pedidos(relogio: Relogio, variacoes: list[dict]) -> list[dict]:
    rand = Aleatorio(1987)
    elegiveis = [v for v in variacoes if v["produto_id"] != 13]
    pedidos = []
    for i in range(40):
        cliente = CLIENTES[(i + 1) % len(CLIENTES)]
        dias = _arredonda_js(((40 - i) / 40) * 70) + rand.int(0, 2)
        canal = "E-commerce" if (i >= 30 or rand.chance(0.4)) else "Loja física"
        itens = []
        for _ in range(rand.int(1, 3)):
            variacao = rand.pick(elegiveis)
            itens.append(dict(variacao_id=variacao["id"], quantidade=1, preco=_produto(variacao["produto_id"])["preco"]))
        status = "ENTREGUE"
        if canal == "E-commerce" and dias <= 3:
            status = "PROCESSANDO"
        elif canal == "E-commerce" and dias <= 17:
            status = "ENVIADO"
        if i == 17:
            status = "CANCELADO"
        hora, minuto = rand.int(10, 20), rand.int(0, 59)
        criado = relogio.dias_atras(dias, hora, minuto)
        rastreio = f"BR{rand.int(100000000, 999999999)}SP" if canal == "E-commerce" and status != "PROCESSANDO" else None
        pedidos.append(
            dict(
                id=i + 1,
                numero=f"CL-{104820 + i * 7}",
                cliente_id=cliente[0],
                loja_id=cliente[5] if canal == "Loja física" else 1,
                canal=canal,
                status=status,
                criado=criado,
                rastreio=rastreio,
                itens=itens,
                total=sum(it["preco"] * it["quantidade"] for it in itens),
            )
        )
    return pedidos


def _preencher(texto: str, pedido: dict | None, variacoes: list[dict]) -> str:
    if not pedido:
        return texto
    variacao = next(v for v in variacoes if v["id"] == pedido["itens"][0]["variacao_id"])
    produto = _produto(variacao["produto_id"])
    return texto.replace("{produto}", produto["nome"]).replace("{cor}", variacao["cor"]).replace("{tamanho}", variacao["tamanho"])


def montar_atendimentos(relogio: Relogio, pedidos: list[dict], variacoes: list[dict]):
    rand = Aleatorio(4410)
    atendimentos, mensagens = [], []
    msg_id = 1
    for indice, roteiro in enumerate(ROTEIROS):
        aid = indice + 1
        cliente = next(c for c in CLIENTES if c[0] == roteiro["cliente"])
        do_cliente = [p for p in pedidos if p["cliente_id"] == roteiro["cliente"]]
        pedido = do_cliente[len(do_cliente) - 1 - roteiro["pedido"]] if roteiro["pedido"] is not None else None
        hora, minuto = rand.int(9, 15), rand.int(0, 59)
        criado = relogio.dias_atras(roteiro["dias"], hora, minuto)
        ultima = criado
        for autor_tipo, conteudo, horas in roteiro["mensagens"]:
            enviado = min(criado + horas * 3_600_000 + rand.int(0, 40) * 60_000, relogio.agora - 120_000)
            ultima = enviado
            autor = (
                roteiro["cliente"] if autor_tipo == "CLIENTE" else roteiro["responsavel"] if autor_tipo == "ATENDENTE" else None
            )
            mensagens.append(
                dict(
                    id=msg_id,
                    atendimento_id=aid,
                    autor_id=autor,
                    autor_tipo=autor_tipo,
                    conteudo=_preencher(conteudo, pedido, variacoes),
                    enviado=enviado,
                )
            )
            msg_id += 1
        atendimentos.append(
            dict(
                id=aid,
                protocolo=f"ATD-{26000 + aid * 37:06d}",
                solicitante_id=roteiro["cliente"],
                responsavel_id=roteiro["responsavel"],
                tipo_id=roteiro["tipo"],
                status=roteiro["status"],
                pedido_id=pedido["id"] if pedido else None,
                loja_id=pedido["loja_id"] if pedido else cliente[5],
                criado=criado,
                atualizado=ultima,
            )
        )
    return atendimentos, mensagens
