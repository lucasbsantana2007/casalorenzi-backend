"""Ferramentas do assistente do site (Casa Lorenzi + Vulto): catálogo, disponibilidade, lojas, políticas,
Lupe+ e pedidos do cliente logado, sacola e atendimento humano.

Dados pessoais (pontos, pedidos) saem só do cliente do token (Contexto.cliente_id): nenhuma ferramenta
recebe um id de cliente. Nenhuma ferramenta compra, cobra ou mexe em estoque: colocar_na_sacola confere a peça
e o navegador a coloca na sacola na hora, com Desfazer (decisão 94); a sacola é a do navegador (a mesma da
página do produto) e o pagamento continua no checkout. Atendimento humano é um botão: o chamado só é aberto
quando o cliente confirma.
"""

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field
from sqlalchemy.orm import Session

from src.config import settings
from src.entities import fidelidade as regra_pontos
from src.entities.busca import (
    TIPOS_COM_TAMANHO,
    PedidoBusca,
    descrever,
    familia_da_cor,
    interpretar_busca,
    normalizar_tamanho,
    tipo_da_peca,
)
from src.entities.pagamento import METODOS_ECOMMERCE, PARCELAS_MAX
from src.repositories import cadastro_repository, cliente_repository, pedido_repository
from src.schemas.produtos import imagem_url
from src.use_cases import fidelidade
from src.use_cases import frete as frete_config
from src.use_cases import produtos as produtos_uc
from src.use_cases.assistente import catalogo, perfil_cliente
from src.use_cases.assistente.ferramentas import Contexto, Entrada, FalhaFerramenta, Ferramenta, Resultado
from src.use_cases.assistente.formatacao import brl, data, numero
from src.utils.datas import hoje, ms
from src.utils.texto import normalizar

MAX_SACOLA = 5  # mesmo limite por peça da sacola do site (SacolaProvider)
ROTULO_STATUS_PEDIDO = {"PROCESSANDO": "Em separação", "ENVIADO": "Enviado", "ENTREGUE": "Entregue", "CANCELADO": "Cancelado"}
ROTULO_CATEGORIA = {"BRONZE": "Bronze", "PRATA": "Prata", "OURO": "Ouro", "VIP": "Vip"}

Marca = Literal["LORENZI", "VULTO"]


def _situacao_texto(situacao: str) -> str:
    return catalogo.ROTULO_SITUACAO.get(situacao, situacao).lower()


def _lista(itens: list[str], conector: str = "e") -> str:
    itens = [i for i in itens if i]
    if len(itens) <= 1:
        return "".join(itens)
    return f"{', '.join(itens[:-1])} {conector} {itens[-1]}"


# ---------- buscar_produtos ----------


class BuscarProdutos(Entrada):
    texto: str | None = Field(None, max_length=160, description="Palavras livres da peça (ex.: 'linho', 'oversized', 'xadrez').")
    tipo_peca: str | None = Field(
        None, max_length=40, description="Tipo de peça: camisa, camiseta, calça, vestido, moletom, jaqueta..."
    )
    cor: str | None = Field(None, max_length=40, description="Cor pedida pelo cliente (ex.: azul, preto, off-white).")
    tamanho: str | None = Field(
        None,
        max_length=10,
        description="Tamanho: XP, P, M, G, GG, U ou numérico (36 a 56). Aceita a grade internacional: XS=XP, S=P, L=G, XL=GG.",
    )
    preco_min: float | None = Field(None, ge=0, le=100000)
    preco_max: float | None = Field(None, ge=0, le=100000)
    marca: Marca | None = None
    genero: Literal["Masculino", "Feminino"] | None = None
    loja_id: int | None = Field(None, description="Só peças disponíveis nesta loja física (id da lista de lojas).")


def _pedido_da_entrada(entrada: BuscarProdutos) -> PedidoBusca:
    pedido = interpretar_busca(entrada.texto or "")
    if entrada.tipo_peca:
        pedido.tipos = tipo_da_peca(entrada.tipo_peca) or pedido.tipos
        if not pedido.tipos:
            pedido.termos.append(normalizar(entrada.tipo_peca))
    if entrada.cor:
        familia = familia_da_cor(entrada.cor)
        if familia:
            pedido.cor = familia
        else:
            pedido.termos.append(normalizar(entrada.cor))
    if entrada.tamanho:
        pedido.tamanho = normalizar_tamanho(entrada.tamanho) or pedido.tamanho
    if entrada.preco_min is not None:
        pedido.preco_min = Decimal(str(entrada.preco_min))
    if entrada.preco_max is not None:
        pedido.preco_max = Decimal(str(entrada.preco_max))
    pedido.marca = entrada.marca or pedido.marca
    pedido.genero = entrada.genero or pedido.genero
    return pedido


def _sem_desconhecidas(resultado: catalogo.ResultadoBusca) -> PedidoBusca:
    """O pedido sem as palavras que não aparecem em nenhuma peça (a busca não as usou; a descrição também não)."""
    return replace(resultado.pedido, termos=[t for t in resultado.pedido.termos if t not in resultado.desconhecidos])


def _frase_do_afrouxado(rotulo: str) -> str:
    if rotulo.startswith("sem "):
        return rotulo
    if rotulo == catalogo.ROTULO_PRECO:
        return "com preço fora da faixa"
    return f"em {rotulo}"


def texto_da_busca(
    resultado: catalogo.ResultadoBusca, cards: list[dict], loja_nome: str | None, habitual: str | None = None
) -> str:
    pedido = resultado.pedido
    descricao = descrever(_sem_desconhecidas(resultado))
    onde = f" na {loja_nome}" if loja_nome else ""
    if not cards:
        so_desconhecidas = not (pedido.tipos or pedido.cor or pedido.tamanho or pedido.preco_min or pedido.preco_max)
        if resultado.desconhecidos and so_desconhecidas and set(pedido.termos) <= set(resultado.desconhecidos):
            return f"Não encontrei “{' '.join(resultado.desconhecidos)}” no nosso catálogo. Quer que eu procure outra peça?"
        texto = f"Não encontrei {descricao}{onde} à venda agora."
        if resultado.esgotados:
            texto += f" {_lista(resultado.esgotados)} {'está esgotada' if len(resultado.esgotados) == 1 else 'estão esgotadas'} nessa opção."
        return texto + " Posso procurar outra cor, outro tamanho ou outra peça?"
    quantidade = f"{resultado.total} {'opção' if resultado.total == 1 else 'opções'}"
    if resultado.afrouxado == [catalogo.ROTULO_PRECO] and pedido.preco_max is not None:
        menor = min(card["preco"] for card in cards)
        texto = f"Não encontrei {descricao}{onde}. Separei as {quantidade} mais perto do seu orçamento, a partir de {brl(menor)}."
    elif resultado.afrouxado:
        texto = f"Não encontrei exatamente {descricao}{onde}. Separei {quantidade} {_frase_do_afrouxado(resultado.afrouxado[0])}."
    else:
        texto = f"Encontrei {quantidade} de {descricao}{onde}."
    if pedido.tamanho is None and set(pedido.tipos) & TIPOS_COM_TAMANHO:
        texto += " Qual tamanho você procura?"
        if habitual:
            texto += f" Nas suas compras, você costuma levar {habitual}."
    elif len(cards) > 1:
        texto += " Quer ver alguma delas de perto?"
    return texto


def buscar_produtos(db: Session, ctx: Contexto, entrada: BuscarProdutos) -> Resultado:
    pedido = _pedido_da_entrada(entrada)
    loja = None
    if entrada.loja_id is not None:
        loja = cadastro_repository.loja(db, entrada.loja_id)
        if loja is None or not loja.ativa or loja.tipo != "LOJA":
            raise FalhaFerramenta("LOJA_NAO_ENCONTRADA: use o id de uma loja física da lista de lojas.")
    resultado = catalogo.buscar(db, pedido, loja_id=loja.id if loja else None, marca_preferida=ctx.marca_site)
    cards = [catalogo.card(a) for a in resultado.achados]
    memoria = {
        "busca": pedido.para_dict(),
        "buscaDescricao": descrever(_sem_desconhecidas(resultado)),
        "produtosMostrados": [{"id": c["produtoId"], "nome": c["nome"]} for c in cards],
        # Busca nova: a peça em foco só continua se for a única encontrada
        "produtoEmFoco": {"id": cards[0]["produtoId"], "nome": cards[0]["nome"]} if len(cards) == 1 else None,
        "corEmFoco": None,
        "tamanhoEmFoco": pedido.tamanho,
    }
    memoria["oferta"] = (
        "TAMANHO"
        if cards and pedido.tamanho is None and set(pedido.tipos) & TIPOS_COM_TAMANHO
        else ("ESCOLHA_PRODUTO" if len(cards) > 1 else None)
    )
    if loja:
        memoria["lojaEmFoco"] = loja.id
        memoria["lojaEmFocoNome"] = loja.nome
    # Sem tamanho na busca: o que o cliente logado costuma levar nesse tipo, como sugestão (decisão 103)
    habitual = None
    if cards and ctx.cliente_id and pedido.tamanho is None and set(pedido.tipos) & TIPOS_COM_TAMANHO:
        habitual = perfil_cliente.tamanho_habitual(db, ctx.cliente_id, pedido.tipos)
    dados = {
        "busca": descrever(_sem_desconhecidas(resultado)),
        "tamanhoQueCostumaLevar": habitual,
        "loja": loja.nome if loja else None,
        "encontrados": resultado.total,
        "pecas": [
            {k: c[k] for k in ("produtoId", "nome", "marca", "categoria", "precoFormatado", "cores", "tamanhos", "situacao")}
            for c in cards
        ],
        "afrouxado": resultado.afrouxado,
        "esgotadasNessaOpcao": resultado.esgotados,
        "palavrasSemPecas": resultado.desconhecidos,
    }
    blocos = [{"tipo": "produtos", "titulo": None, "itens": cards}] if cards else []
    return Resultado(
        dados=dados,
        blocos=blocos,
        memoria=memoria,
        texto=texto_da_busca(resultado, cards, loja.nome if loja else None, habitual),
    )


# ---------- ver_produto ----------


class VerProduto(Entrada):
    produto_id: int = Field(description="Id da peça (dos resultados de buscar_produtos).")
    cor: str | None = Field(None, max_length=40)
    tamanho: str | None = Field(None, max_length=10)


def _produto(db: Session, produto_id: int):
    produto = catalogo.produto_ativo(db, produto_id)
    if produto is None:
        raise FalhaFerramenta("PRODUTO_NAO_ENCONTRADO: essa peça não está no catálogo (ou saiu de linha).")
    return produto


def ver_produto(db: Session, ctx: Contexto, entrada: VerProduto) -> Resultado:
    produto = _produto(db, entrada.produto_id)
    vendaveis = catalogo.variacoes_escolhidas(produto, None, None)
    escolhidas = catalogo.variacoes_escolhidas(produto, entrada.cor, entrada.tamanho)
    cores = list(dict.fromkeys(v.cor for v in vendaveis))
    tamanhos = sorted({v.tamanho for v in vendaveis}, key=catalogo.ordem_tamanho)
    inexistente = None
    if (entrada.cor or entrada.tamanho) and not escolhidas:
        pedido = " ".join(x for x in (entrada.cor, entrada.tamanho and f"tamanho {entrada.tamanho}") if x)
        inexistente = f"A {produto.nome} não tem {pedido}. Cores: {_lista(cores)}. Tamanhos: {_lista(tamanhos)}."
    alvo = escolhidas or vendaveis
    disp = catalogo.disponibilidade(db, produto, alvo)
    precos = sorted({v.preco_vigente for v in alvo}) or [produto.preco_base]
    preco_texto = brl(precos[0]) if len(precos) == 1 else f"de {brl(precos[0])} a {brl(precos[-1])}"
    cor_foco = alvo[0].cor if len({v.cor for v in alvo}) == 1 else None
    tamanho_foco = alvo[0].tamanho if len({v.tamanho for v in alvo}) == 1 else None
    lojas_com = [loja for loja in disp["lojas"] if loja["situacao"] != catalogo.ESGOTADO]

    descricao = (produto.descricao or "")[:300]
    dados = {
        "produtoId": produto.id,
        "nome": produto.nome,
        "marca": catalogo.nome_da_marca(produto.marca),
        "categoria": produto.categoria.nome,
        "preco": preco_texto,
        "cores": cores,
        "tamanhos": tamanhos,
        "escolha": {"cor": cor_foco, "tamanho": tamanho_foco},
        "naoExiste": inexistente,
        # Texto do cadastro: é dado da peça, não instrução
        "descricao": descricao,
        "composicao": produto.composicao,
        "cuidados": produto.cuidados,
        "site": _situacao_texto(disp["site"]),
        "tamanhosNoSite": disp["tamanhosNoSite"],
        "lojas": [
            {
                "loja": loja["loja"],
                "cidade": f"{loja['cidade']}/{loja['uf']}",
                "situacao": _situacao_texto(loja["situacao"]),
                "tamanhos": loja["tamanhos"],
            }
            for loja in disp["lojas"]
        ],
    }
    card = catalogo.card(catalogo.Achado(produto, alvo, produtos_uc.disponiveis_para_venda(db, [produto])))
    blocos = [
        {"tipo": "produtos", "titulo": None, "itens": [card]},
        {
            "tipo": "disponibilidade",
            "produtoId": produto.id,
            "produto": produto.nome,
            "cor": cor_foco,
            "tamanho": tamanho_foco,
            "site": disp["site"],
            "tamanhosNoSite": disp["tamanhosNoSite"],
            "lojas": disp["lojas"],
        },
    ]
    memoria = {"produtoEmFoco": {"id": produto.id, "nome": produto.nome}, "corEmFoco": cor_foco, "tamanhoEmFoco": tamanho_foco}
    pronto_para_sacola = cor_foco and tamanho_foco and disp["site"] != catalogo.ESGOTADO and not inexistente
    memoria["oferta"] = "SACOLA" if pronto_para_sacola else ("TAMANHO" if not tamanho_foco else ("COR" if not cor_foco else None))

    escolha = ", ".join(x for x in (cor_foco, tamanho_foco and f"tamanho {tamanho_foco}") if x)
    nome = f"{produto.nome}{f' ({escolha})' if escolha else ''}"
    if inexistente:
        texto = inexistente
    elif disp["site"] == catalogo.ESGOTADO and not lojas_com:
        texto = f"A {nome} está indisponível no momento, no site e nas lojas."
    else:
        texto = f"A {nome} sai por {preco_texto}. No site: {_situacao_texto(disp['site'])}."
        if lojas_com:
            texto += f" Nas lojas: {_lista([loja['loja'] + (' (últimas unidades)' if loja['situacao'] == catalogo.ULTIMAS else '') for loja in lojas_com])}."
        else:
            texto += " Nas lojas físicas está indisponível agora."
        cores_no_tamanho = list(dict.fromkeys(v.cor for v in alvo))
        if pronto_para_sacola:
            texto += " Quer que eu coloque na sua sacola?"
        elif not tamanho_foco:
            texto += f" Qual tamanho? Temos {_lista(disp['tamanhosNoSite'] or tamanhos, 'ou')}."
        elif not cor_foco and len(cores_no_tamanho) > 1:
            texto += f" Em qual cor? Temos {_lista(cores_no_tamanho, 'ou')}."
    return Resultado(dados=dados, blocos=blocos, memoria=memoria, texto=texto)


# ---------- informacoes_lojas ----------


class InformacoesLojas(Entrada):
    busca: str | None = Field(
        None, max_length=80, description="Nome, bairro ou cidade citados (ex.: 'shopping', 'Pinheiros', 'BH')."
    )
    marca: Marca | None = None


_DIAS_DA_SEMANA = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
NOME_DO_DIA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")


def _faixa(horas: str) -> str:
    """'10:00–22:00' -> '10:00 às 22:00'."""
    inicio, _, fim = horas.partition("–")
    return f"{inicio.strip()} às {fim.strip()}" if fim else horas


def horario_do_dia(horarios: list[str], dia: date) -> str | None:
    """'10:00–22:00' do dia da semana, a partir das linhas do cadastro ('Segunda a sábado: 10:00–22:00',
    'Domingo: 12:00–20:00'). None se o dia não estiver cadastrado."""
    semana = dia.weekday()
    for linha in horarios:
        quando, _, horas = linha.partition(":")
        dias = [_DIAS_DA_SEMANA.index(d) for d in re.findall(r"[a-z]+", normalizar(quando)) if d in _DIAS_DA_SEMANA]
        if (len(dias) == 2 and dias[0] <= semana <= dias[1]) or dias == [semana]:
            return horas.strip()
    return None


def loja_saida(loja) -> dict:
    return {
        "lojaId": loja.id,
        "nome": loja.nome,
        "marca": loja.marca,
        "endereco": loja.endereco,
        "cidade": f"{loja.cidade}/{loja.uf}",
        "telefone": loja.telefone,
        "horarios": list(loja.horarios or []),
    }


def informacoes_lojas(db: Session, ctx: Contexto, entrada: InformacoesLojas) -> Resultado:
    if entrada.busca:
        lojas = catalogo.encontrar_lojas(db, entrada.busca, marca=entrada.marca)
    else:
        lojas = cadastro_repository.lojas(db, somente_ativas=True, marca=entrada.marca, tipo="LOJA")
    itens = [loja_saida(loja) for loja in lojas]
    # "Que horas fecha?" quase sempre é sobre hoje: o horário do dia vem pronto
    dia = hoje()
    hoje_texto = f"{NOME_DO_DIA[dia.weekday()]}, {data(dia)}"
    for item in itens:
        item["horarioDeHoje"] = horario_do_dia(item["horarios"], dia)
    if not itens:
        texto = "Não encontrei uma loja com esse nome ou nessa cidade. Nossas lojas ficam em São Paulo, Rio de Janeiro, Brasília, Curitiba e Belo Horizonte."
    elif len(itens) == 1:
        loja = itens[0]
        horarios = "; ".join(loja["horarios"]) or "horário não cadastrado"
        texto = f"{loja['nome']}: {loja['endereco'] or loja['cidade']}. Horário: {horarios}. Telefone: {loja['telefone'] or 'não cadastrado'}."
        if loja["horarioDeHoje"]:
            texto += f" Hoje ({NOME_DO_DIA[dia.weekday()]}), funciona das {_faixa(loja['horarioDeHoje'])}."
    else:
        texto = f"Encontrei {len(itens)} lojas: {_lista([i['nome'] for i in itens])}."
        de_hoje = [f"{i['nome']}, das {_faixa(i['horarioDeHoje'])}" for i in itens[:4] if i["horarioDeHoje"]]
        if de_hoje:
            texto += f" Hoje ({NOME_DO_DIA[dia.weekday()]}): {'; '.join(de_hoje)}."
        texto += " Endereços, telefones e todos os horários estão abaixo."
    return Resultado(
        dados={
            "hoje": hoje_texto,
            "lojas": [
                {k: i[k] for k in ("nome", "marca", "endereco", "cidade", "telefone", "horarios", "horarioDeHoje")} for i in itens
            ],
        },
        blocos=[{"tipo": "lojas", "itens": itens}] if itens else [],
        texto=texto,
    )


# ---------- politicas_da_loja ----------


class Politicas(Entrada):
    assunto: Literal["frete", "trocas", "pagamento", "vulto_mais"]


# Decisão 111: peça comprada no site troca em loja física da mesma marca, nas condições da troca pelo site
TROCA_NA_LOJA = "Peça comprada no site também pode ser trocada numa loja física da mesma marca (Casa Lorenzi numa loja Casa Lorenzi, Vulto numa loja Vulto), nas mesmas condições da troca pelo site, levando o número do pedido."


def politicas_da_loja(db: Session, ctx: Contexto, entrada: Politicas) -> Resultado:
    if entrada.assunto == "frete":
        condicoes = frete_config.condicoes(db)
        regioes = [
            {
                "regiao": r["nome"],
                "padrao": f"{brl(r['padrao']['valor'])} em até {r['padrao']['prazoDias']} dias úteis",
                "expresso": f"{brl(r['expresso']['valor'])} em até {r['expresso']['prazoDias']} dias úteis"
                if condicoes["expressoAtivo"]
                else None,
            }
            for r in condicoes["regioes"]
        ]
        dados = {
            "freteGratisAcimaDe": brl(condicoes["gratisMinimo"]),
            "expressoDisponivel": condicoes["expressoAtivo"],
            "regioes": regioes,
        }
        texto = (
            f"O frete Padrão é grátis em compras a partir de {brl(condicoes['gratisMinimo'])}. "
            "O valor e o prazo exatos aparecem no checkout a partir do CEP."
        )
    elif entrada.assunto == "trocas":
        tipos = {t.titulo: t.descricao for t in cadastro_repository.tipos_solicitacao(db, ativo=True)}
        dados = {
            "troca": tipos.get("Troca de produto"),
            "devolucao": tipos.get("Devolução e reembolso"),
            "comoPedir": "Na conta do cliente, em Solicitações > Nova solicitação, escolhendo o pedido.",
            "naLojaFisica": TROCA_NA_LOJA,
        }
        texto = (
            f"Trocas: {dados['troca'] or 'por outro tamanho, cor ou modelo'} Devoluções: {dados['devolucao'] or 'em até 30 dias'} "
            "É só entrar na sua conta, abrir Solicitações e escolher o pedido. "
            f"{TROCA_NA_LOJA}"
        )
    elif entrada.assunto == "pagamento":
        metodos = ["PIX" if m_ == "PIX" else f"cartão de crédito em até {PARCELAS_MAX}x" for m_ in METODOS_ECOMMERCE]
        dados = {"formasNoSite": metodos, "pontosVultoMais": "dá para usar pontos Lupe+ como desconto no checkout"}
        texto = f"No site aceitamos {_lista(metodos)}. Também dá para usar os pontos Lupe+ como desconto no checkout."
    else:
        dados = {
            "ganho": "R$ 1 em produtos = 1 ponto na loja física e 2 pontos no site e no app (o frete não conta); Ouro ganha +25% e Vip +50%",
            "resgate": f"100 pontos = R$ 5,00, em múltiplos de 100, em compras a partir de {brl(regra_pontos.COMPRA_MINIMA_RESGATE)} em produtos",
            "validade": f"{regra_pontos.VALIDADE_MESES} meses",
            "categorias": "Bronze até 1.500 pontos, Prata até 5.000, Ouro até 9.999 e Vip a partir de 10.000",
            "vale": "compras da Casa Lorenzi e da Vulto",
        }
        texto = (
            "No Lupe+, cada R$ 1 em produtos vale 1 ponto na loja física e 2 no site e no app. 100 pontos = R$ 5,00 de desconto, "
            f"em compras a partir de {brl(regra_pontos.COMPRA_MINIMA_RESGATE)}. Os pontos valem {regra_pontos.VALIDADE_MESES} meses."
        )
    return Resultado(dados={"assunto": entrada.assunto, **dados}, texto=texto)


# ---------- consultar_meus_pontos ----------


class SemParametros(Entrada):
    pass


def _cliente(db: Session, ctx: Contexto):
    cliente = cliente_repository.por_id(db, ctx.cliente_id) if ctx.cliente_id else None
    if cliente is None or cliente.excluido_em is not None:
        raise FalhaFerramenta("LOGIN_NECESSARIO: para ver essa informação, o cliente precisa entrar na conta.")
    return cliente


def consultar_meus_pontos(db: Session, ctx: Contexto, entrada: SemParametros) -> Resultado:
    cliente = _cliente(db, ctx)
    resumo = fidelidade.resumo(db, cliente)  # a mesma conta da página Lupe+ (lança o vencimento, se houver)
    categoria = ROTULO_CATEGORIA.get(resumo.categoria or "")
    # Sem pontos, "falta 1 ponto para a Bronze" soa estranho: a primeira compra já leva à Bronze
    proxima = regra_pontos.proxima_categoria(resumo.saldo) if resumo.saldo > 0 else None
    vencimentos = [{"data": data(d), "pontos": numero(p)} for d, p in resumo.a_vencer]
    dados = {
        "saldo": numero(resumo.saldo),
        "valorEmReais": brl(resumo.valor_em_reais),
        "categoria": categoria or "sem categoria (sem pontos)",
        "proximosVencimentos": vencimentos,
        "proximaCategoria": {"categoria": ROTULO_CATEGORIA[proxima[0]], "faltam": numero(proxima[1])} if proxima else None,
        "resgate": f"100 pontos = R$ 5,00, em compras a partir de {brl(regra_pontos.COMPRA_MINIMA_RESGATE)} em produtos",
    }
    if resumo.saldo == 0:
        dados["comoComecar"] = "Com a primeira compra o cliente já entra na categoria Bronze."
    bloco = {
        "tipo": "pontos",
        "saldo": resumo.saldo,
        "valorEmReais": float(resumo.valor_em_reais),
        "categoria": categoria,
        "aVencer": [{"data": d.isoformat(), "pontos": p} for d, p in resumo.a_vencer],
        "proximaCategoria": {"categoria": ROTULO_CATEGORIA[proxima[0]], "faltam": proxima[1]} if proxima else None,
        "link": "/cliente/pontos",
    }
    if resumo.saldo == 0:
        texto = "Você ainda não tem pontos Lupe+. Cada R$ 1 em produtos vale 1 ponto na loja física e 2 no site e no app, nas duas marcas."
    else:
        texto = f"Você tem {numero(resumo.saldo)} pontos Lupe+ ({brl(resumo.valor_em_reais)} em desconto)"
        texto += f", na categoria {categoria}." if categoria else "."
        if vencimentos:
            texto += f" Os próximos a vencer: {vencimentos[0]['pontos']} pontos em {vencimentos[0]['data']}."
        if proxima:
            faltam = "Falta 1 ponto" if proxima[1] == 1 else f"Faltam {numero(proxima[1])} pontos"
            texto += f" {faltam} para a categoria {ROTULO_CATEGORIA[proxima[0]]}."
    return Resultado(dados=dados, blocos=[bloco], texto=texto)


# ---------- consultar_meus_pedidos ----------


def consultar_meus_pedidos(db: Session, ctx: Contexto, entrada: SemParametros) -> Resultado:
    cliente = _cliente(db, ctx)
    pedidos = pedido_repository.do_cliente(db, cliente.id)[:5]
    itens = [
        {
            "numero": p.numero,
            "data": ms(p.criado_em),
            "status": p.status,
            "statusRotulo": ROTULO_STATUS_PEDIDO.get(p.status, p.status),
            "total": float(p.total),
            "canal": p.canal,
            "pecas": sum(i.quantidade for i in p.itens),
            "rastreio": p.codigo_rastreio,
        }
        for p in pedidos
    ]
    dados = {
        "pedidos": [
            {
                "numero": i["numero"],
                "data": data(p.criado_em),
                "status": i["statusRotulo"],
                "total": brl(p.total),
                "rastreio": i["rastreio"],
            }
            for i, p in zip(itens, pedidos, strict=True)
        ]
    }
    if not itens:
        texto = "Não encontrei pedidos na sua conta."
    else:
        ultimo = dados["pedidos"][0]
        texto = f"Seu pedido mais recente é o {ultimo['numero']} ({ultimo['data']}): {ultimo['status'].lower()}."
        if ultimo["rastreio"]:
            texto += f" Código de rastreio: {ultimo['rastreio']}."
    return Resultado(
        dados=dados, blocos=[{"tipo": "pedidos", "itens": itens, "link": "/cliente/pedidos"}] if itens else [], texto=texto
    )


# ---------- colocar_na_sacola ----------


class ColocarNaSacola(Entrada):
    produto_id: int
    cor: str | None = Field(None, max_length=40, description="Cor exata da peça (obrigatória se a peça tem mais de uma).")
    tamanho: str = Field(max_length=10)
    quantidade: int = Field(1, ge=1, le=MAX_SACOLA)


def colocar_na_sacola(db: Session, ctx: Contexto, entrada: ColocarNaSacola) -> Resultado:
    """Confere peça, cor, tamanho, preço e disponibilidade e devolve o botão de confirmar. Não adiciona nada:
    a peça só entra na sacola quando o cliente aperta o botão."""
    produto = _produto(db, entrada.produto_id)
    cores = list(dict.fromkeys(v.cor for v in catalogo.variacoes_escolhidas(produto, None, None)))
    cor = entrada.cor or (cores[0] if len(cores) == 1 else None)
    if cor is None:
        raise FalhaFerramenta(f"ESCOLHA_A_COR: a {produto.nome} tem {_lista(cores, 'ou')}. Pergunte a cor ao cliente.")
    variacoes = catalogo.variacoes_escolhidas(produto, cor, entrada.tamanho)
    if len(variacoes) != 1:
        tamanhos = sorted({v.tamanho for v in catalogo.variacoes_escolhidas(produto, cor, None)}, key=catalogo.ordem_tamanho)
        if not tamanhos:
            raise FalhaFerramenta(f"VARIACAO_INEXISTENTE: a {produto.nome} não tem a cor {cor}. Cores: {_lista(cores)}.")
        raise FalhaFerramenta(
            f"VARIACAO_INEXISTENTE: a {produto.nome} na cor {cor} não tem o tamanho {entrada.tamanho}. Tamanhos: {_lista(tamanhos)}."
        )
    variacao = variacoes[0]
    livre = produtos_uc.disponiveis_para_venda(db, [produto]).get(variacao.id, 0)
    if livre < entrada.quantidade:
        raise FalhaFerramenta(
            f"ESGOTADO: a {produto.nome} ({variacao.cor}, {variacao.tamanho}) está indisponível nessa quantidade."
        )
    preco = variacao.preco_vigente
    item = {
        "variacaoId": variacao.id,
        "produtoId": produto.id,
        "nome": produto.nome,
        "cor": variacao.cor,
        "tamanho": variacao.tamanho,
        "sku": variacao.sku,
        "preco": float(preco),
        "quantidade": entrada.quantidade,
        "imagemUrl": imagem_url(produto),
        "marca": produto.marca,
        "codigoModelo": produto.codigo_modelo,
    }
    dados = {
        "colocadoNaSacola": True,
        "peca": f"{produto.nome} · {variacao.cor} · {variacao.tamanho}",
        "preco": brl(preco),
        "quantidade": entrada.quantidade,
        "importante": "A peça entra na sacola do cliente assim que esta resposta aparece (ele pode desfazer). Diga que "
        "colocou e pergunte se ele quer finalizar a compra ou continuar olhando.",
    }
    texto = (
        f"Coloquei {produto.nome}, cor {variacao.cor}, tamanho {variacao.tamanho}, por {brl(preco)}, na sua sacola. "
        "Quer finalizar a compra ou continuar olhando?"
    )
    return Resultado(
        dados=dados,
        blocos=[{"tipo": "acao_sacola", "estado": "ADICIONAR", "item": item}],
        memoria={
            "produtoEmFoco": {"id": produto.id, "nome": produto.nome},
            "corEmFoco": variacao.cor,
            "tamanhoEmFoco": variacao.tamanho,
            "oferta": "FINALIZAR",
        },
        texto=texto,
    )


# ---------- solicitar_atendimento_humano ----------


class AtendimentoHumano(Entrada):
    motivo: str = Field(max_length=300, description="Resumo, em uma frase, do que o cliente precisa.")


def solicitar_atendimento_humano(db: Session, ctx: Contexto, entrada: AtendimentoHumano) -> Resultado:
    """Oferece falar com a equipe pelo próprio site (chamado na conta do cliente; sem login, pede para entrar).
    No site, a oferta não leva ao WhatsApp (decisão 128): quem prefere o WhatsApp usa o botão do topo do chat
    (decisão 127). Nada é aberto até o cliente tocar no botão."""
    logado = ctx.cliente_id is not None
    whatsapp = False
    lojas = [loja_saida(loja) for loja in cadastro_repository.lojas(db, somente_ativas=True, marca=ctx.marca_site, tipo="LOJA")]
    bloco = {
        "tipo": "acao_atendimento",
        "estado": "PENDENTE",
        "motivo": entrada.motivo.strip()[:300],
        "precisaLogin": not logado,
        "whatsapp": whatsapp,
        "telefones": [{"loja": loja["nome"], "telefone": loja["telefone"]} for loja in lojas if loja["telefone"]][:5],
    }
    if logado:
        texto = (
            "Posso abrir uma solicitação para a nossa equipe com o resumo desta conversa. Toque em “Falar com a equipe” "
            "para confirmar: a resposta chega aqui no site."
        )
    else:
        texto = (
            "Para a equipe responder aqui no site, entre na sua conta e toque em “Falar com a equipe”. Se preferir, "
            "ligue para uma das lojas abaixo"
            + (" ou fale com a gente pelo WhatsApp, no botão do topo do chat." if settings.WHATSAPP_ATENDIMENTO else ".")
        )
    return Resultado(
        dados={"botaoOferecido": True, "precisaLogin": not logado, "whatsapp": whatsapp},
        blocos=[bloco],
        memoria={"oferta": "ATENDIMENTO"},
        texto=texto,
    )


# ---------- Registro ----------

FERRAMENTAS = [
    Ferramenta(
        "buscar_produtos",
        "Busca peças no catálogo real da Casa Lorenzi e da Vulto e devolve até 6 disponíveis, com preço, cores e "
        "tamanhos. Use para qualquer pergunta sobre ter ou encontrar uma peça. Preencha só o que o cliente disse. "
        "Se nada bater exatamente, o resultado diz o que foi afrouxado (cor parecida, outros tamanhos).",
        BuscarProdutos,
        buscar_produtos,
    ),
    Ferramenta(
        "ver_produto",
        "Detalhes de uma peça (descrição, composição, cores, tamanhos, preço) e a disponibilidade no site e em "
        "cada loja física, na cor e no tamanho pedidos. Use quando o cliente escolhe uma peça ou pergunta se tem numa loja.",
        VerProduto,
        ver_produto,
    ),
    Ferramenta(
        "informacoes_lojas",
        "Endereço, telefone e horários das lojas físicas, cadastrados no sistema. Sem busca, lista todas.",
        InformacoesLojas,
        informacoes_lojas,
    ),
    Ferramenta(
        "politicas_da_loja",
        "Regras oficiais do site: frete (valores e frete grátis), trocas e devoluções, formas de pagamento e o programa Lupe+.",
        Politicas,
        politicas_da_loja,
    ),
    Ferramenta(
        "consultar_meus_pontos",
        "Saldo de pontos Lupe+ do cliente logado: pontos, valor em reais, categoria, próximos vencimentos e quanto "
        "falta para a próxima categoria. Sem login, devolve LOGIN_NECESSARIO.",
        SemParametros,
        consultar_meus_pontos,
        exige_cliente=True,
        escrita=True,
    ),
    Ferramenta(
        "consultar_meus_pedidos",
        "Os 5 pedidos mais recentes do cliente logado, com status e código de rastreio. Sem login, devolve LOGIN_NECESSARIO.",
        SemParametros,
        consultar_meus_pedidos,
        exige_cliente=True,
    ),
    Ferramenta(
        "colocar_na_sacola",
        "Confere peça, cor, tamanho, preço e disponibilidade e coloca a peça na sacola do cliente na hora (ele pode "
        "desfazer). Use quando o cliente pedir a peça, com cor e tamanho definidos. Não finaliza a compra.",
        ColocarNaSacola,
        colocar_na_sacola,
    ),
    Ferramenta(
        "solicitar_atendimento_humano",
        "Mostra ao cliente o botão para falar com a equipe (abre um chamado com o resumo da conversa quando ele "
        "confirma). Use quando você não resolve o pedido, quando há reclamação ou quando o cliente pede uma pessoa.",
        AtendimentoHumano,
        solicitar_atendimento_humano,
    ),
]
