"""A Lúcia no WhatsApp (decisão 108): o n8n é o carteiro, o backend é quem responde e decide.

O n8n recebe a mensagem do cliente na Meta (WhatsApp Cloud API), chama POST /api/canais/whatsapp/mensagens com o
telefone, o texto e o id da mensagem, e manda de volta, pelo mesmo número, o texto que esta rota devolver. A
resposta sai do mesmo assistente do site (as mesmas ferramentas, o verificador e as duas falhas → pessoa); muda só
o formato: sem cards nem botões, tudo vira texto com os links das peças.

- Uma conversa por telefone, enquanto ela estiver ativa (24 h sem mensagem encerram, como no site). O telefone não
  fica salvo na conversa: ela é achada pelo HMAC do número (com o segredo do canal), guardado como chave_hash.
- Sem login: o WhatsApp não identifica a conta do site, então pedidos, pontos e dados da conta ficam no site.
- Pedido de pessoa (ou a Lúcia oferecendo a equipe): abre o chamado na hora, canal WHATSAPP, com o resumo e o
  telefone para a equipe responder. Uma conversa abre no máximo um chamado.
- A mesma mensagem entregue duas vezes pela Meta (ela reenvia quando não recebe confirmação) não gera duas respostas.
"""

import hashlib
import hmac
import re
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m
from src.config import settings
from src.entities import assistente as regra
from src.middlewares import limite
from src.repositories import assistente_repository, sessao
from src.use_cases import atendimentos
from src.use_cases.assistente import catalogo, conversas
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos, Expirado, MuitasTentativas

CANAL = "WHATSAPP"
# WhatsApp aceita até 4.096 caracteres por mensagem
TAMANHO_MAXIMO = 4000
MAXIMO_DE_PECAS = 5
# Mensagens em rajada ("oi" / "tudo bem?" / "tem camisa azul?"): a segunda espera a primeira ser respondida
ESPERA_ENTRE_TENTATIVAS = 0.5
TENTATIVAS = 40
LIMITE_DE_MENSAGENS = "Recebi muitas mensagens seguidas. Me dá uns minutinhos e escreve de novo, por favor."
LONGA_DEMAIS = "Sua mensagem ficou longa demais para mim. Pode resumir em poucas linhas?"
SO_TEXTO = "Por enquanto eu só consigo ler mensagens de texto. Pode escrever o que você precisa?"
# Frases da oferta de atendimento do site (texto de solicitar_atendimento_humano e do modelo)
_OFERTA_DA_EQUIPE = re.compile(r"[^.!?]*\b(Posso (passar|abrir|chamar)|[Tt]oque|ligue para uma das lojas)\b[^.!?]*[.!?]\s*")


def telefone_valido(telefone: str) -> str | None:
    """Só os dígitos, com DDI (5511999999999). Fora de 10 a 15 dígitos: inválido."""
    digitos = "".join(c for c in telefone or "" if c.isdigit())
    return digitos if 10 <= len(digitos) <= 15 else None


def _chave(telefone: str) -> str:
    return hmac.new(settings.CANAL_WHATSAPP_SEGREDO.encode(), telefone.encode(), hashlib.sha256).hexdigest()


def _conversa_do_telefone(db: Session, telefone: str) -> m.ConversaAssistente:
    """A conversa ativa deste número; se não houver (primeira mensagem ou a anterior venceu), uma nova."""
    chave_hash = conversas._hash(_chave(telefone))
    limite_de_atividade = agora() - timedelta(hours=settings.IA_CONVERSA_EXPIRA_HORAS)
    conversa = db.scalar(
        select(m.ConversaAssistente)
        .where(
            m.ConversaAssistente.tipo == regra.CLIENTE,
            m.ConversaAssistente.chave_hash == chave_hash,
            m.ConversaAssistente.status != regra.ENCERRADA,
            m.ConversaAssistente.atualizada_em >= limite_de_atividade,
        )
        .order_by(m.ConversaAssistente.atualizada_em.desc())
        .limit(1)
    )
    if conversa is not None:
        return conversa
    conversa = conversas._nova(db, tipo=regra.CLIENTE, marca=settings.CANAL_WHATSAPP_MARCA, chave_hash=chave_hash)
    sessao.confirmar(db)
    return conversa


def _id_da_mensagem(id_mensagem: str | None) -> str | None:
    """O id da Meta (wamid...) é longo: guarda o resumo dele, para reconhecer a mesma mensagem entregue de novo."""
    if not id_mensagem:
        return None
    return "wa:" + hashlib.sha256(id_mensagem.encode()).hexdigest()[:40]


# ---------- Texto para o WhatsApp ----------


def _link(caminho: str | None) -> str | None:
    if not caminho:
        return None
    return caminho if caminho.startswith("http") else f"{settings.URL_FRONTEND}{caminho}"


def _markdown_do_whatsapp(texto: str) -> str:
    """O site usa **negrito** e [rótulo](link); o WhatsApp, *negrito* e o link escrito."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m_: f"{m_.group(1)}: {_link(m_.group(2))}", texto)


def _pecas(bloco: dict) -> list[str]:
    linhas = []
    for item in bloco.get("itens", [])[:MAXIMO_DE_PECAS]:
        partes = [f"• *{item.get('nome')}*", item.get("precoFormatado")]
        if item.get("situacao") == catalogo.ESGOTADO:
            partes.append("indisponível no site")
        linha = " – ".join(p for p in partes if p)
        if link := _link(item.get("link")):
            linha += f"\n  {link}"
        linhas.append(linha)
    return linhas


def _disponibilidade(bloco: dict) -> list[str]:
    rotulo = catalogo.ROTULO_SITUACAO
    linhas = [f"No site: {rotulo.get(bloco.get('site'), bloco.get('site'))}"]
    for loja in bloco.get("lojas", []):
        linhas.append(f"{loja.get('loja')}: {rotulo.get(loja.get('situacao'), loja.get('situacao'))}")
    return linhas


def _lojas(bloco: dict) -> list[str]:
    linhas = []
    for loja in bloco.get("itens", [])[:6]:
        partes = [f"*{loja.get('nome')}*", loja.get("endereco") or loja.get("cidade")]
        if hoje := loja.get("horarioDeHoje"):
            partes.append(f"hoje: {hoje}")
        if telefone := loja.get("telefone"):
            partes.append(f"tel. {telefone}")
        linhas.append(" – ".join(p for p in partes if p))
    return linhas


def _sacola(bloco: dict) -> list[str]:
    item = bloco.get("item") or {}
    produto = {"id": item.get("produtoId"), "marca": item.get("marca")}
    if produto["id"] is None:
        return []
    caminho = f"/vulto/produto/{produto['id']}" if produto["marca"] == "VULTO" else f"/produto/{produto['id']}"
    escolha = ", ".join(x for x in (item.get("cor"), item.get("tamanho") and f"tamanho {item['tamanho']}") if x)
    return [f"Para comprar ({escolha}), é só abrir: {_link(caminho)}"]


def texto_para_whatsapp(texto: str, blocos: list[dict]) -> str:
    """A resposta do assistente em texto: o que o modelo escreveu e, depois, o essencial de cada card."""
    partes = [_markdown_do_whatsapp((texto or "").strip())]
    for bloco in blocos or []:
        tipo = bloco.get("tipo")
        linhas = {
            "produtos": _pecas,
            "disponibilidade": _disponibilidade,
            "lojas": _lojas,
            "acao_sacola": _sacola,
        }.get(tipo, lambda _: [])(bloco)
        if tipo == "link" and (link := _link(bloco.get("destino"))):
            linhas = [f"{bloco.get('rotulo') or 'Link'}: {link}"]
        if linhas:
            partes.append("\n".join(linhas))
    texto_final = "\n\n".join(p for p in partes if p)
    if len(texto_final) > TAMANHO_MAXIMO:
        texto_final = texto_final[: TAMANHO_MAXIMO - 1].rsplit("\n", 1)[0] + "\n…"
    return texto_final


# ---------- Atendimento humano ----------


def _passar_para_a_equipe(db: Session, conversa: m.ConversaAssistente, telefone: str, nome: str | None, motivo: str) -> str:
    """Abre o chamado (canal WHATSAPP) com o resumo e o telefone. Se a conversa já tem chamado, só lembra o protocolo."""
    assistente_repository.travar(db, conversa.id)
    if conversa.atendimento_id and (existente := db.get(m.Atendimento, conversa.atendimento_id)) is not None:
        return (
            f"A sua conversa já está com a nossa equipe (protocolo {existente.protocolo}). "
            "Alguém vai continuar com você por aqui, pelo WhatsApp."
        )
    resumo = conversas._resumo_para_atendimento(db, conversa, motivo, CANAL)
    resumo = resumo.replace(
        "O cliente seguiu pelo WhatsApp com este protocolo.", f"O cliente falou com a Lúcia pelo WhatsApp: +{telefone}."
    )
    atendimento = atendimentos.abrir_pelo_whatsapp(
        db, None, marca=conversa.marca, tipo_solicitacao_id=conversas._tipo_para_atendimento(db).id, descricao=resumo
    )
    atendimento.contato = f"+{telefone}"
    atendimento.contato_nome = (nome or "").strip()[:120] or "Cliente do WhatsApp"
    conversa.atendimento_id = atendimento.id
    conversa.status = regra.ENCAMINHADA
    conversa.atualizada_em = agora()
    sessao.confirmar(db)
    return (
        f"Pronto! Passei a sua conversa para a nossa equipe, com o resumo do que falamos (protocolo {atendimento.protocolo}). "
        "Alguém vai continuar com você por aqui, pelo WhatsApp."
    )


# ---------- Mensagem recebida ----------


def responder(db: Session, *, telefone: str, texto: str | None, id_mensagem: str | None, nome: str | None) -> dict:
    """{"responder": bool, "texto": str, "conversaId": str | None, "protocolo": str | None}. responder=False: a
    mesma mensagem já foi respondida (a Meta entregou de novo) e o n8n não deve mandar nada."""
    texto = (texto or "").strip()
    if not texto:
        return {"responder": True, "texto": SO_TEXTO, "conversaId": None, "protocolo": None}
    try:
        limite.conferir(
            f"whatsapp:{_chave(telefone)[:16]}", maximo=regra.LIMITE_POR_CONVERSA[regra.CLIENTE][0], janela_segundos=600
        )
    except MuitasTentativas:
        return {"responder": True, "texto": LIMITE_DE_MENSAGENS, "conversaId": None, "protocolo": None}

    id_cliente = _id_da_mensagem(id_mensagem)
    for tentativa in range(TENTATIVAS):
        conversa = _conversa_do_telefone(db, telefone)
        if id_cliente and assistente_repository.por_id_cliente(db, conversa.id, id_cliente) is not None:
            return {"responder": False, "texto": "", "conversaId": conversa.id, "protocolo": None}
        try:
            _, resposta = conversas.enviar(db, conversa, texto, id_cliente=id_cliente, canal=CANAL)
            break
        except Conflito:  # a mensagem anterior deste número ainda está sendo respondida
            db.rollback()
            if tentativa == TENTATIVAS - 1:
                raise
            time.sleep(ESPERA_ENTRE_TENTATIVAS)
        except Expirado:  # venceu entre a busca e o envio: a próxima volta abre outra
            db.rollback()
        except DadosInvalidos:
            db.rollback()
            return {"responder": True, "texto": LONGA_DEMAIS, "conversaId": conversa.id, "protocolo": None}
    else:
        raise Conflito("A conversa não ficou livre a tempo.")

    blocos = resposta.blocos or []
    oferta = next((b for b in blocos if b.get("tipo") == "acao_atendimento"), None)
    if oferta is not None:
        conversa = assistente_repository.obter(db, conversa.id, regra.CLIENTE)
        aviso = _passar_para_a_equipe(db, conversa, telefone, nome, oferta.get("motivo") or texto)
        blocos = [b for b in blocos if b.get("tipo") != "acao_atendimento"]
        # A oferta ("Posso passar você...", "Toque em...") já foi aceita: no lugar dela, o que foi feito
        corpo = _OFERTA_DA_EQUIPE.sub("", resposta.conteudo or "").strip()
        resposta_texto = f"{corpo}\n\n{aviso}" if corpo else aviso
    else:
        resposta_texto = resposta.conteudo or ""
    conversa = assistente_repository.obter(db, conversa.id, regra.CLIENTE)
    atendimento = db.get(m.Atendimento, conversa.atendimento_id) if conversa and conversa.atendimento_id else None
    return {
        "responder": True,
        "texto": texto_para_whatsapp(resposta_texto, blocos),
        "conversaId": conversa.id if conversa else None,
        "protocolo": atendimento.protocolo if atendimento else None,
    }
