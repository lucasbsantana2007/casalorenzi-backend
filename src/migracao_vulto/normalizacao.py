"""Padronização dos dados da Vulto: funções puras (sem banco), usadas por todos os domínios.

Cada função recebe o valor como veio da origem (o texto do staging ou o tipo que o Excel deu à
célula) e devolve o valor no padrão da plataforma. Valor vazio vira None. Valor que não dá para
converter com segurança levanta ValorInvalido: quem chama decide (NULL ou descarte) e registra a
ocorrência com o valor original. Nada aqui chuta.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from src.entities.cliente import cpf_valido, email_valido, telefone_e164
from src.entities.pedido import CANAL_APP, CANAL_LOJA, CANAL_SITE
from src.entities.produto import alias_normalizado

FUSO_ORIGEM = ZoneInfo("America/Sao_Paulo")  # data sem fuso na origem é horário de Brasília
CENTAVO = Decimal("0.01")


class ValorInvalido(ValueError):
    """O valor existe, mas não dá para converter com segurança."""


def _vazio(valor) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _chave(texto) -> str:
    """Texto para comparar: sem acento, minúsculo, espaços únicos."""
    return re.sub(r"\s+", " ", sem_acento(str(texto)).strip().lower())


# ---------- Dinheiro ----------

_BR = re.compile(r"-?(\d{1,3}(\.\d{3})+|\d+),\d{1,2}")  # 1.234,56 · 379,80
_PONTO_DECIMAL = re.compile(r"-?\d+(\.\d{1,2})?")  # 129.8 · 19081
_MILHAR_PONTO = re.compile(r"-?\d{1,3}(\.\d{3})+")  # 1.234 (dinheiro não tem 3 casas)


def dinheiro(valor) -> Decimal | None:
    """Reais com 2 casas: "R$ 149,90", "379,80", "1.234,56", "129.8", 149.9. Um inteiro ("19081")
    é lido como reais; se pode ser centavos (o app grava assim), use escalas() e confira com a conta
    da venda."""
    if _vazio(valor):
        return None
    if isinstance(valor, bool):
        raise ValorInvalido(f"Valor em dinheiro inválido: {valor!r}")
    if isinstance(valor, int | float | Decimal):
        return Decimal(str(valor)).quantize(CENTAVO)
    texto = re.sub(r"\s", "", str(valor).replace("R$", ""))
    try:
        if _BR.fullmatch(texto):
            return Decimal(texto.replace(".", "").replace(",", ".")).quantize(CENTAVO)
        if _PONTO_DECIMAL.fullmatch(texto):
            return Decimal(texto).quantize(CENTAVO)
        if _MILHAR_PONTO.fullmatch(texto):
            return Decimal(texto.replace(".", "")).quantize(CENTAVO)
    except InvalidOperation:
        pass
    raise ValorInvalido(f"Valor em dinheiro inválido: {valor!r}")


def escalas(valor) -> dict[str, Decimal]:
    """Interpretações possíveis de um valor: sempre em reais; e, se veio como inteiro sem separador,
    também em centavos. A certa é a que bate com a soma dos itens (detecção nunca é às cegas)."""
    reais = dinheiro(valor)
    if reais is None:
        return {}
    candidatos = {"reais": reais}
    texto = str(valor).strip()
    if re.fullmatch(r"-?\d+", texto):
        candidatos["centavos"] = (reais / 100).quantize(CENTAVO)
    return candidatos


# ---------- Datas ----------


@dataclass(frozen=True)
class Data:
    momento: datetime  # sempre com fuso
    precisao: str  # "segundo", "minuto", "dia" ou "mes"


_MESES = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}
_EXCEL_ZERO = datetime(1899, 12, 30)


def _no_fuso(momento: datetime) -> datetime:
    return momento if momento.tzinfo else momento.replace(tzinfo=FUSO_ORIGEM)


def _dia(ano: int, mes: int, dia: int, original) -> datetime:
    try:
        return datetime(ano, mes, dia, tzinfo=FUSO_ORIGEM)
    except ValueError:
        raise ValorInvalido(f"Data inexistente: {original!r}") from None


def data_hora(valor, *, ano_padrao: int | None = None, serial_excel: bool = False) -> Data | None:
    """Data com fuso. Sem fuso na origem ⇒ America/Sao_Paulo; sufixo Z ⇒ UTC; offset (-03:00) respeitado.
    Aceita ISO (com ou sem T, Z, microssegundos, offset), dd/mm/aaaa [hh:mm[:ss]], dd/mm/aa, dd/mm (com
    ano_padrao), mês/ano ("jan/23", "set/2023" → dia 1, precisão "mes") e o número de série do Excel
    (célula numérica, ou texto só de dígitos com serial_excel=True)."""
    if _vazio(valor):
        return None
    if isinstance(valor, datetime):
        precisao = "dia" if valor.time() == time(0) and valor.tzinfo is None else "segundo"
        return Data(_no_fuso(valor), precisao)
    if isinstance(valor, date):
        return Data(_dia(valor.year, valor.month, valor.day, valor), "dia")
    if isinstance(valor, int | float) and not isinstance(valor, bool):
        return _serial(valor)
    texto = str(valor).strip()
    if serial_excel and re.fullmatch(r"\d+(\.\d+)?", texto):
        return _serial(float(texto))

    if re.match(r"\d{4}-\d{2}-\d{2}", texto):
        try:
            momento = datetime.fromisoformat(texto)
        except ValueError:
            raise ValorInvalido(f"Data inválida: {valor!r}") from None
        if len(texto) == 10:
            return Data(_no_fuso(momento), "dia")
        precisao = "minuto" if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", texto) else "segundo"
        return Data(_no_fuso(momento).astimezone(UTC) if texto.endswith("Z") else _no_fuso(momento), precisao)

    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", texto):
        dia, mes, ano = int(m[1]), int(m[2]), int(m[3])
        ano = ano + 2000 if ano < 100 else ano
        momento = _dia(ano, mes, dia, valor)
        if m[4] is None:
            return Data(momento, "dia")
        momento = momento.replace(hour=int(m[4]), minute=int(m[5]), second=int(m[6] or 0))
        return Data(momento, "segundo" if m[6] else "minuto")

    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})", texto):
        if ano_padrao is None:
            raise ValorInvalido(f"Data sem ano: {valor!r}")
        return Data(_dia(ano_padrao, int(m[2]), int(m[1]), valor), "dia")

    if m := re.fullmatch(r"([a-zç]{3})[a-zç]*/(\d{4}|\d{2})", _chave(texto)):
        if m[1] not in _MESES:
            raise ValorInvalido(f"Mês inválido: {valor!r}")
        ano = int(m[2]) + (2000 if len(m[2]) == 2 else 0)
        return Data(_dia(ano, _MESES[m[1]], 1, valor), "mes")

    raise ValorInvalido(f"Data em formato desconhecido: {valor!r}")


def _serial(numero: float) -> Data:
    if not 20000 <= numero <= 80000:  # 1954 a 2119: fora disso não é data do Excel
        raise ValorInvalido(f"Número de série do Excel fora do esperado: {numero!r}")
    momento = _EXCEL_ZERO + timedelta(days=float(numero))
    return Data(momento.replace(tzinfo=FUSO_ORIGEM), "dia" if float(numero).is_integer() else "minuto")


# ---------- Pessoas e contato ----------


def cpf(valor, *, numero_excel: bool = False) -> str | None:
    """11 dígitos sem máscara, com dígito verificador válido. Aceita máscara e espaços
    ("936.216.440-08", " 441 954 145 80"). numero_excel=True (ou um int): o Excel guardou como número e
    pode ter comido os zeros à esquerda; completa até 11 dígitos."""
    if _vazio(valor):
        return None
    if isinstance(valor, int) and not isinstance(valor, bool):
        valor, numero_excel = str(valor), True
    texto = str(valor).strip()
    if re.search(r"[a-zA-Z@]", texto):
        raise ValorInvalido(f"Não é um CPF: {valor!r}")
    digitos = re.sub(r"\D", "", texto)
    if numero_excel and 8 <= len(digitos) < 11:
        digitos = digitos.zfill(11)
    if len(digitos) != 11 or not cpf_valido(digitos):
        raise ValorInvalido(f"CPF inválido: {valor!r}")
    return digitos


def email(valor) -> str | None:
    """Minúsculo, sem espaços, formato validado."""
    if _vazio(valor):
        return None
    texto = re.sub(r"\s", "", str(valor)).lower()
    if not email_valido(texto):
        raise ValorInvalido(f"E-mail inválido: {valor!r}")
    return texto


def telefone(valor) -> str | None:
    """E.164 (+5511948854328). Aceita "11951021527", "+55 11 91217-2644", "(11) 98369-1660". Sem DDD
    (ex.: "90429-6274") não dá para saber a cidade: inválido."""
    if _vazio(valor):
        return None
    if (numero := telefone_e164(valor)) is None:
        raise ValorInvalido(f"Telefone inválido: {valor!r}")
    return numero


def instagram(valor) -> str | None:
    """Handle minúsculo, sem @ (aceita também o link do perfil)."""
    if _vazio(valor):
        return None
    texto = str(valor).strip().lower()
    texto = re.sub(r"^(https?://)?(www\.)?instagram\.com/", "", texto).strip("/").lstrip("@")
    if not re.fullmatch(r"[a-z0-9._]{1,30}", texto):
        raise ValorInvalido(f"Instagram inválido: {valor!r}")
    return texto


def nome_pessoa(valor) -> str | None:
    """Trim e espaços únicos; a capitalização fica como veio (o original continua no staging)."""
    if _vazio(valor):
        return None
    return re.sub(r"\s+", " ", str(valor)).strip()


@dataclass(frozen=True)
class Referencia:
    tipo: str  # "cpf", "email" ou "telefone"
    valor: str
    ambigua: bool = False  # 11 dígitos que são CPF válido e também têm cara de celular


def referencia_cliente(valor) -> Referencia | None:
    """O cliente_ref do legado mistura CPF, e-mail e telefone ("depende de quem cadastrou").
    CPF válido vence; 11 dígitos com cara de celular que também passam no dígito do CPF ficam
    marcados como ambíguos. Textos como "NAO INFORMADO" e "consumidor" levantam ValorInvalido."""
    if _vazio(valor):
        return None
    texto = str(valor).strip()
    if "@" in texto:
        return Referencia("email", email(texto))
    try:
        documento = cpf(texto)
    except ValorInvalido:
        documento = None
    try:
        fone = telefone(texto)
    except ValorInvalido:
        fone = None
    if documento:
        mascara_cpf = bool(re.fullmatch(r"\d{3}\.\d{3}\.\d{3}-\d{2}", texto))
        return Referencia("cpf", documento, ambigua=fone is not None and not mascara_cpf)
    if fone:
        return Referencia("telefone", fone)
    raise ValorInvalido(f"Referência de cliente não identificável: {valor!r}")


# ---------- Produto ----------

# Dicionário fechado de cores: código do SKU canônico → nome. Os sinônimos vêm do próprio catálogo
# (a cor escrita na planilha ao lado do código canônico de cada linha).
CORES = {
    "AMA": "AMARELO",
    "AZM": "AZUL MARINHO",
    "BEG": "BEGE",
    "BRA": "BRANCO",
    "CIN": "CINZA MESCLA",
    "JCL": "JEANS CLARO",
    "JES": "JEANS ESCURO",
    "LIL": "LILÁS",
    "MRR": "MARROM",
    "OFF": "OFF WHITE",
    "OLI": "VERDE OLIVA",
    "PRE": "PRETO",
    "VIN": "VINHO",
}
# Letra da cor no código curto do CD (CAM016GP = CAM 016, G bege, P)
LETRA_COR = {"Y": "AMA", "A": "AZM", "G": "BEG", "B": "BRA", "C": "CIN", "J": "JCL", "E": "JES", "L": "LIL", "M": "MRR",
             "O": "OFF", "V": "OLI", "P": "PRE", "H": "VIN"}  # fmt: skip
SINONIMOS_COR = {
    "amarelo": "AMA", "yellow": "AMA", "amarelo manteiga": "AMA",
    "azul marinho": "AZM", "navy": "AZM", "az marinho": "AZM", "marinho": "AZM",
    "bege": "BEG", "beige": "BEG", "areia": "BEG",
    "branco": "BRA", "white": "BRA", "bco": "BRA",
    "cinza mescla": "CIN", "mescla": "CIN", "cinza": "CIN", "cz mescla": "CIN",
    "jeans claro": "JCL", "light denim": "JCL", "jns claro": "JCL",
    "jeans escuro": "JES", "dark denim": "JES", "jns escuro": "JES",
    "lilas": "LIL", "lavanda": "LIL",
    "marrom": "MRR", "brown": "MRR", "cafe": "MRR",
    "off white": "OFF", "off-white": "OFF", "offwhite": "OFF",
    "verde oliva": "OLI", "olive": "OLI", "oliva": "OLI", "vd oliva": "OLI",
    "preto": "PRE", "black": "PRE", "pto": "PRE",
    "vinho": "VIN", "burgundy": "VIN", "bordo": "VIN",
}  # fmt: skip

TAMANHOS = ("PP", "P", "M", "G", "GG", "U", "36", "38", "40", "42", "44", "46")
# Grafias de tamanho: único e a numeração internacional (S/L/XL = P/G/GG, a equivalência usual no Brasil)
SINONIMOS_TAMANHO = {"UN": "U", "UNICO": "U", "TAMUNICO": "U", "S": "P", "L": "G", "XL": "GG"}


def codigo_cor(valor) -> str | None:
    """Código de 3 letras da cor (BRA, BEG...) a partir do nome, de um sinônimo ou do próprio código."""
    if _vazio(valor):
        return None
    chave = _chave(valor)
    if chave.upper() in CORES:
        return chave.upper()
    if chave in SINONIMOS_COR:
        return SINONIMOS_COR[chave]
    raise ValorInvalido(f"Cor fora do dicionário: {valor!r}")


def cor(valor) -> str | None:
    """Nome da cor no dicionário fechado, maiúsculo (BRANCO, BEGE...)."""
    codigo = codigo_cor(valor)
    return CORES[codigo] if codigo else None


def tamanho(valor) -> str | None:
    """Maiúsculo, sem espaços: PP…GG, 36…46 ou U."""
    if _vazio(valor):
        return None
    texto = re.sub(r"\s", "", sem_acento(str(valor)).upper())
    texto = SINONIMOS_TAMANHO.get(texto, texto)
    if texto not in TAMANHOS:
        raise ValorInvalido(f"Tamanho desconhecido: {valor!r}")
    return texto


def tamanhos(valor) -> list[str]:
    """Uma linha do catálogo com vários tamanhos ("P/M/G/GG") vira a lista deles."""
    if _vazio(valor):
        return []
    return [tamanho(parte) for parte in str(valor).split("/")]


@dataclass(frozen=True)
class ChaveSku:
    categoria: str  # BER
    numero: str  # 004
    cor: str | None  # código da cor (JES); None se a grafia não traz a cor
    tamanho: str | None  # None quando a linha é de vários tamanhos

    @property
    def modelo(self) -> str:
        return f"{self.categoria}-{self.numero}"

    @property
    def canonico(self) -> str:
        if not self.cor or not self.tamanho:
            raise ValorInvalido(f"SKU {self.modelo} sem cor ou tamanho não tem forma canônica")
        return f"VLT-{self.categoria}-{self.numero}-{self.cor}-{self.tamanho}"


_TAM_SKU = "PP|GG|P|M|G|U|\\d{2}"
_SKU_CANONICO = re.compile(r"VLT-([A-Z]{3})-(\d{3})-([A-Z]{3})-([A-Z0-9]+)")
_SKU_CURTO = re.compile(rf"([A-Z]{{3}})(\d{{3}})([A-Z])({_TAM_SKU})")
_SKU_FISCAL = re.compile(r"VLT ([A-Z]{3}) (\d{3}) (.+)")


def interpretar_sku(valor) -> ChaveSku:
    """Lê qualquer grafia de SKU da Vulto: canônica (VLT-BER-004-JES-36, também minúscula), código
    curto do CD (CAM016GP, BER001B40) e a digitação do fiscal (vlt ber 001 branco 38; sem o tamanho
    quando a linha é de vários tamanhos)."""
    if _vazio(valor):
        raise ValorInvalido("SKU vazio")
    texto = alias_normalizado(sem_acento(str(valor)))
    if m := _SKU_CANONICO.fullmatch(texto):
        if m[3] not in CORES:
            raise ValorInvalido(f"Cor desconhecida no SKU: {valor!r}")
        return ChaveSku(m[1], m[2], m[3], tamanho(m[4]))
    if m := _SKU_CURTO.fullmatch(texto):
        if m[3] not in LETRA_COR:
            raise ValorInvalido(f"Letra de cor desconhecida no SKU: {valor!r}")
        return ChaveSku(m[1], m[2], LETRA_COR[m[3]], tamanho(m[4]))
    if m := _SKU_FISCAL.fullmatch(texto):
        partes = m[3].split(" ")
        tam = None
        if len(partes) > 1 and re.fullmatch(_TAM_SKU, partes[-1]):
            tam, partes = partes[-1], partes[:-1]
        return ChaveSku(m[1], m[2], codigo_cor(" ".join(partes)), tamanho(tam) if tam else None)
    raise ValorInvalido(f"SKU em formato desconhecido: {valor!r}")


# EANs que aparecem em várias peças diferentes (preenchimento de planilha, não código de verdade)
EANS_FICTICIOS = {"7890000000000"}


def digito_ean13(doze: str) -> int:
    soma = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(doze))
    return (10 - soma % 10) % 10


def ean(valor) -> str | None:
    """13 dígitos com dígito verificador correto (EAN-13). O fictício 7890000000000 é recusado."""
    if _vazio(valor):
        return None
    texto = str(valor).strip()
    if isinstance(valor, float):
        texto = str(int(valor)) if valor.is_integer() else texto
    if not re.fullmatch(r"\d{13}", texto):
        raise ValorInvalido(f"EAN não tem 13 dígitos: {valor!r}")
    if texto in EANS_FICTICIOS:
        raise ValorInvalido(f"EAN fictício: {valor!r}")
    if digito_ean13(texto[:12]) != int(texto[12]):
        raise ValorInvalido(f"EAN com dígito verificador errado: {valor!r}")
    return texto


# Categoria da plataforma pelo prefixo do SKU (o código é limpo; o texto da planilha tem ~60 grafias).
# Aprovado: só Calças e Bermudas e Shorts são novas; o resto usa as categorias da Casa Lorenzi.
CATEGORIA_POR_PREFIXO = {
    "BER": "Bermudas e Shorts",
    "CAL": "Calças",
    "CAM": "Malharia",  # camisetas
    "CMS": "Camisaria",
    "MOL": "Malharia",  # moletons
    "SAI": "Saias",
    "TOP": "Malharia",  # tops e croppeds
    "TRI": "Tricô",
    "VES": "Vestidos",
    "JAQ": "Outerwear",
    "ACE": "Acessórios",
}
CATEGORIA_NAO_CATALOGADO = "Não catalogado"
CATEGORIAS_NOVAS = ("Calças", "Bermudas e Shorts", CATEGORIA_NAO_CATALOGADO)

# Texto da coluna categoria → categoria da plataforma (último nível de "Bottoms > Short"); na ordem.
# Serve para conferir o texto contra o prefixo do SKU.
CATEGORIA_POR_TEXTO = (
    ("bermuda", "Bermudas e Shorts"),
    ("short", "Bermudas e Shorts"),
    ("calca", "Calças"),
    ("cropped", "Malharia"),
    ("top", "Malharia"),
    ("regata", "Malharia"),
    ("camiseta", "Malharia"),
    ("moletom", "Malharia"),
    ("moleton", "Malharia"),
    ("hoodie", "Malharia"),
    ("malharia", "Malharia"),
    ("camisa", "Camisaria"),
    ("overshirt", "Camisaria"),
    ("saia", "Saias"),
    ("vestido", "Vestidos"),
    ("trico", "Tricô"),
    ("jaqueta", "Outerwear"),
    ("outerwear", "Outerwear"),
    ("acessorio", "Acessórios"),
    ("bone", "Acessórios"),
    ("bolsa", "Acessórios"),
    ("pochete", "Acessórios"),
    ("cinto", "Acessórios"),
)


def categoria(valor) -> str | None:
    """Categoria da plataforma a partir do texto da planilha ("BERMUDA/SHORT", "Bottoms > Short",
    "camiseta básica", "Tops > Camisa"...). Vale o último nível; se ele não diz nada, o texto todo."""
    if _vazio(valor):
        return None
    for trecho in (_chave(str(valor).split(">")[-1]), _chave(valor)):
        for termo, nome in CATEGORIA_POR_TEXTO:
            if termo in trecho:
                return nome
    raise ValorInvalido(f"Categoria sem mapeamento: {valor!r}")


def categoria_do_sku(chave: ChaveSku) -> str:
    if chave.categoria not in CATEGORIA_POR_PREFIXO:
        raise ValorInvalido(f"Prefixo de SKU sem categoria: {chave.categoria}")
    return CATEGORIA_POR_PREFIXO[chave.categoria]


# ---------- Venda ----------

# Canal pela loja do legado, nunca pelo texto (14 grafias, e "APP" lançado na loja 5)
CANAL_POR_LOJA_LEGADO = {1: CANAL_LOJA, 2: CANAL_LOJA, 3: CANAL_LOJA, 4: CANAL_LOJA, 5: CANAL_SITE, 6: CANAL_APP}


def canal(loja_id_legado) -> str:
    try:
        return CANAL_POR_LOJA_LEGADO[int(loja_id_legado)]
    except (KeyError, TypeError, ValueError):
        raise ValorInvalido(f"Loja do legado sem canal: {loja_id_legado!r}") from None


# Status do legado → (status do pedido, status do pagamento). Pagamento None = sem pagamento.
# Parametrizável: é o mapeamento proposto no plano; o status vazio é decidido na migração das vendas.
STATUS_POR_TEXTO = {
    "pago": ("ENTREGUE", "APROVADO"),
    "aprovado": ("ENTREGUE", "APROVADO"),
    "aguardando": ("PROCESSANDO", "PENDENTE"),
    "cancelado": ("CANCELADO", None),
    "cancelada": ("CANCELADO", None),
    "estornado": ("CANCELADO", "ESTORNADO"),
    "chargeback": ("CANCELADO", "ESTORNADO"),
}


def status(valor) -> tuple[str, str | None] | None:
    if _vazio(valor):
        return None
    chave = _chave(valor)
    if chave not in STATUS_POR_TEXTO:
        raise ValorInvalido(f"Status desconhecido: {valor!r}")
    return STATUS_POR_TEXTO[chave]


# ---------- Genéricos ----------

_VERDADEIROS = {"1", "x", "s", "sim", "true", "verdadeiro", "y", "yes"}
_FALSOS = {"0", "n", "nao", "false", "falso", "no"}


def booleano(valor) -> bool | None:
    """true/false: "1", "x", "sim", "S" · "0", "N", "não". Vazio vira None (quem chama decide o padrão;
    no consentimento de mensagens, na dúvida, é falso)."""
    if _vazio(valor):
        return None
    if isinstance(valor, bool):
        return valor
    chave = _chave(valor)
    if chave in _VERDADEIROS:
        return True
    if chave in _FALSOS:
        return False
    raise ValorInvalido(f"Não é sim/não: {valor!r}")


def texto_livre(valor) -> str | None:
    """Trim; vazio vira None. Quebras de linha do meio ficam."""
    if _vazio(valor):
        return None
    return str(valor).replace("\r\n", "\n").strip()
