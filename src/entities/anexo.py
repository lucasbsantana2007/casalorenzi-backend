"""Anexo de mensagem do atendimento: só imagens (foto do defeito, da etiqueta etc.), até 2 MB.

O tipo declarado precisa bater com o conteúdo real do arquivo (assinatura dos primeiros
bytes), para ninguém enviar outro tipo de arquivo com o nome de uma imagem."""

TIPOS_ANEXO = ("image/jpeg", "image/png", "image/webp")
TAMANHO_MAXIMO_ANEXO = 2 * 1024 * 1024  # bytes, depois de decodificar o base64
NOME_MAXIMO = 255


def tipo_pelo_conteudo(dados: bytes) -> str | None:
    """Tipo real da imagem pelos primeiros bytes (assinatura do formato), ou None."""
    if dados.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(dados) >= 12 and dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    return None


def tamanho_permitido(tamanho: int) -> bool:
    return 0 < tamanho <= TAMANHO_MAXIMO_ANEXO
