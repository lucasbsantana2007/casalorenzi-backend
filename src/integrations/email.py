"""Envio de e-mails pelo Resend (https://resend.com), pela API HTTP deles.

- Com RESEND_API_KEY no .env, o e-mail sai de verdade; sem ela (ambiente local, testes), o
  conteúdo vai para o log da API, como antes.
- O envio roda em segundo plano: a resposta da API não espera o Resend, e uma falha dele não
  derruba a operação (fica registrada no log). Por isso, chame `enviar` só depois de gravar
  no banco: o link do e-mail precisa já existir.

Teste a configuração com:  python -m src.integrations.email seu@email.com
"""

import logging
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx
import truststore

from src.config.settings import EMAIL_REMETENTE, RESEND_API_KEY

log = logging.getLogger("casalorenzi")

URL_RESEND = "https://api.resend.com/emails"
TEMPO_LIMITE = 10  # segundos
# Certificados do sistema (Windows/Linux) em vez da lista do Python: funciona também com antivírus
# que inspecionam HTTPS (ex.: Avast), cujo certificado só está cadastrado no sistema.
_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

_fila = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email")


@dataclass(frozen=True)
class Email:
    para: str
    assunto: str
    texto: str
    html: str


def enviar(email: Email) -> None:
    """Agenda o envio e volta na hora."""
    if not RESEND_API_KEY:
        log.info("E-mail (sem RESEND_API_KEY, não enviado) para %s · %s\n%s", email.para, email.assunto, email.texto)
        return
    _fila.submit(_enviar_com_log, email)


def _enviar_com_log(email: Email) -> None:
    try:
        enviar_agora(email)
        log.info("E-mail enviado para %s · %s", email.para, email.assunto)
    except Exception:
        log.exception("Falha ao enviar e-mail para %s · %s", email.para, email.assunto)


def enviar_agora(email: Email, cliente_http: httpx.Client | None = None) -> str:
    """Envia e espera a resposta do Resend. Devolve o id do e-mail; erro do Resend levanta exceção."""
    corpo = {"from": EMAIL_REMETENTE, "to": [email.para], "subject": email.assunto, "text": email.texto, "html": email.html}
    cabecalhos = {"Authorization": f"Bearer {RESEND_API_KEY}"}
    http = cliente_http or httpx.Client(timeout=TEMPO_LIMITE, verify=_SSL)
    try:
        resposta = http.post(URL_RESEND, json=corpo, headers=cabecalhos)
    finally:
        if cliente_http is None:
            http.close()
    if resposta.status_code >= 400:
        raise RuntimeError(f"Resend respondeu {resposta.status_code}: {resposta.text}")
    return resposta.json().get("id", "")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python -m src.integrations.email seu@email.com")
    if not RESEND_API_KEY:
        sys.exit("Defina RESEND_API_KEY no .env antes de testar.")
    teste = Email(
        para=sys.argv[1],
        assunto="Casa Lorenzi · teste de envio",
        texto="Se você recebeu esta mensagem, o envio de e-mails da API está funcionando.",
        html="<p>Se você recebeu esta mensagem, o envio de e-mails da API está funcionando.</p>",
    )
    print(f"Enviado pelo Resend (id {enviar_agora(teste)}) a partir de {EMAIL_REMETENTE}.")
