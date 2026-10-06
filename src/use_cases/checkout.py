"""Checkout da loja: compra sem conta. O e-mail identifica o cliente e o PIN criado aqui libera
"Meus pedidos". Já comprou antes? Usa o mesmo PIN.

Numa única transação: confere os dados, recalcula preços e frete no servidor (nada de valor
vem do navegador), escolhe a loja de expedição, grava pedido, itens e pagamento (aprovado:
pagamento simulado na demonstração) e cria as transferências das peças que faltam na loja.
As peças só saem do estoque no envio (painel de pedidos).
"""

import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from src import models as m
from src.entities.cliente import email_valido, normalizar_email
from src.entities.frete import ROTULOS, opcao_de_frete, somente_digitos
from src.entities.pagamento import METODOS_ECOMMERCE, PARCELAS_MAX
from src.entities.pedido import proximo_numero
from src.repositories import cliente_repository, estoque_repository, pedido_repository, produto_repository, sessao
from src.schemas.pedidos import CheckoutEntrada
from src.use_cases import pagamentos
from src.use_cases.meus_pedidos import conferir_pin, texto_do_pin, validar_novo_pin
from src.use_cases.pedidos import escolher_loja_expedicao, planejar_transferencias, registrar_evento
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos, MuitasTentativas
from src.utils.seguranca import gerar_hash

log = logging.getLogger("casalorenzi")

ITENS_MAX = 50
QUANTIDADE_MAX = 20

# (campo, limite de caracteres, obrigatório) do endereço de entrega — limites das colunas de pedidos
_ENDERECO = (("rua", 160, True), ("numero", 20, True), ("complemento", 80, False), ("bairro", 80, True), ("cidade", 120, True))


def _texto(valor: str | None, maximo: int, mensagem_tamanho: str) -> str:
    texto = (valor or "").strip()
    if len(texto) > maximo:
        raise DadosInvalidos(mensagem_tamanho)
    return texto


def _cliente(db: Session, dados: CheckoutEntrada, email: str) -> m.Cliente:
    """Cliente do e-mail (criado se for a primeira compra). Quem já tem PIN precisa usar o mesmo."""
    pin = validar_novo_pin(dados.pin, dados.pin_confirmacao)
    cliente = cliente_repository.por_email(db, email, travar=True)
    if cliente is None:
        return cliente_repository.criar(
            db, nome=dados.nome, email=email, telefone=_texto(dados.telefone, 30, "Telefone inválido."), pin_hash=gerar_hash(pin)
        )
    if cliente.pin_hash is None:
        # Cliente antigo (loja física ou migrado) ainda sem PIN: o checkout cria
        cliente.pin_hash = gerar_hash(pin)
    else:
        try:
            confere = conferir_pin(db, cliente, texto_do_pin(pin))
        except MuitasTentativas:
            raise MuitasTentativas("Muitas tentativas com um PIN incorreto. Tente de novo em 15 minutos.") from None
        if not confere:
            raise Conflito("Este e-mail já tem um PIN. Use o mesmo PIN das suas compras anteriores.")
    if not cliente.telefone and dados.telefone:
        cliente.telefone = _texto(dados.telefone, 30, "Telefone inválido.")
    return cliente


def _itens(db: Session, dados: CheckoutEntrada) -> list[tuple[m.Variacao, int, Decimal]]:
    """(variação, quantidade, preço unitário) de cada item. O preço vem do cadastro, não do navegador."""
    if not dados.itens:
        raise DadosInvalidos("Sua sacola está vazia.")
    if len(dados.itens) > ITENS_MAX:
        raise DadosInvalidos(f"A sacola pode ter no máximo {ITENS_MAX} itens.")
    itens, pedido_por_variacao = [], {}
    for item in dados.itens:
        variacao = produto_repository.variacao(db, item.variacao_id)
        if variacao is None or not variacao.produto.ativo:
            raise DadosInvalidos("Um dos itens da sacola não está mais disponível.")
        if not 1 <= item.quantidade <= QUANTIDADE_MAX:
            raise DadosInvalidos(f"A quantidade de cada item deve ficar entre 1 e {QUANTIDADE_MAX}.")
        pedido_por_variacao[variacao.id] = pedido_por_variacao.get(variacao.id, 0) + item.quantidade
        itens.append((variacao, item.quantidade, variacao.produto.preco_base))
    disponivel = estoque_repository.totais_por_variacao(db, list(pedido_por_variacao))
    for variacao, _, _ in itens:
        if disponivel.get(variacao.id, 0) < pedido_por_variacao[variacao.id]:
            raise Conflito(
                f"{variacao.produto.nome} ({variacao.cor}, {variacao.tamanho}) esgotou. Ajuste a sacola para continuar."
            )
    return itens


def finalizar_compra(db: Session, dados: CheckoutEntrada) -> m.Pedido:
    email = normalizar_email(dados.email)
    if not email_valido(email):
        raise DadosInvalidos("Informe um e-mail válido.")
    if email != normalizar_email(dados.email_confirmacao):
        raise DadosInvalidos("Os e-mails não conferem.")
    nome = _texto(dados.nome, 120, "O nome deve ter no máximo 120 caracteres.")
    if not nome:
        raise DadosInvalidos("Informe o nome completo.")
    dados.nome = nome

    endereco = dados.endereco
    cep = somente_digitos(endereco.cep)
    uf = endereco.uf.strip().upper()
    campos = {campo: _texto(getattr(endereco, campo), maximo, "Endereço de entrega inválido.") for campo, maximo, _ in _ENDERECO}
    if len(cep) != 8 or len(uf) != 2 or any(not campos[campo] for campo, _, obrigatorio in _ENDERECO if obrigatorio):
        raise DadosInvalidos("Preencha o endereço de entrega completo.")

    cliente = _cliente(db, dados, email)
    itens = _itens(db, dados)

    subtotal = sum((preco * quantidade for _, quantidade, preco in itens), Decimal("0"))
    frete = opcao_de_frete(cep, subtotal, dados.frete_tipo)
    if frete is None:
        raise DadosInvalidos("Escolha uma opção de frete para o CEP informado.")
    frete_valor, prazo = frete
    metodo = dados.pagamento.metodo
    if metodo not in METODOS_ECOMMERCE:
        raise DadosInvalidos("Escolha a forma de pagamento.")
    parcelas = min(max(dados.pagamento.parcelas or 1, 1), PARCELAS_MAX) if metodo == "CARTAO" else 1

    loja = escolher_loja_expedicao(db, [(v.id, q) for v, q, _ in itens], cep)
    momento = agora()
    pedido = m.Pedido(
        numero=proximo_numero(pedido_repository.reservar_numeracao(db)),
        cliente=cliente,
        loja_id=loja.id,
        canal="E-commerce",
        status="PROCESSANDO",
        subtotal=subtotal,
        total=subtotal + frete_valor,
        frete_tipo=dados.frete_tipo,
        frete_valor=frete_valor,
        frete_prazo_dias=prazo,
        entrega_cep=cep,
        entrega_rua=campos["rua"],
        entrega_numero=campos["numero"],
        entrega_complemento=campos["complemento"] or None,
        entrega_bairro=campos["bairro"],
        entrega_cidade=campos["cidade"],
        entrega_uf=uf,
        criado_em=momento,
        itens=[m.ItemPedido(variacao_id=v.id, quantidade=q, preco_unitario=preco) for v, q, preco in itens],
    )
    sessao.adicionar(db, pedido)
    pagamentos.novo(db, pedido, metodo=metodo, valor=pedido.total, parcelas=parcelas, quando=momento)
    registrar_evento(db, pedido, "PROCESSANDO", observacao=f"Pagamento aprovado · expedição: {loja.nome}", quando=momento)
    sessao.gerar_ids(db)
    planejar_transferencias(db, pedido)
    sessao.confirmar(db, pedido)

    # Ainda não há envio de e-mail: a confirmação fica registrada no log
    log.info(
        "Pedido %s confirmado para %s (%s, frete %s)", pedido.numero, email, f"R$ {pedido.total:.2f}", ROTULOS[dados.frete_tipo]
    )
    sessao.descartar_cache(db)
    return pedido_repository.obter(db, pedido.id)
