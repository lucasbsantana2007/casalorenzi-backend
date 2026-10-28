"""Como o assistente entende uma busca de peça escrita em português ("camisa azul M até R$ 150").

Só vocabulário e regras de texto, sem banco: as regras do assistente usam para interpretar a mensagem e a
ferramenta de busca usa para comparar o pedido com o catálogo. A busca nunca inventa: quando nada bate,
ela afrouxa um filtro por vez (cor parecida, outro tamanho...) e diz o que mudou, ou diz que não encontrou.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from src.utils.texto import moeda, normalizar

# ---------- Cores ----------

# Família de cor -> (cores exatas, cores parecidas) do catálogo, já normalizadas (sem acento, minúsculas).
# As parecidas só entram quando não há nenhuma peça na cor exata, e o cliente é avisado.
CORES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "azul": (("azul", "azul marinho", "marinho", "azul ceu", "azul riviera"), ("jeans claro", "jeans escuro")),
    "marinho": (("azul marinho", "marinho"), ("azul", "azul ceu", "azul riviera", "jeans escuro")),
    "azul claro": (("azul ceu", "azul riviera"), ("azul", "jeans claro")),
    "branco": (("branco",), ("off white", "off-white")),
    "off white": (("off white", "off-white"), ("branco", "areia")),
    "preto": (("preto",), ("grafite",)),
    "cinza": (("cinza mescla", "grafite", "cinza"), ()),
    "bege": (("bege", "areia"), ("camel", "off white", "off-white")),
    "marrom": (("marrom", "caramelo", "conhaque", "camel"), ("bege",)),
    "camel": (("camel", "caramelo"), ("marrom", "bege")),
    "verde": (("verde oliva", "verde"), ()),
    "vinho": (("vinho",), ()),
    "vermelho": ((), ("vinho",)),
    "lilas": (("lilas",), ()),
    "roxo": ((), ("lilas", "vinho")),
    "rosa": ((), ("lilas",)),
    "amarelo": (("amarelo",), ()),
}

# Expressões (normalizadas) -> família. As de duas palavras são procuradas antes das de uma.
_EXPRESSOES_COR = {
    "azul marinho": "marinho",
    "azul escuro": "marinho",
    "azul claro": "azul claro",
    "azul ceu": "azul claro",
    "azul bebe": "azul claro",
    "off white": "off white",
    "off-white": "off white",
    "verde oliva": "verde",
    "verde militar": "verde",
    "cinza mescla": "cinza",
}
_PALAVRAS_COR = {
    **{p: "azul" for p in ("azul", "azuis")},
    "marinho": "marinho",
    "celeste": "azul claro",
    **{p: "branco" for p in ("branco", "branca", "brancos", "brancas")},
    **{p: "off white" for p in ("offwhite", "creme", "cru", "gelo")},
    **{p: "preto" for p in ("preto", "preta", "pretos", "pretas", "black")},
    **{p: "cinza" for p in ("cinza", "cinzas", "mescla", "grafite", "chumbo")},
    **{p: "bege" for p in ("bege", "beges", "areia", "nude", "caqui", "khaki")},
    **{p: "marrom" for p in ("marrom", "marrons", "caramelo", "conhaque", "chocolate", "cafe")},
    "camel": "camel",
    **{p: "verde" for p in ("verde", "verdes", "oliva", "militar")},
    **{p: "vinho" for p in ("vinho", "bordo", "bordeaux", "marsala")},
    **{p: "vermelho" for p in ("vermelho", "vermelha", "vermelhos", "vermelhas")},
    **{p: "lilas" for p in ("lilas", "lavanda")},
    **{p: "roxo" for p in ("roxo", "roxa", "roxos", "roxas")},
    **{p: "rosa" for p in ("rosa", "rosas", "pink", "rosinha")},
    **{p: "amarelo" for p in ("amarelo", "amarela", "amarelos", "amarelas", "mostarda")},
}

# ---------- Tipos de peça ----------

# Tipo -> (categorias do catálogo, palavras no nome da peça). A peça é do tipo quando a categoria dela
# está na lista ou o nome tem uma das palavras (as categorias mudam de nome entre as marcas).
TIPOS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "camisa": (("Camisas", "Camisaria"), ("camisa", "overshirt")),
    "camiseta": (("Camisetas",), ("camiseta", "tee", "regata")),
    "regata": ((), ("regata",)),
    "polo": ((), ("polo",)),
    "blusa": (("Camisetas", "Tricô", "Tops e Croppeds"), ("blusa",)),
    "calca": (("Calças",), ("calca",)),
    "bermuda": (("Bermudas e Shorts",), ("bermuda", "short")),
    "saia": (("Saias",), ("saia", "minissaia")),
    "vestido": (("Vestidos",), ("vestido",)),
    "macacao": ((), ("macacao",)),
    "jaqueta": (("Jaquetas", "Outerwear"), ("jaqueta", "bomber", "corta-vento", "puffer", "trench", "blazer")),
    "blazer": ((), ("blazer",)),
    "moletom": (("Moletons",), ("moletom", "hoodie")),
    "trico": (("Tricô",), ("trico", "tricot", "sueter", "cardiga", "cardigan", "colete")),
    "sueter": ((), ("sueter",)),
    "cardiga": ((), ("cardiga", "cardigan")),
    "top": (("Tops e Croppeds",), ("top", "cropped", "body")),
    "cropped": ((), ("cropped",)),
    "body": ((), ("body",)),
    "acessorio": (("Acessórios",), ()),
    "bolsa": ((), ("bolsa", "pochete", "ecobag")),
    "cinto": ((), ("cinto",)),
    "chapeu": ((), ("bone", "bucket", "chapeu", "gorro")),
    "meia": ((), ("meia",)),
    "lenco": ((), ("lenco",)),
}
_PALAVRAS_TIPO = {
    **{p: "camisa" for p in ("camisa", "camisas", "camisaria", "overshirt", "chemise")},
    **{p: "camiseta" for p in ("camiseta", "camisetas", "tshirt", "t-shirt", "camisinha", "baby", "tee")},
    **{p: "regata" for p in ("regata", "regatas")},
    **{p: "polo" for p in ("polo", "polos")},
    **{p: "blusa" for p in ("blusa", "blusas", "blusinha")},
    **{p: "calca" for p in ("calca", "calcas", "jogger", "pantalona")},
    **{p: "bermuda" for p in ("bermuda", "bermudas", "short", "shorts")},
    **{p: "saia" for p in ("saia", "saias", "minissaia")},
    **{p: "vestido" for p in ("vestido", "vestidos")},
    **{p: "macacao" for p in ("macacao", "macacoes")},
    **{p: "jaqueta" for p in ("jaqueta", "jaquetas", "casaco", "casacos", "bomber", "trench", "puffer", "agasalho")},
    **{p: "blazer" for p in ("blazer", "blazers")},
    **{p: "moletom" for p in ("moletom", "moletons", "hoodie", "hoodies", "canguru")},
    **{p: "trico" for p in ("trico", "tricot", "malha", "tricos")},
    **{p: "sueter" for p in ("sueter", "sueteres", "pulover")},
    **{p: "cardiga" for p in ("cardiga", "cardigas", "cardigan", "cardigans", "colete")},
    **{p: "top" for p in ("top", "tops")},
    **{p: "cropped" for p in ("cropped", "croppeds")},
    "body": "body",
    **{p: "acessorio" for p in ("acessorio", "acessorios")},
    **{p: "bolsa" for p in ("bolsa", "bolsas", "pochete", "ecobag")},
    **{p: "cinto" for p in ("cinto", "cintos")},
    **{p: "chapeu" for p in ("bone", "bones", "chapeu", "chapeus", "gorro", "bucket")},
    **{p: "meia" for p in ("meia", "meias")},
    **{p: "lenco" for p in ("lenco", "lencos")},
}
# "corta vento" é uma peça (jaqueta), escrita em duas palavras
_EXPRESSOES_TIPO = {"corta vento": "jaqueta", "corta-vento": "jaqueta", "tamanho unico": None}

# ---------- Tamanhos ----------

TAMANHOS_LETRA = ("XP", "PP", "P", "M", "G", "GG", "XG", "XGG", "EG", "U")
_SINONIMOS_TAMANHO = {"UNICO": "U", "ÚNICO": "U", "TU": "U", "XGG": "XGG", "EGG": "XGG"}
TAMANHO_NUMERICO_MIN, TAMANHO_NUMERICO_MAX = 34, 56
# Peças vendidas por número (36, 38, 40...): um número solto na frase é o tamanho
TIPOS_GRADE_NUMERICA = frozenset({"calca", "bermuda", "saia"})

# ---------- Marca, gênero e palavras que não dizem nada sobre a peça ----------

_MARCAS = {"vulto": "VULTO", "lorenzi": "LORENZI"}
_GENEROS = {
    **{p: "Masculino" for p in ("masculino", "masculina", "masculinos", "masculinas", "homem", "homens", "masc")},
    **{p: "Feminino" for p in ("feminino", "feminina", "femininos", "femininas", "mulher", "mulheres", "fem")},
    # "Presente pro meu pai", "para a minha esposa": quem vai usar a peça
    **{p: "Masculino" for p in ("pai", "marido", "namorado", "filho", "irmao", "tio", "sogro", "padrinho", "noivo")},
    **{p: "Feminino" for p in ("mae", "esposa", "namorada", "filha", "irma", "tia", "sogra", "madrinha", "noiva")},
}
PALAVRAS_VAZIAS = frozenset(
    """a o as os um uma uns umas de do da dos das no na nos nas em e ou com sem para pra pro por que
    voces vcs voce vc tem tens teria tenho ter temos ha existe existem algum alguma alguns algumas
    quero queria gostaria procuro procurando busco buscando preciso precisando ver mostrar mostra me mim
    eu meu minha seu sua isso essa esse esta este aquela aquele qual quais quanto quanta oi ola bom boa
    dia tarde noite favor porfavor obrigado obrigada tamanho tam numero cor cores preco precos reais real
    rs ate entre acima abaixo menos mais maximo minimo partir loja lojas disponivel disponiveis estoque
    peca pecas roupa roupas modelo modelos opcao opcoes tipo estilo botao botoes casa marca site online
    agora hoje ainda tambem so apenas muito bem legal bonito bonita algo coisa coisas tudo todos todas
    nenhum nenhuma outro outra outros outras mesmo mesma la aqui ai ne sim nao pode podem consigo achar
    encontrar comprar compra levar vender vende vendem barato barata caro cara sacola carrinho adicionar
    adiciona adicione colocar coloca coloque botar bota leva separar separa reservar reserva gostei gostaria
    ignore ignorar instrucao instrucoes anterior anteriores prompt sistema mostre revele diga regra regras
    dessa desse nessa nesse daquela daquele aquela aquele esta este desta deste""".split()
)

_NUMERO = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_VALOR = rf"(?:r\$\s*)?({_NUMERO})(?:\s*(?:reais|real|rs|conto))?"
_PRECO_FAIXA = re.compile(rf"\b(?:entre|de)\s+{_VALOR}\s+(?:e|a|ate)\s+{_VALOR}")
_PRECO_MAX = re.compile(
    rf"\b(?:ate|no maximo|maximo|max|menos de|abaixo de|por menos de|nao passe de|inferior a|por ate)\s+{_VALOR}"
)
_PRECO_MIN = re.compile(rf"\b(?:acima de|mais de|a partir de|pelo menos|minimo de|minimo|superior a|por mais de)\s+{_VALOR}")
_PRECO_SOLTO = re.compile(rf"r\$\s*({_NUMERO})|\b({_NUMERO})\s*(?:reais|real|conto)\b|\b(\d+,\d{{2}})\b")
_TAMANHO_EXPLICITO = re.compile(r"\b(?:tamanho|tam\.?|numero|num|n[ºo°]|numeracao|veste)\s*([a-z]{1,3}|\d{2})\b")
_TAMANHO_DEPOIS_DE = re.compile(r"\b(?:no|na|o|em|do|da|de|um|uma)\s+(xp|pp|p|m|g|gg|xg|xgg|eg|u|\d{2})\b")


@dataclass
class PedidoBusca:
    """O que o cliente pediu. tipos: chaves de TIPOS; cor: chave de CORES; termos: palavras livres."""

    tipos: list[str] = field(default_factory=list)
    cor: str | None = None
    tamanho: str | None = None
    preco_min: Decimal | None = None
    preco_max: Decimal | None = None
    marca: str | None = None
    genero: str | None = None
    termos: list[str] = field(default_factory=list)

    def vazio(self) -> bool:
        return not (self.tipos or self.cor or self.tamanho or self.preco_min or self.preco_max or self.termos)

    def para_dict(self) -> dict:
        return {
            "tipos": self.tipos,
            "cor": self.cor,
            "tamanho": self.tamanho,
            "precoMin": float(self.preco_min) if self.preco_min is not None else None,
            "precoMax": float(self.preco_max) if self.preco_max is not None else None,
            "marca": self.marca,
            "genero": self.genero,
            "termos": self.termos,
        }

    @classmethod
    def de_dict(cls, dados: dict | None) -> "PedidoBusca":
        dados = dados or {}

        def dec(valor) -> Decimal | None:
            return Decimal(str(valor)) if valor is not None else None

        return cls(
            tipos=[t for t in dados.get("tipos") or [] if t in TIPOS],
            cor=dados.get("cor") if dados.get("cor") in CORES else None,
            tamanho=normalizar_tamanho(dados.get("tamanho")),
            preco_min=dec(dados.get("precoMin")),
            preco_max=dec(dados.get("precoMax")),
            marca=dados.get("marca") if dados.get("marca") in ("LORENZI", "VULTO") else None,
            genero=dados.get("genero") if dados.get("genero") in ("Masculino", "Feminino") else None,
            termos=[str(t) for t in dados.get("termos") or []][:6],
        )


def _decimal(texto: str) -> Decimal | None:
    """'1.299,90' -> 1299.90; '150' -> 150; '150.5' -> 150.5."""
    limpo = texto.strip()
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", limpo):
        limpo = limpo.replace(".", "")
    try:
        valor = Decimal(limpo)
    except InvalidOperation:
        return None
    return valor if valor > 0 else None


def extrair_preco(texto: str) -> tuple[Decimal | None, Decimal | None, str]:
    """(preço mínimo, preço máximo, texto sem os trechos de preço). Valor solto ('150 reais') é teto."""
    minimo = maximo = None
    restante = texto
    if faixa := _PRECO_FAIXA.search(restante):
        a, b = _decimal(faixa.group(1)), _decimal(faixa.group(2))
        if a and b:
            minimo, maximo = min(a, b), max(a, b)
            restante = restante.replace(faixa.group(0), " ")
    if maximo is None and (teto := _PRECO_MAX.search(restante)):
        maximo = _decimal(teto.group(1))
        restante = restante.replace(teto.group(0), " ")
    if minimo is None and (piso := _PRECO_MIN.search(restante)):
        minimo = _decimal(piso.group(1))
        restante = restante.replace(piso.group(0), " ")
    if minimo is None and maximo is None and (solto := _PRECO_SOLTO.search(restante)):
        maximo = _decimal(solto.group(1) or solto.group(2) or solto.group(3))
        restante = restante.replace(solto.group(0), " ")
    return minimo, maximo, restante


def normalizar_tamanho(valor: str | None) -> str | None:
    """'m' -> 'M'; 'único' -> 'U'; '40' -> '40'. Fora da grade conhecida: None."""
    if valor is None:
        return None
    texto = str(valor).strip().upper().replace("TAMANHO", "").strip()
    texto = _SINONIMOS_TAMANHO.get(texto, texto)
    if texto in TAMANHOS_LETRA:
        return texto
    if texto.isdigit() and TAMANHO_NUMERICO_MIN <= int(texto) <= TAMANHO_NUMERICO_MAX:
        return texto
    return None


def tamanho_do_catalogo(valor: str | None) -> str:
    """Tamanho gravado na variação, comparável com normalizar_tamanho ('Único' -> 'U')."""
    return normalizar_tamanho(valor) or str(valor or "").strip().upper()


def extrair_tamanho(texto_original: str, texto: str, curto: bool) -> tuple[str | None, str]:
    """Tamanho pedido e o texto sem ele. Letra solta (M, G) só vale escrita em maiúscula, depois de
    'tamanho'/'no'/'na', ou numa mensagem curta ('M', 'e o G?'): evita ler 'e' ou 'o' como tamanho."""
    if achado := _TAMANHO_EXPLICITO.search(texto):
        tamanho = normalizar_tamanho(achado.group(1))
        if tamanho:
            return tamanho, texto.replace(achado.group(0), " ")
    if achado := _TAMANHO_DEPOIS_DE.search(texto):
        tamanho = normalizar_tamanho(achado.group(1))
        # "de 40" é preço ou quantidade; número só vale depois de no/na/o/um
        if tamanho and not (tamanho.isdigit() and achado.group(0).split()[0] in ("de", "da", "do", "em")):
            return tamanho, texto.replace(achado.group(0), " ")
    for token in re.findall(r"[A-Za-zÀ-ÿ]+|\d+", texto_original):
        tamanho = normalizar_tamanho(token)
        if tamanho is None:
            continue
        if token.isdigit():
            if curto:
                return tamanho, re.sub(rf"\b{token}\b", " ", texto, count=1)
            continue
        maiuscula = token.isupper() and len(token) <= 3
        if maiuscula or (curto and len(token) <= 3):
            return tamanho, re.sub(rf"\b{token.lower()}\b", " ", texto, count=1)
    return None, texto


def _tokens(texto: str) -> list[str]:
    return re.findall(r"[a-z0-9\-]+", texto)


def interpretar_busca(mensagem: str) -> PedidoBusca:
    """Lê tipo de peça, cor, tamanho, faixa de preço, marca e gênero de uma frase em português."""
    texto = normalizar(mensagem)
    pedido = PedidoBusca()
    pedido.preco_min, pedido.preco_max, texto = extrair_preco(texto)
    curto = len(_tokens(texto)) <= 4
    pedido.tamanho, texto = extrair_tamanho(mensagem, texto, curto)

    for expressao, familia in _EXPRESSOES_COR.items():
        if re.search(rf"\b{re.escape(expressao)}\b", texto):
            pedido.cor = pedido.cor or familia
            texto = texto.replace(expressao, " ")
    for expressao, tipo in _EXPRESSOES_TIPO.items():
        if expressao in texto:
            if tipo and tipo not in pedido.tipos:
                pedido.tipos.append(tipo)
            texto = texto.replace(expressao, " ")

    for token in _tokens(texto):
        if token in _PALAVRAS_TIPO:
            tipo = _PALAVRAS_TIPO[token]
            if tipo not in pedido.tipos:
                pedido.tipos.append(tipo)
        elif token in _PALAVRAS_COR:
            pedido.cor = pedido.cor or _PALAVRAS_COR[token]
        elif token in _MARCAS:
            pedido.marca = _MARCAS[token]
        elif token in _GENEROS:
            pedido.genero = _GENEROS[token]
        elif token not in PALAVRAS_VAZIAS and len(token) >= 3 and not token.isdigit():
            if token not in pedido.termos:
                pedido.termos.append(token)
    # "calça de alfaiataria 44": peças com grade numérica aceitam o número solto como tamanho
    if pedido.tamanho is None and set(pedido.tipos) & TIPOS_GRADE_NUMERICA:
        for numero in re.findall(r"\b\d{2}\b", texto):
            if (tamanho := normalizar_tamanho(numero)) is not None:
                pedido.tamanho = tamanho
                break
    pedido.termos = pedido.termos[:6]
    return pedido


# ---------- Comparação com o catálogo ----------


def familia_da_cor(valor: str | None) -> str | None:
    """Cor escrita pelo cliente ou pelo modelo ('azul-marinho', 'Preta') -> família de CORES."""
    if not valor:
        return None
    texto = normalizar(valor).replace("-", " ").strip()
    if texto in CORES:
        return texto
    if texto in _EXPRESSOES_COR:
        return _EXPRESSOES_COR[texto]
    for token in _tokens(texto):
        if token in _PALAVRAS_COR:
            return _PALAVRAS_COR[token]
    return None


def tipo_da_peca(valor: str | None) -> list[str]:
    """Tipo escrito ('calças', 'camisa de botão') -> chaves de TIPOS."""
    if not valor:
        return []
    texto = normalizar(valor)
    tipos = [tipo for expressao, tipo in _EXPRESSOES_TIPO.items() if tipo and expressao in texto]
    for token in _tokens(texto):
        tipo = _PALAVRAS_TIPO.get(token) or (token if token in TIPOS else None)
        if tipo and tipo not in tipos:
            tipos.append(tipo)
    return tipos


def nota_da_cor(cor_do_catalogo: str, familia: str | None) -> int:
    """2: cor exata; 1: parecida; 0: outra cor. Sem cor pedida: 2 (tudo serve)."""
    if not familia:
        return 2
    exatas, parecidas = CORES.get(familia, ((), ()))
    cor = normalizar(cor_do_catalogo).strip()
    if cor in exatas or any(cor.startswith(f"{e} ") for e in exatas):
        return 2
    if cor in parecidas:
        return 1
    return 0


def e_do_tipo(nome: str, categoria: str, tipos: list[str]) -> bool:
    if not tipos:
        return True
    palavras = set(_tokens(normalizar(nome)))
    for tipo in tipos:
        categorias, nomes = TIPOS.get(tipo, ((), ()))
        if categoria in categorias or any(n in palavras or n in normalizar(nome) for n in nomes):
            return True
    return False


def termos_no_texto(termos: list[str], *textos: str | None) -> int:
    """Quantos termos livres aparecem nos textos da peça (nome, categoria, cor, coleção, descrição)."""
    alvo = normalizar(" ".join(t or "" for t in textos))
    return sum(1 for termo in termos if termo in alvo)


ROTULO_TIPO = {
    "calca": "calça",
    "trico": "tricô",
    "macacao": "macacão",
    "cardiga": "cardigã",
    "sueter": "suéter",
    "acessorio": "acessório",
    "lenco": "lenço",
    "chapeu": "boné ou chapéu",
}
ROTULO_COR = {"lilas": "lilás", "azul claro": "azul-claro", "off white": "off-white", "marinho": "azul-marinho"}
# "na cor branca": a cor concorda com "cor" (feminino)
_COR_FEMININA = {"branco": "branca", "preto": "preta", "amarelo": "amarela", "vermelho": "vermelha", "roxo": "roxa"}


def rotulo_cor(familia: str | None) -> str:
    return ROTULO_COR.get(familia or "", familia or "")


def descrever(pedido: PedidoBusca) -> str:
    """'camisa azul, tamanho M, até R$ 150,00' (para o histórico e as respostas)."""
    partes = []
    if pedido.tipos:
        partes.append(" ou ".join(ROTULO_TIPO.get(t, t) for t in pedido.tipos))
    if pedido.termos:
        partes.append(" ".join(pedido.termos))
    texto = " ".join(partes) or {"Masculino": "peças masculinas", "Feminino": "peças femininas"}.get(pedido.genero, "peças")
    if pedido.cor:
        texto += f" na cor {_COR_FEMININA.get(pedido.cor, rotulo_cor(pedido.cor))}"
    if pedido.tamanho:
        texto += f", tamanho {pedido.tamanho}"
    if pedido.preco_min is not None and pedido.preco_max is not None:
        texto += f", entre {moeda(pedido.preco_min)} e {moeda(pedido.preco_max)}"
    elif pedido.preco_max is not None:
        texto += f", até {moeda(pedido.preco_max)}"
    elif pedido.preco_min is not None:
        texto += f", a partir de {moeda(pedido.preco_min)}"
    if pedido.marca:
        texto += ", da " + ("Vulto" if pedido.marca == "VULTO" else "Casa Lorenzi")
    return texto
