from decimal import Decimal

from sqlalchemy.orm import Session

from src import models as m
from src.entities.produto import ESTACAO_PADRAO, ESTACOES, GENEROS
from src.repositories import cadastro_repository, estoque_repository, produto_repository, sessao
from src.schemas.produtos import ProdutoEntrada
from src.use_cases import anexos, log_acoes
from src.use_cases.estoque import criar_estoques_zerados
from src.utils.datas import agora
from src.utils.erros import DadosInvalidos, NaoEncontrado
from src.utils.texto import chave_texto, corresponde, moeda


def listar(db: Session, busca: str | None = None, categoria: str | None = None, ativo: bool | None = None) -> list[m.Produto]:
    produtos = [
        p
        for p in produto_repository.listar(db, categoria=categoria, ativo=ativo)
        if corresponde(busca, p.nome, p.categoria.nome, *(v.sku for v in p.variacoes))
    ]
    produtos.sort(key=lambda p: chave_texto(p.nome))
    return produtos


def obter(db: Session, produto_id: int) -> m.Produto:
    produto = produto_repository.obter(db, produto_id)
    if produto is None:
        raise NaoEncontrado("Produto não encontrado.")
    return produto


def totais_de_estoque(db: Session, produtos: list[m.Produto]) -> dict[int, int]:
    return estoque_repository.totais_por_variacao(db, [v.id for p in produtos for v in p.variacoes])


def imagem(db: Session, produto_id: int) -> m.ImagemProduto:
    produto = obter(db, produto_id)
    if produto.imagem is None:
        raise NaoEncontrado("Este produto não tem foto enviada.")
    return produto.imagem


def _validar(db: Session, dados: ProdutoEntrada, produto_id: int | None) -> m.Categoria:
    if not dados.nome.strip():
        raise DadosInvalidos("Informe o nome do produto.")
    if not dados.categoria:
        raise DadosInvalidos("Selecione a categoria.")
    categoria = cadastro_repository.categoria_por_nome(db, dados.categoria)
    if categoria is None:
        raise DadosInvalidos(f"Categoria '{dados.categoria}' não existe.")
    if not dados.preco_base > 0:
        raise DadosInvalidos("Informe um preço base válido.")
    skus = [v.sku.strip().upper() for v in dados.variacoes]
    if any(not sku for sku in skus):
        raise DadosInvalidos("Toda variação precisa de um SKU.")
    if len(set(skus)) != len(skus):
        raise DadosInvalidos("Há SKUs repetidos nas variações.")
    if skus and (duplicado := produto_repository.sku_em_uso(db, skus, produto_id)):
        raise DadosInvalidos(f"O SKU {duplicado.sku} já está em uso.")
    if produto_id is None and not dados.genero:
        raise DadosInvalidos("Selecione a coleção do produto: Masculino ou Feminino.")
    if dados.genero is not None and dados.genero not in GENEROS:
        raise DadosInvalidos("Coleção inválida. Use Masculino ou Feminino.")
    if dados.estacao is not None and dados.estacao not in ESTACOES:
        raise DadosInvalidos("Estação inválida. Use Inverno, Verão ou Atemporal.")
    sem_custo = next((v for v in dados.variacoes if v.preco_custo is None or not v.preco_custo >= 0), None)
    if sem_custo is not None:
        raise DadosInvalidos(f"Informe o preço de custo da variação {sem_custo.sku.strip().upper() or sem_custo.cor}.")
    return categoria


def _custo(valor: float) -> Decimal:
    return Decimal(str(valor)).quantize(Decimal("0.01"))


def _salvar_variacoes(db: Session, produto: m.Produto, dados: ProdutoEntrada) -> list[dict]:
    """Atualiza as variações enviadas; as novas recebem estoque zerado em todas as lojas.
    Variações omitidas não são apagadas, porque têm histórico de estoque.
    Devolve as mudanças de custo e as variações novas, para o log."""
    alteracoes = []
    existentes = {v.id: v for v in produto.variacoes}
    for entrada in dados.variacoes:
        campos = {
            "sku": entrada.sku.strip().upper(),
            "tamanho": entrada.tamanho.strip(),
            "cor": entrada.cor.strip(),
            "preco_custo": _custo(entrada.preco_custo),
        }
        if entrada.id is not None:
            variacao = existentes.get(entrada.id)
            if variacao is None:
                raise DadosInvalidos(f"A variação {entrada.id} não pertence a este produto.")
            if variacao.preco_custo != campos["preco_custo"]:
                de = moeda(variacao.preco_custo) if variacao.preco_custo is not None else "—"
                alteracoes.append({"campo": f"Custo {campos['sku']}", "de": de, "para": moeda(campos["preco_custo"])})
            for campo, valor in campos.items():
                setattr(variacao, campo, valor)
        else:
            variacao = m.Variacao(produto=produto, **campos)
            sessao.adicionar(db, variacao)
            criar_estoques_zerados(db, variacao)
            alteracoes.append(
                {
                    "campo": f"Nova variação {campos['sku']}",
                    "de": "—",
                    "para": f"{campos['cor']} · {campos['tamanho']} · custo {moeda(campos['preco_custo'])}",
                }
            )
    return alteracoes


def _aplicar_imagem(produto: m.Produto, dados: ProdutoEntrada) -> dict | None:
    """imagem troca a foto; remover_imagem volta à ilustração. Devolve a mudança para o log (ou None)."""
    if dados.imagem is not None:
        nome, tipo, conteudo = anexos.ler_imagem(dados.imagem.nome, dados.imagem.tipo, dados.imagem.conteudo_base64)
        tinha_foto = produto.imagem is not None
        if tinha_foto:
            foto = produto.imagem
            foto.nome, foto.tipo, foto.tamanho, foto.dados, foto.atualizado_em = nome, tipo, len(conteudo), conteudo, agora()
        else:
            produto.imagem = m.ImagemProduto(nome=nome, tipo=tipo, tamanho=len(conteudo), dados=conteudo, atualizado_em=agora())
        return {"campo": "Foto", "de": "Foto anterior" if tinha_foto else "Ilustração", "para": nome}
    if dados.remover_imagem and produto.imagem is not None:
        produto.imagem = None
        return {"campo": "Foto", "de": "Foto enviada", "para": "Ilustração"}
    return None


_ROTULOS = {
    "nome": "Nome",
    "categoria": "Categoria",
    "genero": "Coleção",
    "estacao": "Estação",
    "preco_base": "Preço de venda",
    "ativo": "Ativo",
}
_FORMATOS = {"preco_base": moeda, "ativo": lambda v: "Sim" if v else "Não"}


def _campos_log(produto: m.Produto) -> dict:
    return {
        "nome": produto.nome,
        "categoria": produto.categoria.nome,
        "genero": produto.genero,
        "estacao": produto.estacao,
        "preco_base": Decimal(str(produto.preco_base)).quantize(Decimal("0.01")),
        "ativo": produto.ativo,
    }


def criar(db: Session, dados: ProdutoEntrada, usuario: m.Usuario) -> m.Produto:
    categoria = _validar(db, dados, None)
    produto = m.Produto(
        nome=dados.nome.strip(),
        categoria=categoria,
        preco_base=dados.preco_base,
        ativo=dados.ativo,
        genero=dados.genero,
        estacao=dados.estacao or ESTACAO_PADRAO,
        descricao=dados.descricao,
        composicao=dados.composicao,
        cuidados=dados.cuidados,
    )
    _aplicar_imagem(produto, dados)
    sessao.adicionar(db, produto)
    _salvar_variacoes(db, produto, dados)
    sessao.gerar_ids(db)
    log_acoes.registrar(
        db,
        usuario,
        "PRODUTOS",
        "CADASTROU",
        f"Cadastrou o produto {produto.nome} ({moeda(produto.preco_base)})",
        referencia=("produto", produto.id),
    )
    sessao.confirmar(db)
    return obter(db, produto.id)


def atualizar(db: Session, produto_id: int, dados: ProdutoEntrada, usuario: m.Usuario) -> m.Produto:
    produto = obter(db, produto_id)
    nome_anterior = produto.nome
    antes = _campos_log(produto)
    produto.categoria = _validar(db, dados, produto.id)
    foto = _aplicar_imagem(produto, dados)
    produto.nome = dados.nome.strip()
    produto.preco_base = dados.preco_base
    produto.ativo = dados.ativo
    # Só mudam se forem enviados; coleção e estação nunca ficam vazias (o produto sairia da vitrine)
    for campo in ("genero", "estacao", "descricao", "composicao", "cuidados"):
        if campo in dados.model_fields_set and not (campo in ("genero", "estacao") and getattr(dados, campo) is None):
            setattr(produto, campo, getattr(dados, campo))
    alteracoes = log_acoes.mudancas(antes, _campos_log(produto), _ROTULOS, _FORMATOS)
    if foto:
        alteracoes.append(foto)
    alteracoes += _salvar_variacoes(db, produto, dados)
    if alteracoes:
        log_acoes.registrar(
            db, usuario, "PRODUTOS", "EDITOU", f"Editou o produto {nome_anterior}", alteracoes, referencia=("produto", produto.id)
        )
    sessao.confirmar(db)
    sessao.descartar_cache(db)
    return obter(db, produto.id)
