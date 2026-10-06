"""Validação dos anexos de mensagens do atendimento (regras em src/entities/anexo.py)."""

import base64
import binascii
import math

from src import models as m
from src.entities.anexo import NOME_MAXIMO, TAMANHO_MAXIMO_ANEXO, TIPOS_ANEXO, tamanho_permitido, tipo_pelo_conteudo
from src.utils.erros import DadosInvalidos

# Tamanho máximo do texto em base64 que ainda cabe em 2 MB decodificados
_BASE64_MAXIMO = 4 * math.ceil(TAMANHO_MAXIMO_ANEXO / 3)


def _nome_seguro(nome: str | None) -> str:
    """Só o nome do arquivo (sem pastas), limitado a 255 caracteres."""
    nome = (nome or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return nome[:NOME_MAXIMO] or "anexo"


def preparar(nome: str | None, tipo: str | None, conteudo_base64: str | None) -> m.Anexo:
    """Confere tipo, tamanho e conteúdo e devolve o anexo pronto para ligar a uma mensagem (sem gravar)."""
    tipo = (tipo or "").strip().lower()
    if tipo not in TIPOS_ANEXO:
        raise DadosInvalidos("O anexo deve ser uma imagem JPG, PNG ou WEBP.")

    texto = (conteudo_base64 or "").strip()
    if texto.startswith("data:"):  # aceita o resultado de FileReader.readAsDataURL
        texto = texto.partition(",")[2]
    texto = "".join(texto.split())
    if len(texto) > _BASE64_MAXIMO:  # recusa antes de decodificar um arquivo grande demais
        raise DadosInvalidos("O anexo deve ter no máximo 2 MB.")
    try:
        dados = base64.b64decode(texto, validate=True)
    except (binascii.Error, ValueError):
        raise DadosInvalidos("Não foi possível ler o anexo. Envie o arquivo em base64.") from None

    if not dados:
        raise DadosInvalidos("O anexo está vazio.")
    if not tamanho_permitido(len(dados)):
        raise DadosInvalidos("O anexo deve ter no máximo 2 MB.")
    if tipo_pelo_conteudo(dados) != tipo:
        raise DadosInvalidos("O conteúdo do anexo não corresponde ao tipo informado.")
    return m.Anexo(nome=_nome_seguro(nome), tipo=tipo, tamanho=len(dados), dados=dados)
