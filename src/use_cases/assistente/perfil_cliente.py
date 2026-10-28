"""O que a Lúcia já sabe do cliente logado, para a conversa começar do ponto dele (decisão 100).

- Pontos Lupe+ vencendo nos próximos 30 dias: a mesma conta do aviso por e-mail (avisos_pontos), só lendo. Ponto
  que vence sem uso é a dor do CRM; a saudação lembra antes de vencer.
- Tamanho que costuma levar, por tipo de peça: o mais comprado nos pedidos não cancelados. Serve de sugestão
  ("Camisas no M"), nunca de certeza: o cliente pode estar comprando para outra pessoa.
- O pedido em andamento mais recente (em separação ou enviado), o "cadê meu pedido?" mais comum.

Nada aqui grava: abrir o chat não lança vencimento de pontos nem mexe em pedido.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from src import models as m
from src.entities import fidelidade as regra_pontos
from src.entities.busca import ROTULO_TIPO, TIPOS_COM_TAMANHO, tipo_da_peca
from src.repositories import fidelidade_repository, pedido_repository
from src.use_cases.assistente.formatacao import brl, data, numero
from src.use_cases.fidelidade import lotes_em_aberto
from src.utils.datas import hoje

EM_ANDAMENTO = ("PROCESSANDO", "ENVIADO")


@dataclass
class Perfil:
    primeiro_nome: str | None = None
    # (tipo, tamanho), do tipo mais comprado para o menos
    tamanhos: list[tuple[str, str]] = field(default_factory=list)
    pontos_vencendo: int = 0
    primeiro_vencimento: date | None = None
    datas_de_vencimento: int = 0
    saldo: int = 0
    pedido_em_andamento: str | None = None


def plural(tipo: str) -> str:
    """'calca' -> 'calças', 'moletom' -> 'moletons', 'macacao' -> 'macacões'."""
    rotulo = ROTULO_TIPO.get(tipo, tipo)
    if rotulo.endswith("ão"):
        return rotulo[:-2] + "ões"
    if rotulo.endswith("m"):
        return rotulo[:-1] + "ns"
    if rotulo.endswith("r"):
        return rotulo + "es"
    return rotulo + "s"


def _tamanhos(pedidos: list[m.Pedido]) -> list[tuple[str, str]]:
    contagem: dict[str, Counter] = {}
    for pedido in pedidos:
        if pedido.status == "CANCELADO":
            continue
        for item in pedido.itens:
            tamanho = (item.variacao.tamanho or "").strip().upper()
            if not tamanho or tamanho in ("U", "UNICO", "ÚNICO"):
                continue
            tipo = next((t for t in tipo_da_peca(item.variacao.produto.nome) if t in TIPOS_COM_TAMANHO), None)
            if tipo:
                contagem.setdefault(tipo, Counter())[tamanho] += item.quantidade
    # Do tipo mais comprado para o menos; em cada tipo, o tamanho mais comprado (empate: o primeiro que apareceu,
    # que é o do pedido mais recente)
    ordem = sorted(contagem, key=lambda tipo: -sum(contagem[tipo].values()))
    return [(tipo, contagem[tipo].most_common(1)[0][0]) for tipo in ordem]


def perfil(db: Session, cliente: m.Cliente, referencia: date | None = None) -> Perfil:
    referencia = referencia or hoje()
    limite = referencia + timedelta(days=regra_pontos.AVISO_VENCIMENTO_DIAS)
    lotes = lotes_em_aberto(fidelidade_repository.movimentos(db, cliente.id))
    vencendo = sorted((vence, pontos) for vence, pontos in lotes if referencia <= vence <= limite)
    pedidos = pedido_repository.do_cliente(db, cliente.id)  # do mais recente para o mais antigo
    andamento = next((p.numero for p in pedidos if p.status in EM_ANDAMENTO), None)
    return Perfil(
        primeiro_nome=cliente.nome.split()[0] if cliente.nome else None,
        tamanhos=_tamanhos(pedidos),
        pontos_vencendo=sum(pontos for _, pontos in vencendo),
        primeiro_vencimento=vencendo[0][0] if vencendo else None,
        datas_de_vencimento=len({vence for vence, _ in vencendo}),
        saldo=sum(pontos for vence, pontos in lotes if vence >= referencia),
        pedido_em_andamento=andamento,
    )


def frase_dos_pontos(p: Perfil) -> str | None:
    if not p.pontos_vencendo:
        return None
    pontos = f"{numero(p.pontos_vencendo)} {'ponto' if p.pontos_vencendo == 1 else 'pontos'} {regra_pontos.NOME_PROGRAMA}"
    if p.datas_de_vencimento == 1:
        frase = f"Você tem {pontos} que vencem em {data(p.primeiro_vencimento)}"
    else:
        frase = f"Você tem {pontos} vencendo nos próximos {regra_pontos.AVISO_VENCIMENTO_DIAS} dias (os primeiros em {data(p.primeiro_vencimento)})"
    if p.saldo >= regra_pontos.RESGATE_MULTIPLO:
        frase += f": dá para usar no checkout, em compras a partir de {brl(regra_pontos.COMPRA_MINIMA_RESGATE)}"
    return frase + "."


def saudacao(p: Perfil, nome_assistente: str, sugestoes_padrao: list[str]) -> tuple[str, list[str]]:
    """(texto, sugestões) da primeira mensagem para o cliente logado."""
    partes = [f"Oi, {p.primeiro_nome}!" if p.primeiro_nome else "Oi!"]
    partes.append(f"Aqui é a {nome_assistente}, assistente virtual da Casa Lorenzi e da Vulto.")
    if frase := frase_dos_pontos(p):
        partes.append(frase)
    partes.append(
        "Posso encontrar peças, ver se tem na sua loja, acompanhar seus pedidos e consultar seus pontos. O que você procura?"
    )
    sugestoes = []
    if p.pontos_vencendo:
        sugestoes.append(f"Como uso meus pontos {regra_pontos.NOME_PROGRAMA}?")
    if p.pedido_em_andamento:
        sugestoes.append(f"Onde está o pedido {p.pedido_em_andamento}?")
    if p.tamanhos:
        tipo, tamanho = p.tamanhos[0]
        sugestoes.append(f"{plural(tipo).capitalize()} no {tamanho}")
    pontos_ja = any("pontos" in s.lower() for s in sugestoes)
    for padrao in sugestoes_padrao:
        if len(sugestoes) >= 4:
            break
        if pontos_ja and "pontos" in padrao.lower():
            continue
        sugestoes.append(padrao)
    return " ".join(partes), sugestoes


def linhas_do_contexto(p: Perfil) -> list[str]:
    """O perfil no contexto do modelo (do sistema: é fonte para o verificador de números)."""
    linhas = []
    if p.tamanhos:
        tamanhos = "; ".join(f"{plural(tipo)} {tamanho}" for tipo, tamanho in p.tamanhos[:4])
        linhas.append(
            f"- Tamanhos que o cliente costuma comprar: {tamanhos}. Use como sugestão quando ele não disser o tamanho "
            '("você costuma levar M; quer ver nele?"), nunca como certeza: ele pode estar comprando para outra pessoa.'
        )
    if frase := frase_dos_pontos(p):
        linhas.append(f"- Pontos {regra_pontos.NOME_PROGRAMA} a vencer: {frase}")
    if p.pedido_em_andamento:
        linhas.append(f"- Pedido em andamento mais recente: {p.pedido_em_andamento}.")
    return linhas


def tamanho_habitual(db: Session, cliente_id: int, tipos: list[str]) -> str | None:
    """O tamanho que o cliente costuma levar no tipo buscado (o primeiro dos tipos que ele já comprou)."""
    habituais = dict(_tamanhos(pedido_repository.do_cliente(db, cliente_id)))
    return next((habituais[t] for t in tipos if t in habituais), None)
