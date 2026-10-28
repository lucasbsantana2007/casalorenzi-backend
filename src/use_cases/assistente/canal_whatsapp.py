"""A Lúcia no WhatsApp (decisão 108): o n8n é o carteiro, o backend é quem responde e decide.

O n8n recebe a mensagem do cliente na Meta (WhatsApp Cloud API), chama POST /api/canais/whatsapp/mensagens com o
telefone, o texto e o id da mensagem, e manda de volta, pelo mesmo número, o texto que esta rota devolver. A
resposta sai do mesmo assistente do site (as mesmas ferramentas, o verificador e as duas falhas → pessoa); muda só
o formato: sem cards nem botões, tudo vira texto com os links das peças.

- Uma conversa por telefone, enquanto ela estiver ativa (24 h sem mensagem encerram, como no site). O telefone não
  fica salvo na conversa: ela é achada pelo HMAC do número (com o segredo do canal), guardado como chave_hash.
- Sem login: o WhatsApp não identifica a conta do site, então pedidos, pontos e dados da conta ficam no site.
- Ênfase na ajuda humana (decisão 114): a primeira mensagem recebe um menu com dois botões, "Respostas rápidas" (a
  Lúcia) ou "Falar com a equipe" (1 ou 2 também valem). Toda resposta da Lúcia traz o botão da equipe.
- Equipe (escolhida no menu, pedida a qualquer momento ou oferecida depois de duas falhas): abre o chamado na hora,
  canal WHATSAPP, com o resumo e o telefone. As mensagens seguintes entram no mesmo chamado, para a equipe ler no
  painel. Uma conversa abre no máximo um chamado.
- A mesma mensagem entregue duas vezes pela Meta (ela reenvia quando não recebe confirmação) não gera duas respostas.
"""

import hashlib
import hmac
import logging
import re
import time
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m
from src.config import settings
from src.entities import assistente as regra
from src.entities.atendimento import EM_ABERTO
from src.middlewares import limite
from src.repositories import assistente_repository, sessao
from src.use_cases import atendimentos
from src.use_cases.assistente import catalogo, conversas, regras_cliente
from src.utils.datas import agora
from src.utils.erros import Conflito, DadosInvalidos, Expirado, MuitasTentativas
from src.utils.texto import normalizar

log = logging.getLogger(__name__)

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
    limite_de_atividade = agora() - timedelta(hours=settings.WHATSAPP_CICLO_HORAS)
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
    # Ciclo novo: fecha o chamado em que a equipe ficou esperando o cliente (se a automação ainda não fechou)
    for atendimento in _parados(db, telefone):
        _encerrar(db, atendimento, avisar=False)
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


# ---------- Menu: respostas rápidas ou equipe (decisão 114) ----------

LUCIA, EQUIPE, MENU = "LUCIA", "EQUIPE", "MENU"
BOTAO_LUCIA = {"id": LUCIA, "title": "Respostas rápidas"}
BOTAO_EQUIPE = {"id": EQUIPE, "title": "Falar com a equipe"}
OPCOES_DO_MENU = (
    "1. Respostas rápidas comigo: peças, disponibilidade, lojas, horários e frete\n2. Falar com alguém da nossa equipe"
)
LEMBRETE_DO_MENU = "Para eu te ajudar, escolha uma opção: 1 para respostas rápidas comigo ou 2 para falar com a nossa equipe."
LUCIA_PRONTA = (
    "Perfeito! Pode me perguntar o que precisar. Se em qualquer momento quiser falar com uma pessoa, é só tocar em "
    "“Falar com a equipe” ou responder 2."
)


def cumprimento(momento=None) -> str:
    """Bom dia, boa tarde ou boa noite, pelo horário de São Paulo."""
    hora = (momento or agora()).astimezone(settings.FUSO).hour
    if 5 <= hora < 12:
        return "Bom dia"
    return "Boa tarde" if 12 <= hora < 18 else "Boa noite"


def texto_do_menu(nome: str | None, momento=None) -> str:
    """A primeira mensagem: o cumprimento do horário com o primeiro nome do perfil do WhatsApp, quem é a Lúcia
    e as duas opções."""
    primeiro = re.match(r"[^\W\d_]+", (nome or "").strip())
    saudacao = f"{cumprimento(momento)}, {primeiro.group(0)[:30]}!" if primeiro else f"{cumprimento(momento)}!"
    return (
        f"{saudacao} Aqui é a Lúcia, assistente virtual da Casa Lorenzi e da Vulto. Que bom ter você por aqui. "
        f"Como posso te ajudar hoje?\n\n{OPCOES_DO_MENU}"
    )


JA_COM_A_EQUIPE = (
    "Recebi! Sua mensagem foi para a nossa equipe, junto com a conversa (protocolo {protocolo}). Alguém responde por "
    "aqui. Se quiser respostas rápidas enquanto isso, toque em “Respostas rápidas”."
)
DICA_DA_EQUIPE = "Para falar com alguém da equipe, responda 2."
# Corpo de mensagem com botões: até 1.024 caracteres (acima disso, sai texto com a dica)
TAMANHO_COM_BOTOES = 1024
_ESCOLHE_LUCIA = {"1", "um", "respostas rapidas", "resposta rapida", "lucia"}
_ESCOLHE_EQUIPE = {"2", "dois", "equipe", "falar com a equipe", "atendente", "atendimento humano", "pessoa", "humano"}
_PEDE_MENU = {"menu", "opcoes", "inicio"}


def _escolha(texto: str, botao: str | None) -> str | None:
    """LUCIA, EQUIPE ou MENU quando o cliente escolheu (botão ou resposta curta); senão None (é uma pergunta)."""
    if botao in (LUCIA, EQUIPE, MENU):
        return botao
    curto = " ".join(re.findall(r"[a-z0-9]+", normalizar(texto)))
    if curto in _ESCOLHE_LUCIA:
        return LUCIA
    if curto in _ESCOLHE_EQUIPE:
        return EQUIPE
    if curto in _PEDE_MENU:
        return MENU
    return None


def mensagem_da_meta(telefone: str, texto: str, botoes: list[dict] | None = None) -> dict:
    """O corpo pronto para POST /{phone-number-id}/messages da WhatsApp Cloud API: com botões (interactive) quando
    cabem, senão texto (com a dica de como chamar a equipe, se era esse o botão)."""
    if botoes and len(texto) <= TAMANHO_COM_BOTOES:
        return {
            "messaging_product": "whatsapp",
            "to": telefone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": texto},
                "action": {"buttons": [{"type": "reply", "reply": dict(b)} for b in botoes]},
            },
        }
    if botoes and BOTAO_EQUIPE in botoes:
        texto = f"{texto}\n\n{DICA_DA_EQUIPE}"
    return {"messaging_product": "whatsapp", "to": telefone, "type": "text", "text": {"body": texto[:TAMANHO_MAXIMO]}}


def _saida(telefone: str, texto: str, botoes: list[dict] | None, conversa: m.ConversaAssistente | None, db: Session) -> dict:
    atendimento = db.get(m.Atendimento, conversa.atendimento_id) if conversa and conversa.atendimento_id else None
    return {
        "responder": True,
        "texto": texto,
        "mensagem": mensagem_da_meta(telefone, texto, botoes),
        "conversaId": conversa.id if conversa else None,
        "protocolo": atendimento.protocolo if atendimento else None,
    }


def _guardar(db: Session, conversa: m.ConversaAssistente, **valores) -> None:
    """Grava o estado do menu na memória da conversa (None apaga a chave)."""
    contexto = dict(conversa.contexto or {})
    for chave, valor in valores.items():
        if valor is None:
            contexto.pop(chave, None)
        else:
            contexto[chave] = valor
    conversa.contexto = contexto
    conversa.atualizada_em = agora()
    sessao.confirmar(db)


def _so_saudacao(texto: str) -> bool:
    return bool(regras_cliente.SAUDACAO.match(" ".join(re.findall(r"[a-z0-9]+", normalizar(texto)))))


def _para_a_equipe(db, conversa, telefone, nome, motivo) -> dict:
    aviso = _passar_para_a_equipe(db, conversa, telefone, nome, motivo)
    conversa = assistente_repository.obter(db, conversa.id, regra.CLIENTE)
    _guardar(db, conversa, whatsappModo=EQUIPE, perguntaPendente=None)
    return _saida(telefone, aviso, [BOTAO_LUCIA], conversa, db)


# ---------- Um lugar só para o atendimento humano (decisão 115) ----------
# O chamado do WhatsApp é o mesmo do painel: o cliente que vem do site com o protocolo cai no chamado que já existe;
# a resposta da equipe no painel volta para o WhatsApp do cliente (pelo n8n); e o ciclo fecha sozinho quando o
# cliente fica 4 horas sem responder depois da equipe.

PROTOCOLO = re.compile(r"\bATD-\d{6}\b")
# A Meta só aceita mensagem livre até 24 h depois da última mensagem do cliente; depois, só modelo aprovado
JANELA_DA_META = timedelta(hours=24)
ENCERRAMENTO = (
    "Como não tivemos mais notícias, encerramos este atendimento (protocolo {protocolo}). Obrigada pelo contato! "
    "Se precisar de algo, é só mandar uma mensagem por aqui."
)
NOTA_ENCERRADO = "Encerrado automaticamente: o cliente ficou {horas} horas sem responder depois da equipe."


def _vindo_do_site(db: Session, conversa: m.ConversaAssistente, telefone: str, texto: str, nome: str | None) -> dict | None:
    """Cliente que tocou em "Continuar no WhatsApp" no site: a mensagem traz o protocolo. Liga a conversa ao chamado
    que já existe (com o resumo do site), em vez de abrir outro. Protocolo de outro canal, encerrado ou inexistente:
    None (segue o menu)."""
    achado = PROTOCOLO.search(texto)
    if not achado:
        return None
    atendimento = db.scalar(select(m.Atendimento).where(m.Atendimento.protocolo == achado.group(0)))
    if atendimento is None or atendimento.canal != CANAL or atendimento.status == "CONCLUIDO":
        return None
    if not (atendimento.contato or "").startswith("+"):
        atendimento.contato = f"+{telefone}"
    if (nome or "").strip() and atendimento.contato_nome in (None, "Visitante do site"):
        atendimento.contato_nome = nome.strip()[:120]
    conversa.atendimento_id = atendimento.id
    conversa.status = regra.ENCAMINHADA
    sessao.confirmar(db)
    atendimentos.mensagem_do_whatsapp(db, atendimento, texto)
    _guardar(db, conversa, whatsappModo=EQUIPE, perguntaPendente=None)
    primeiro = re.match(r"[^\W\d_]+", (nome or "").strip())
    saudacao = f"{cumprimento()}, {primeiro.group(0)[:30]}!" if primeiro else f"{cumprimento()}!"
    texto_resposta = (
        f"{saudacao} Recebi o seu protocolo {atendimento.protocolo}. A nossa equipe já tem o resumo da sua conversa no "
        "site e continua com você por aqui."
    )
    return _saida(telefone, texto_resposta, [BOTAO_LUCIA], conversa, db)


def _telefone_do_chamado(atendimento: m.Atendimento) -> str | None:
    digitos = "".join(c for c in (atendimento.contato or "") if c.isdigit())
    return digitos if (atendimento.contato or "").startswith("+") and 10 <= len(digitos) <= 15 else None


def _ultima_do_cliente(atendimento: m.Atendimento):
    return max((msg.enviado_em for msg in atendimento.mensagens if msg.autor_tipo == "CLIENTE"), default=None)


def _entregar(mensagem: dict) -> bool:
    """Entrega pelo n8n (decisão 108): POST no webhook de envio, com o segredo do canal. Sem webhook: False."""
    if not settings.N8N_ENVIO_URL:
        return False
    try:
        resposta = httpx.post(
            settings.N8N_ENVIO_URL,
            json={"mensagem": mensagem},
            headers={"X-Canal-Segredo": settings.CANAL_WHATSAPP_SEGREDO},
            timeout=10,
        )
        return resposta.status_code < 300
    except httpx.HTTPError:
        log.warning("Falha ao entregar mensagem da equipe pelo n8n", exc_info=True)
        return False


def entregar_resposta_da_equipe(db: Session, atendimento: m.Atendimento, conteudo: str) -> bool | None:
    """Resposta da equipe no painel, num chamado do WhatsApp: vai para o WhatsApp do cliente. None quando não se
    aplica (outro canal ou sem telefone); False quando não deu para entregar (fica registrado no chamado)."""
    telefone = _telefone_do_chamado(atendimento) if atendimento.canal == CANAL else None
    if telefone is None:
        return None
    ultima = _ultima_do_cliente(atendimento)
    if ultima is None or agora() - ultima > JANELA_DA_META:
        atendimentos.registrar_evento(
            db,
            atendimento,
            "Resposta não enviada pelo WhatsApp: passaram mais de 24 h desde a última mensagem do cliente (regra da "
            "Meta). Fale com o cliente pelo telefone do chamado.",
        )
        sessao.confirmar(db)
        return False
    # A resposta da equipe renova o ciclo da conversa: o cliente tem 4 h a partir dela
    for conversa in db.scalars(select(m.ConversaAssistente).where(m.ConversaAssistente.atendimento_id == atendimento.id)):
        conversa.atualizada_em = agora()
    sessao.confirmar(db)
    texto = f"{conteudo.strip()}\n\nEquipe Casa Lorenzi e Vulto · protocolo {atendimento.protocolo}"
    entregue = _entregar(mensagem_da_meta(telefone, texto[:TAMANHO_MAXIMO], [BOTAO_LUCIA]))
    if not entregue:
        atendimentos.registrar_evento(
            db, atendimento, "Não consegui entregar esta resposta no WhatsApp do cliente. Tente de novo em instantes."
        )
        sessao.confirmar(db)
    return entregue


def _parados(db: Session, telefone: str | None = None) -> list[m.Atendimento]:
    """Chamados do WhatsApp em aberto cuja última mensagem é da equipe e tem mais de WHATSAPP_CICLO_HORAS horas.
    Se a última é do cliente, quem deve resposta é a equipe: não fecha."""
    consulta = select(m.Atendimento).where(m.Atendimento.canal == CANAL, m.Atendimento.status.in_(EM_ABERTO))
    if telefone:
        consulta = consulta.where(m.Atendimento.contato == f"+{telefone}")
    limite_de_espera = agora() - timedelta(hours=settings.WHATSAPP_CICLO_HORAS)
    parados = []
    for atendimento in db.scalars(consulta):
        conversa_real = [msg for msg in atendimento.mensagens if msg.autor_tipo in ("CLIENTE", "ATENDENTE")]
        if conversa_real and conversa_real[-1].autor_tipo == "ATENDENTE" and conversa_real[-1].enviado_em <= limite_de_espera:
            parados.append(atendimento)
    return parados


def _encerrar(db: Session, atendimento: m.Atendimento, avisar: bool) -> None:
    atendimento.status = "CONCLUIDO"
    atendimento.atualizado_em = agora()
    atendimentos.registrar_evento(db, atendimento, NOTA_ENCERRADO.format(horas=settings.WHATSAPP_CICLO_HORAS))
    sessao.confirmar(db)
    telefone = _telefone_do_chamado(atendimento)
    ultima = _ultima_do_cliente(atendimento)
    if avisar and telefone and ultima is not None and agora() - ultima <= JANELA_DA_META:
        _entregar(mensagem_da_meta(telefone, ENCERRAMENTO.format(protocolo=atendimento.protocolo)))


def encerrar_ciclos(db: Session) -> int:
    """Automação encerrar_whatsapp: fecha os chamados do WhatsApp em que o cliente ficou 4 horas sem responder depois
    da equipe, e avisa o cliente (dentro da janela de 24 h da Meta). Devolve quantos fechou."""
    parados = _parados(db)
    for atendimento in parados:
        _encerrar(db, atendimento, avisar=True)
    return len(parados)


# ---------- Mensagem recebida ----------


def responder(
    db: Session, *, telefone: str, texto: str | None, id_mensagem: str | None, nome: str | None, botao: str | None = None
) -> dict:
    """{"responder", "texto", "mensagem", "conversaId", "protocolo"}. "mensagem" é o corpo pronto para a Meta (com os
    botões); responder=False: a mesma mensagem já foi tratada (a Meta entregou de novo) e o n8n não manda nada.

    Na primeira mensagem, o cliente escolhe: respostas rápidas (a Lúcia) ou a equipe. Se a primeira mensagem já era
    uma pergunta, ela é respondida assim que ele escolher a Lúcia. Com a equipe, o chamado abre na hora e as mensagens
    seguintes entram nele. Toda resposta da Lúcia traz o botão da equipe."""
    texto = (texto or "").strip()
    if not texto and not botao:
        return {
            "responder": True,
            "texto": SO_TEXTO,
            "mensagem": mensagem_da_meta(telefone, SO_TEXTO),
            "conversaId": None,
            "protocolo": None,
        }
    try:
        limite.conferir(
            f"whatsapp:{_chave(telefone)[:16]}", maximo=regra.LIMITE_POR_CONVERSA[regra.CLIENTE][0], janela_segundos=600
        )
    except MuitasTentativas:
        return {
            "responder": True,
            "texto": LIMITE_DE_MENSAGENS,
            "mensagem": mensagem_da_meta(telefone, LIMITE_DE_MENSAGENS),
            "conversaId": None,
            "protocolo": None,
        }

    id_cliente = _id_da_mensagem(id_mensagem)
    conversa = _conversa_do_telefone(db, telefone)
    memoria = conversa.contexto or {}
    if id_cliente and (
        memoria.get("whatsappUltimoId") == id_cliente or assistente_repository.por_id_cliente(db, conversa.id, id_cliente)
    ):
        return {"responder": False, "texto": "", "mensagem": None, "conversaId": conversa.id, "protocolo": None}
    modo = memoria.get("whatsappModo")
    escolha = _escolha(texto, botao)
    if id_cliente:
        _guardar(db, conversa, whatsappUltimoId=id_cliente)

    if escolha == MENU:
        _guardar(db, conversa, whatsappModo=MENU)
        return _saida(telefone, texto_do_menu(nome), [BOTAO_LUCIA, BOTAO_EQUIPE], conversa, db)

    if modo is None and (vindo := _vindo_do_site(db, conversa, telefone, texto, nome)) is not None:
        return vindo
    if modo in (None, MENU):
        if escolha == EQUIPE:
            motivo = memoria.get("perguntaPendente") or "O cliente escolheu falar com a equipe no menu do WhatsApp."
            return _para_a_equipe(db, conversa, telefone, nome, motivo)
        if escolha == LUCIA:
            pendente = memoria.get("perguntaPendente")
            _guardar(db, conversa, whatsappModo=LUCIA, perguntaPendente=None)
            if not pendente:
                return _saida(telefone, LUCIA_PRONTA, [BOTAO_EQUIPE], conversa, db)
            texto = pendente  # a pergunta que chegou antes da escolha
        else:
            # Primeira mensagem (ou resposta que não é uma opção): o menu, guardando a pergunta para depois
            pergunta = None if _so_saudacao(texto) else texto[:800]
            _guardar(db, conversa, whatsappModo=MENU, perguntaPendente=pergunta or memoria.get("perguntaPendente"))
            corpo = texto_do_menu(nome) if modo is None else LEMBRETE_DO_MENU
            return _saida(telefone, corpo, [BOTAO_LUCIA, BOTAO_EQUIPE], conversa, db)

    elif modo == EQUIPE:
        if escolha == LUCIA:
            _guardar(db, conversa, whatsappModo=LUCIA)
            return _saida(telefone, LUCIA_PRONTA, [BOTAO_EQUIPE], conversa, db)
        atendimento = db.get(m.Atendimento, conversa.atendimento_id) if conversa.atendimento_id else None
        if atendimento is None or atendimento.status == "CONCLUIDO":
            # O chamado foi encerrado: começa de novo, com o menu
            _guardar(db, conversa, whatsappModo=MENU, perguntaPendente=None if _so_saudacao(texto) else texto[:800])
            return _saida(telefone, texto_do_menu(nome), [BOTAO_LUCIA, BOTAO_EQUIPE], conversa, db)
        if escolha != EQUIPE:
            atendimentos.mensagem_do_whatsapp(db, atendimento, texto)
        return _saida(telefone, JA_COM_A_EQUIPE.format(protocolo=atendimento.protocolo), [BOTAO_LUCIA], conversa, db)

    elif escolha == EQUIPE:  # modo LUCIA: botão ou "2" chama a equipe a qualquer momento
        return _para_a_equipe(db, conversa, telefone, nome, "O cliente pediu para falar com a equipe no WhatsApp.")
    elif escolha == LUCIA:
        return _saida(telefone, LUCIA_PRONTA, [BOTAO_EQUIPE], conversa, db)

    return _resposta_da_lucia(db, telefone, texto, id_cliente, nome)


def _resposta_da_lucia(db: Session, telefone: str, texto: str, id_cliente: str | None, nome: str | None) -> dict:
    for tentativa in range(TENTATIVAS):
        conversa = _conversa_do_telefone(db, telefone)
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
            return _saida(telefone, LONGA_DEMAIS, [BOTAO_EQUIPE], conversa, db)
    else:
        raise Conflito("A conversa não ficou livre a tempo.")

    blocos = resposta.blocos or []
    oferta = next((b for b in blocos if b.get("tipo") == "acao_atendimento"), None)
    if oferta is not None:
        conversa = assistente_repository.obter(db, conversa.id, regra.CLIENTE)
        saida = _para_a_equipe(db, conversa, telefone, nome, oferta.get("motivo") or texto)
        # A oferta ("Posso passar você...", "Toque em...") já foi aceita: no lugar dela, o que foi feito
        corpo = _OFERTA_DA_EQUIPE.sub("", resposta.conteudo or "").strip()
        if corpo:
            saida["texto"] = texto_para_whatsapp(
                f"{corpo}\n\n{saida['texto']}", [b for b in blocos if b.get("tipo") != "acao_atendimento"]
            )
            saida["mensagem"] = mensagem_da_meta(telefone, saida["texto"], [BOTAO_LUCIA])
        return saida
    conversa = assistente_repository.obter(db, conversa.id, regra.CLIENTE)
    return _saida(telefone, texto_para_whatsapp(resposta.conteudo or "", blocos), [BOTAO_EQUIPE], conversa, db)
