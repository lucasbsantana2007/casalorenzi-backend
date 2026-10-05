"""Popula o banco com os mesmos dados de demonstração do frontend (src/data/seed).

Uso:
    python -m app.seed            # só popula se o banco estiver vazio
    python -m app.seed --recriar  # apaga todos os dados e popula de novo

O gerador pseudoaleatório é o mesmo do frontend (mulberry32 com as mesmas
sementes), então produtos, histórico de estoque, pedidos e atendimentos ficam
idênticos aos da camada de mocks. As datas são relativas ao momento da carga.

Todas as contas usam a senha "lorenzi2026".
"""

import argparse
import math
import unicodedata
from datetime import date, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import models as m
from app.config import FUSO
from app.database import Base, SessionLocal
from app.security import gerar_hash
from app.utils import de_ms

SENHA_DEMO = "lorenzi2026"
DIA = 86_400_000
HISTORICO_DIAS = 75

LOJAS = [
    (1, "Oscar Freire", "São Paulo", "SP"),
    (2, "Iguatemi São Paulo", "São Paulo", "SP"),
    (3, "Leblon", "Rio de Janeiro", "RJ"),
    (4, "Pátio Batel", "Curitiba", "PR"),
]

CATEGORIAS = ["Camisaria", "Alfaiataria", "Vestidos", "Tricô", "Malharia", "Saias", "Outerwear", "Acessórios"]

USUARIOS = [
    (1, "Helena Lorenzi", "helena@casalorenzi.com.br", "ADMINISTRADOR", None),
    (2, "Rafael Monteiro", "rafael.monteiro@casalorenzi.com.br", "LOJISTA", 1),
    (3, "Beatriz Carvalho", "beatriz.carvalho@casalorenzi.com.br", "LOJISTA", 2),
    (4, "André Siqueira", "andre.siqueira@casalorenzi.com.br", "LOJISTA", 3),
    (5, "Camila Rocha", "camila.rocha@casalorenzi.com.br", "LOJISTA", 4),
    (6, "Diego Almeida", "diego.almeida@casalorenzi.com.br", "OPERADOR", 1),
    (7, "Carla Nunes", "carla.nunes@casalorenzi.com.br", "OPERADOR", 3),
]

# id, nome, email, telefone, cliente desde, loja preferida
CLIENTES = [
    (101, "Mariana Costa", "mariana.costa@gmail.com", "(11) 98422-1937", "2021-03-14", 1),
    (102, "Ricardo Fonseca", "ricardo.fonseca@outlook.com", "(11) 99710-4402", "2019-11-02", 2),
    (103, "Juliana Prado", "ju.prado@gmail.com", "(21) 98134-7750", "2022-06-21", 3),
    (104, "Felipe Andrade", "felipe.andrade@icloud.com", "(41) 99288-3016", "2023-01-09", 4),
    (105, "Luiza Bastos", "luiza.bastos@gmail.com", "(21) 99640-2281", "2020-08-30", 3),
    (106, "Gustavo Tavares", "gustavo.tavares@gmail.com", "(11) 97455-6190", "2024-02-17", 1),
    (107, "Patrícia Moreira", "patricia.moreira@uol.com.br", "(11) 98820-5573", "2018-05-05", 2),
    (108, "Thiago Ribeiro", "thiago.ribeiro@gmail.com", "(41) 99107-8834", "2023-09-12", 4),
]

# As variações são tamanhos × cores. genero/estacao alimentam a vitrine.
PRODUTOS = [
    dict(id=1, genero="Masculino", estacao="Verão", nome="Camisa de Linho Toscana", categoria="Camisaria", preco=489, codigo="CML", tamanhos=["P", "M", "G"], cores=["Branco", "Azul Céu"]),
    dict(id=2, genero="Masculino", estacao="Atemporal", nome="Camisa Oxford Slim", categoria="Camisaria", preco=369, codigo="COX", tamanhos=["P", "M", "G"], cores=["Marinho"]),
    dict(id=3, genero="Masculino", estacao="Inverno", nome="Calça de Alfaiataria Lã Fria", categoria="Alfaiataria", preco=649, codigo="CAL", tamanhos=["40", "42", "44"], cores=["Grafite", "Marinho"]),
    dict(id=4, genero="Masculino", estacao="Inverno", nome="Blazer Milano", categoria="Alfaiataria", preco=1490, codigo="BLZ", tamanhos=["48", "50", "52"], cores=["Marinho"]),
    dict(id=5, genero="Feminino", estacao="Verão", nome="Vestido Midi de Seda", categoria="Vestidos", preco=1190, codigo="VMS", tamanhos=["P", "M", "G"], cores=["Off-white", "Verde Oliva"]),
    dict(id=6, genero="Feminino", estacao="Inverno", nome="Suéter de Cashmere Gola Careca", categoria="Tricô", preco=1290, codigo="SCC", tamanhos=["P", "M", "G"], cores=["Camel"]),
    dict(id=7, genero="Feminino", estacao="Inverno", nome="Cardigã de Lã Merino", categoria="Tricô", preco=789, codigo="CLM", tamanhos=["P", "M", "G"], cores=["Cinza Mescla"]),
    dict(id=8, genero="Masculino", estacao="Verão", nome="Polo Piquet Pima", categoria="Malharia", preco=329, codigo="PPP", tamanhos=["P", "M", "G"], cores=["Marinho", "Branco"]),
    dict(id=9, genero="Feminino", estacao="Atemporal", nome="Saia Plissada Midi", categoria="Saias", preco=559, codigo="SPM", tamanhos=["36", "38", "40"], cores=["Preto"]),
    dict(id=10, genero="Feminino", estacao="Inverno", nome="Trench Coat Gabardine", categoria="Outerwear", preco=2190, codigo="TRC", tamanhos=["P", "M", "G"], cores=["Bege"]),
    dict(id=11, genero="Masculino", estacao="Atemporal", nome="Cinto de Couro Trançado", categoria="Acessórios", preco=279, codigo="CCT", tamanhos=["90", "100"], cores=["Conhaque"]),
    dict(id=12, genero="Feminino", estacao="Verão", nome="Lenço de Seda Estampado", categoria="Acessórios", preco=349, codigo="LSE", tamanhos=["Único"], cores=["Azul Riviera"]),
    dict(id=13, genero="Masculino", estacao="Verão", nome="Bermuda de Sarja Resort", categoria="Alfaiataria", preco=399, codigo="BSR", tamanhos=["40", "42", "44"], cores=["Areia"], ativo=False),
]

# id, titulo, categoria, exige venda, ordem, descricao, conta no pós-venda
TIPOS_SOLICITACAO = [
    (1, "Troca de produto", "Pós-venda", True, 1, "Troca por outro tamanho, cor ou modelo.", "TROCA"),
    (2, "Devolução e reembolso", "Pós-venda", True, 2, "Devolução em até 30 dias após o recebimento.", "DEVOLUCAO"),
    (3, "Acompanhamento de entrega", "Pedidos", True, 3, "Dúvidas sobre prazo ou status do envio.", None),
    (4, "Ajuste de costura", "Serviços", True, 4, "Barra, ajuste de cintura ou mangas.", None),
    (5, "Reserva em outra loja", "Disponibilidade", False, 5, "Reservar uma peça disponível em outra unidade.", None),
    (6, "Dúvida sobre produto", "Informações", False, 6, "Medidas, composição e cuidados com a peça.", None),
    (7, "Reclamação", "Qualidade", False, 7, "Relate um problema com produto ou atendimento.", None),
]

# Roteiros de atendimento escritos à mão. autorTipo: CLIENTE | ATENDENTE | SISTEMA
ROTEIROS = [
    dict(cliente=101, tipo=1, status="EM_ANDAMENTO", responsavel=2, dias=2, pedido=0, mensagens=[
        ("CLIENTE", "Olá! Comprei o item {produto} ({cor}, tamanho {tamanho}), mas ficou grande. Gostaria de trocar por um tamanho menor, na mesma cor.", 0),
        ("ATENDENTE", "Oi, Mariana! Tudo bem? Verifiquei aqui e temos a numeração menor disponível na Oscar Freire. Posso separar para você retirar a partir de amanhã?", 3),
        ("CLIENTE", "Perfeito, pode separar sim. Passo aí na quinta à tarde.", 5),
    ]),
    dict(cliente=101, tipo=4, status="CONCLUIDO", responsavel=2, dias=21, pedido=1, mensagens=[
        ("CLIENTE", "Preciso de um pequeno ajuste no item {produto}. Vocês fazem na loja?", 0),
        ("ATENDENTE", "Fazemos sim! O ajuste é cortesia e fica pronto em até 5 dias úteis. Pode trazer a peça na Oscar Freire.", 2),
        ("SISTEMA", "Peça recebida para ajuste na loja Oscar Freire.", 30),
        ("ATENDENTE", "Mariana, sua peça já está pronta para retirada. Obrigado pela preferência!", 120),
    ]),
    dict(cliente=102, tipo=3, status="ABERTO", responsavel=None, dias=0, pedido=0, mensagens=[
        ("CLIENTE", "Meu pedido consta como enviado, mas o rastreio não atualiza há mais de uma semana. Podem verificar com a transportadora?", 0),
    ]),
    dict(cliente=103, tipo=5, status="AGUARDANDO_CLIENTE", responsavel=4, dias=1, pedido=None, mensagens=[
        ("CLIENTE", "Vi no site o vestido midi de seda verde oliva no tamanho P. Tem no Leblon? Se não tiver, conseguem trazer de outra loja?", 0),
        ("ATENDENTE", "Oi, Juliana! No Leblon não temos o P, mas a Oscar Freire tem uma peça. Consigo solicitar a transferência e ela chega em até 3 dias úteis. Posso seguir?", 4),
    ]),
    dict(cliente=104, tipo=2, status="EM_ANDAMENTO", responsavel=5, dias=3, pedido=0, mensagens=[
        ("CLIENTE", "Gostaria de devolver o item {produto}. O tamanho {tamanho} não serviu e não há numeração disponível para troca.", 0),
        ("ATENDENTE", "Felipe, recebemos sua solicitação. O reembolso é feito na mesma forma de pagamento após a conferência da peça na loja Pátio Batel.", 6),
    ]),
    dict(cliente=105, tipo=7, status="ABERTO", responsavel=None, dias=0, pedido=None, mensagens=[
        ("CLIENTE", "O suéter de cashmere que comprei começou a formar bolinhas depois de duas lavagens à mão, seguindo a etiqueta. Gostaria de uma avaliação.", 0),
    ]),
    dict(cliente=106, tipo=6, status="CONCLUIDO", responsavel=2, dias=9, pedido=None, mensagens=[
        ("CLIENTE", "Qual a composição do blazer Milano? Ele amassa muito em viagem?", 0),
        ("ATENDENTE", "Gustavo, o Blazer Milano é 98% lã fria e 2% elastano, com ótima recuperação. Recomendamos transportá-lo em capa e pendurá-lo ao chegar.", 1),
        ("CLIENTE", "Ótimo, obrigado!", 2),
    ]),
    dict(cliente=107, tipo=1, status="ABERTO", responsavel=None, dias=1, pedido=0, mensagens=[
        ("CLIENTE", "Ganhei o item {produto} de presente no tamanho {tamanho} e preciso trocar por outro tamanho. Tenho a nota fiscal.", 0),
    ]),
    dict(cliente=108, tipo=3, status="CONCLUIDO", responsavel=1, dias=15, pedido=1, mensagens=[
        ("CLIENTE", "Meu pedido ainda está em separação. Há previsão de envio?", 0),
        ("ATENDENTE", "Thiago, seu pedido foi despachado hoje. O código de rastreio já está disponível no portal.", 5),
    ]),
    dict(cliente=103, tipo=4, status="EM_ANDAMENTO", responsavel=4, dias=5, pedido=0, mensagens=[
        ("CLIENTE", "Gostaria de ajustar a cintura do item {produto}. É possível?", 0),
        ("ATENDENTE", "É possível sim, Juliana. Nossa costureira atende no Leblon às terças e quintas. Pode trazer a peça quando quiser.", 3),
        ("SISTEMA", "Peça recebida para ajuste na loja Leblon.", 50),
    ]),
    dict(cliente=102, tipo=6, status="AGUARDANDO_CLIENTE", responsavel=3, dias=4, pedido=None, mensagens=[
        ("CLIENTE", "O trench coat tem forro removível?", 0),
        ("ATENDENTE", "Ricardo, o forro não é removível, mas é em viscose leve, ideal para meia-estação. Quer que eu reserve um para você provar no Iguatemi?", 2),
    ]),
    dict(cliente=101, tipo=6, status="CONCLUIDO", responsavel=1, dias=40, pedido=None, mensagens=[
        ("CLIENTE", "O lenço de seda pode ser lavado à mão?", 0),
        ("ATENDENTE", "Recomendamos lavagem a seco para preservar a estampa e o brilho da seda.", 1),
    ]),
]


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


def _montar_variacoes() -> list[dict]:
    variacoes, vid = [], 1
    for produto in PRODUTOS:
        for cor in produto["cores"]:
            for tamanho in produto["tamanhos"]:
                sufixo = "U" if tamanho == "Único" else tamanho
                variacoes.append(dict(id=vid, produto_id=produto["id"], sku=f"CL-{produto['codigo']}-{_codigo_cor(cor)}-{sufixo}", tamanho=tamanho, cor=cor))
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
        (38, "CONCLUIDA"), (34, "CONCLUIDA"), (31, "CONCLUIDA"), (27, "CONCLUIDA"), (24, "CANCELADA"),
        (21, "CONCLUIDA"), (18, "CONCLUIDA"), (15, "CONCLUIDA"), (12, "CONCLUIDA"), (9, "CONCLUIDA"),
        (6, "CONCLUIDA"), (4, "EM_TRANSITO"), (3, "EM_TRANSITO"), (2, "EM_TRANSITO"), (1, "SOLICITADA"), (0, "SOLICITADA"),
    ]
    elegiveis = [v for v in variacoes if v["produto_id"] != 13]
    transferencias = []
    for indice, (dias, status) in enumerate(roteiro):
        origem = rand.int(1, 4)
        destino = rand.int(1, 4)
        if destino == origem:
            destino = (origem % 4) + 1
        hora = rand.int(9, 12)
        minuto = rand.int(0, 59)
        criado = relogio.dias_atras(dias, hora, minuto)
        recebido = criado + rand.int(20, 60) * 3_600_000 if status == "CONCLUIDA" else None
        variacao_id = rand.pick(elegiveis)["id"]
        quantidade = rand.int(1, 3)
        solicitante = rand.pick([1, 2, 3, 4, 5])
        observacao = rand.pick(["Cliente aguardando na loja de destino", "Reposição de grade", "Ajuste de mix para vitrine", ""])
        transferencias.append(dict(
            id=indice + 1, codigo=f"TRF-{indice + 1:04d}", variacao_id=variacao_id,
            loja_origem_id=origem, loja_destino_id=destino, quantidade=quantidade, status=status,
            solicitante_id=solicitante, responsavel_id=_operador(origem), criado=criado,
            enviado=criado + 2 * 3_600_000 if status in ("EM_TRANSITO", "CONCLUIDA") else None,
            recebido=recebido, observacao=observacao,
        ))
    return transferencias


def _eventos_aleatorios(rand: Aleatorio, relogio: Relogio, loja_id: int, produto: dict) -> list[dict]:
    eventos = []
    ativo = produto.get("ativo", True)
    intensidade = {1: 0.13, 2: 0.11, 3: 0.1, 4: 0.07}[loja_id] * (1 if ativo else 0.3)
    for dia in range(HISTORICO_DIAS - 1, -1, -1):
        if rand.chance(intensidade):
            quantidade = -(1 if rand.chance(0.85) else 2)
            hora, minuto = rand.int(10, 21), rand.int(0, 59)
            criado = relogio.dias_atras(dia, hora, minuto)
            eventos.append(dict(tipo="VENDA", quantidade=quantidade, criado=criado, origem=f"Venda PDV · cupom {rand.int(100000, 999999)}", usuario_id=_lojista(loja_id)))
        if rand.chance(0.012):
            hora, minuto = rand.int(11, 19), rand.int(0, 59)
            eventos.append(dict(tipo="DEVOLUCAO", quantidade=1, criado=relogio.dias_atras(dia, hora, minuto), origem="Devolução de cliente · troca de tamanho", usuario_id=_lojista(loja_id)))
    if ativo:
        for base in (55, 30, 9):
            if rand.chance(0.6):
                quantidade = rand.int(3, 6)
                dias = base + rand.int(-4, 4)
                minuto = rand.int(0, 59)
                criado = relogio.dias_atras(dias, 8, minuto)
                eventos.append(dict(tipo="ENTRADA", quantidade=quantidade, criado=criado, origem=f"Recebimento do CD · NF {rand.int(40000, 49999)}", usuario_id=_operador(loja_id)))
    if rand.chance(0.15):
        quantidade = rand.pick([-1, 1, -2])
        eventos.append(dict(tipo="AJUSTE", quantidade=quantidade, criado=relogio.dias_atras(rand.int(3, 40), 18, 30), origem="Inventário rotativo", usuario_id=_operador(loja_id)))
    return eventos


def _montar_estoque(relogio: Relogio, variacoes: list[dict]):
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
                    eventos.append(dict(tipo="TRANSFERENCIA_SAIDA", quantidade=-t["quantidade"], criado=t["enviado"], origem=rota, usuario_id=t["responsavel_id"], transferencia_id=t["id"]))
                if t["loja_destino_id"] == loja_id and t["recebido"]:
                    eventos.append(dict(tipo="TRANSFERENCIA_ENTRADA", quantidade=t["quantidade"], criado=t["recebido"], origem=rota, usuario_id=_operador(loja_id), transferencia_id=t["id"]))
            eventos.sort(key=lambda e: e["criado"])

            saldo = rand.int(5, 10) if produto.get("ativo", True) else rand.int(2, 5)
            registros = [dict(tipo="ENTRADA", quantidade=saldo, criado=relogio.dias_atras(HISTORICO_DIAS, 8, 0), origem="Carga inicial de inventário", usuario_id=1)]
            for evento in eventos:
                if saldo + evento["quantidade"] < 0:
                    if evento["tipo"] != "TRANSFERENCIA_SAIDA":
                        continue
                    registros.append(dict(tipo="ENTRADA", quantidade=-evento["quantidade"], criado=evento["criado"] - 3_600_000, origem="Recebimento do CD · reposição urgente", usuario_id=_operador(loja_id)))
                    saldo -= evento["quantidade"]
                registros.append(evento)
                saldo += evento["quantidade"]

            corrente = 0
            for registro in registros:
                corrente += registro["quantidade"]
                movimentacoes.append(dict(id=mov_id, estoque_id=eid, saldo=corrente, **registro))
                mov_id += 1

            minimo = 2 if produto["categoria"] == "Acessórios" else rand.int(2, 3)
            estoques.append(dict(id=eid, loja_id=loja_id, variacao_id=variacao["id"], quantidade=corrente, minimo=minimo, atualizado=registros[-1]["criado"]))

    return estoques, movimentacoes, transferencias


def _montar_pedidos(relogio: Relogio, variacoes: list[dict]) -> list[dict]:
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
        pedidos.append(dict(
            id=i + 1, numero=f"CL-{104820 + i * 7}", cliente_id=cliente[0],
            loja_id=cliente[5] if canal == "Loja física" else 1, canal=canal, status=status,
            criado=criado, rastreio=rastreio, itens=itens, total=sum(it["preco"] * it["quantidade"] for it in itens),
        ))
    return pedidos


def _preencher(texto: str, pedido: dict | None, variacoes: list[dict]) -> str:
    if not pedido:
        return texto
    variacao = next(v for v in variacoes if v["id"] == pedido["itens"][0]["variacao_id"])
    produto = _produto(variacao["produto_id"])
    return texto.replace("{produto}", produto["nome"]).replace("{cor}", variacao["cor"]).replace("{tamanho}", variacao["tamanho"])


def _montar_atendimentos(relogio: Relogio, pedidos: list[dict], variacoes: list[dict]):
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
            autor = roteiro["cliente"] if autor_tipo == "CLIENTE" else roteiro["responsavel"] if autor_tipo == "ATENDENTE" else None
            mensagens.append(dict(id=msg_id, atendimento_id=aid, autor_id=autor, autor_tipo=autor_tipo, conteudo=_preencher(conteudo, pedido, variacoes), enviado=enviado))
            msg_id += 1
        atendimentos.append(dict(
            id=aid, protocolo=f"ATD-{26000 + aid * 37:06d}", solicitante_id=roteiro["cliente"],
            responsavel_id=roteiro["responsavel"], tipo_id=roteiro["tipo"], status=roteiro["status"],
            pedido_id=pedido["id"] if pedido else None, loja_id=pedido["loja_id"] if pedido else cliente[5],
            criado=criado, atualizado=ultima,
        ))
    return atendimentos, mensagens


# ---------------------------------------------------------------------------
# Gravação no banco
# ---------------------------------------------------------------------------

def _ajustar_sequencias(db: Session) -> None:
    """Depois de inserir ids explícitos, o próximo id gerado pelo PostgreSQL precisa vir depois deles."""
    if db.get_bind().dialect.name != "postgresql":
        return
    for tabela in Base.metadata.sorted_tables:
        db.execute(text(
            f"SELECT setval(pg_get_serial_sequence('{tabela.name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {tabela.name}), 0) + 1, false)"
        ))


def apagar_tudo(db: Session) -> None:
    for tabela in reversed(Base.metadata.sorted_tables):
        db.execute(tabela.delete())


def popular(db: Session) -> None:
    relogio = Relogio()
    senha = gerar_hash(SENHA_DEMO)
    variacoes = _montar_variacoes()
    estoques, movimentacoes, transferencias = _montar_estoque(relogio, variacoes)
    pedidos = _montar_pedidos(relogio, variacoes)
    atendimentos, mensagens = _montar_atendimentos(relogio, pedidos, variacoes)

    db.add_all(m.Loja(id=i, nome=n, cidade=c, uf=uf) for i, n, c, uf in LOJAS)
    db.add_all(m.Categoria(id=i, nome=nome) for i, nome in enumerate(CATEGORIAS, start=1))
    db.flush()
    db.add_all(m.Usuario(id=i, nome=n, email=e, papel=p, loja_id=loja, senha_hash=senha) for i, n, e, p, loja in USUARIOS)
    db.add_all(
        m.Usuario(id=i, nome=n, email=e, papel="CLIENTE", telefone=tel, cliente_desde=date.fromisoformat(desde), loja_preferida_id=loja, senha_hash=senha)
        for i, n, e, tel, desde, loja in CLIENTES
    )
    categoria_id = {nome: i for i, nome in enumerate(CATEGORIAS, start=1)}
    db.add_all(
        m.Produto(id=p["id"], nome=p["nome"], categoria_id=categoria_id[p["categoria"]], preco_base=p["preco"], genero=p["genero"], estacao=p["estacao"], ativo=p.get("ativo", True))
        for p in PRODUTOS
    )
    db.flush()
    db.add_all(m.Variacao(**v) for v in variacoes)
    db.add_all(
        m.TipoSolicitacao(id=i, titulo=t, categoria=c, exige_venda=ev, ordem_exibicao=o, descricao=d, conta_pos_venda=pv, ativo=True)
        for i, t, c, ev, o, d, pv in TIPOS_SOLICITACAO
    )
    db.flush()
    db.add_all(
        m.Estoque(id=e["id"], loja_id=e["loja_id"], variacao_id=e["variacao_id"], quantidade=e["quantidade"], quantidade_min=e["minimo"], atualizado_em=de_ms(e["atualizado"]))
        for e in estoques
    )
    db.add_all(
        m.Transferencia(
            id=t["id"], codigo=t["codigo"], variacao_id=t["variacao_id"], loja_origem_id=t["loja_origem_id"],
            loja_destino_id=t["loja_destino_id"], quantidade=t["quantidade"], status=t["status"],
            solicitante_id=t["solicitante_id"], responsavel_id=t["responsavel_id"], observacao=t["observacao"],
            criado_em=de_ms(t["criado"]), enviado_em=t["enviado"] and de_ms(t["enviado"]), recebido_em=t["recebido"] and de_ms(t["recebido"]),
        )
        for t in transferencias
    )
    db.flush()
    db.add_all(
        m.Movimentacao(
            id=mv["id"], estoque_id=mv["estoque_id"], tipo=mv["tipo"], quantidade=mv["quantidade"], origem=mv["origem"],
            usuario_id=mv["usuario_id"], transferencia_id=mv.get("transferencia_id"), saldo_resultante=mv["saldo"], criado_em=de_ms(mv["criado"]),
        )
        for mv in movimentacoes
    )
    for p in pedidos:
        db.add(m.Pedido(
            id=p["id"], numero=p["numero"], cliente_id=p["cliente_id"], loja_id=p["loja_id"], canal=p["canal"], status=p["status"],
            codigo_rastreio=p["rastreio"], total=p["total"], criado_em=de_ms(p["criado"]),
            itens=[m.ItemPedido(variacao_id=it["variacao_id"], quantidade=it["quantidade"], preco_unitario=it["preco"]) for it in p["itens"]],
        ))
    db.flush()
    db.add_all(
        m.Atendimento(
            id=a["id"], protocolo=a["protocolo"], solicitante_id=a["solicitante_id"], responsavel_id=a["responsavel_id"],
            tipo_solicitacao_id=a["tipo_id"], status=a["status"], pedido_id=a["pedido_id"], loja_id=a["loja_id"],
            criado_em=de_ms(a["criado"]), atualizado_em=de_ms(a["atualizado"]),
        )
        for a in atendimentos
    )
    db.flush()
    db.add_all(
        m.Mensagem(id=x["id"], atendimento_id=x["atendimento_id"], autor_id=x["autor_id"], autor_tipo=x["autor_tipo"], conteudo=x["conteudo"], enviado_em=de_ms(x["enviado"]))
        for x in mensagens
    )
    db.flush()
    _ajustar_sequencias(db)


def main() -> None:
    parser = argparse.ArgumentParser(description="Popula o banco com os dados de demonstração.")
    parser.add_argument("--recriar", action="store_true", help="apaga todos os dados antes de popular")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.recriar:
            apagar_tudo(db)
        elif db.scalar(select(func.count()).select_from(m.Usuario)):
            print("O banco já tem dados. Use --recriar para apagar tudo e popular de novo.")
            return
        popular(db)
        db.commit()
        resumo = {
            "lojas": m.Loja, "produtos": m.Produto, "variações": m.Variacao, "estoques": m.Estoque,
            "movimentações": m.Movimentacao, "transferências": m.Transferencia, "pedidos": m.Pedido,
            "atendimentos": m.Atendimento, "usuários": m.Usuario,
        }
        contagens = ", ".join(f"{db.scalar(select(func.count()).select_from(t))} {nome}" for nome, t in resumo.items())
        print(f"Dados de demonstração carregados: {contagens}.")
        print(f"Senha de todas as contas: {SENHA_DEMO}")


if __name__ == "__main__":
    main()
