"""Conversas com os assistentes: abrir, conferir o dono, enviar mensagem, eventos da sacola, encaminhar
para o atendimento humano, encerrar, apagar as vencidas (retenção) e medir o uso.

Dono da conversa (isolamento entre clientes):
- site sem login: só quem tem a chave da conversa (devolvida uma vez na abertura; no banco, só o hash);
- site com login de cliente: a conversa passa a ser da conta e só esse cliente a abre (outro cliente,
  ou o mesmo navegador sem login, recebe 404, como se ela não existisse);
- copiloto: só o membro da equipe que a abriu.
Uma mensagem por vez em cada conversa (a segunda, durante a resposta, recebe 409), e o reenvio da mesma
mensagem (mesmo idCliente) devolve a resposta já dada, sem chamar o modelo de novo.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src import models as m
from src.config import settings
from src.entities import assistente as regra
from src.entities.papeis import ACESSO, pode_acessar
from src.repositories import assistente_repository, cadastro_repository, sessao
from src.use_cases import analises, atendimentos
from src.use_cases.assistente import (
    catalogo,
    ferramentas_cliente,
    ferramentas_gerenciais,
    prompts,
    regras_cliente,
    regras_gerenciais,
)
from src.use_cases.assistente.ferramentas import ROTULO_MODULO, ROTULO_PAPEL, Contexto
from src.use_cases.assistente.formatacao import cru, data
from src.use_cases.assistente.orquestrador import Assistente, responder
from src.utils.datas import agora, ms
from src.utils.erros import DadosInvalidos, Expirado, NaoAutenticado, NaoEncontrado

ASSISTENTE_CLIENTE = Assistente(
    tipo=regra.CLIENTE,
    ferramentas=ferramentas_cliente.FERRAMENTAS,
    prompt_fixo=prompts.PROMPT_CLIENTE,
    direta=regras_cliente.direta,
    regras=regras_cliente.responder,
)
ASSISTENTE_GERENCIAL = Assistente(
    tipo=regra.GERENCIAL,
    ferramentas=ferramentas_gerenciais.FERRAMENTAS,
    prompt_fixo=prompts.PROMPT_GERENCIAL,
    direta=regras_gerenciais.direta,
    regras=regras_gerenciais.responder,
)

# Chaves da memória da conversa (o resto é descartado) e o tamanho máximo das listas
CHAVES_MEMORIA = {
    "busca",
    "buscaDescricao",
    "produtosMostrados",
    "produtoEmFoco",
    "corEmFoco",
    "tamanhoEmFoco",
    "lojaEmFoco",
    "lojaEmFocoNome",
    "oferta",
    "eventos",
}


def _hash(chave: str) -> str:
    return hashlib.sha256(chave.encode()).hexdigest()


def _validade(momento: datetime) -> datetime:
    return momento + timedelta(days=settings.IA_RETENCAO_DIAS)


def _limpar_memoria(memoria: dict) -> dict:
    limpa = {k: v for k, v in memoria.items() if k in CHAVES_MEMORIA and v is not None}
    if "produtosMostrados" in limpa:
        limpa["produtosMostrados"] = limpa["produtosMostrados"][:6]
    if "eventos" in limpa:
        limpa["eventos"] = limpa["eventos"][-5:]
    return cru(limpa)


# ---------- Saída ----------


def mensagem_saida(mensagem: m.MensagemAssistente) -> dict:
    return {
        "id": mensagem.id,
        "papel": mensagem.papel,
        "texto": mensagem.conteudo,
        "blocos": mensagem.blocos or [],
        "modo": mensagem.modo,
        "criadaEm": ms(mensagem.criada_em),
    }


def conversa_saida(db: Session, conversa: m.ConversaAssistente, com_mensagens: bool = True) -> dict:
    saida = {
        "id": conversa.id,
        "tipo": conversa.tipo,
        "status": conversa.status,
        "titulo": conversa.titulo,
        "marca": conversa.marca,
        "criadaEm": ms(conversa.criada_em),
        "atualizadaEm": ms(conversa.atualizada_em),
        "atendimento": None,
    }
    if conversa.atendimento_id:
        atendimento = db.get(m.Atendimento, conversa.atendimento_id)
        if atendimento is not None:
            saida["atendimento"] = {"id": atendimento.id, "protocolo": atendimento.protocolo}
    if com_mensagens:
        mensagens = assistente_repository.mensagens(db, conversa.id, limite=regra.MENSAGENS_NO_HISTORICO)
        saida["mensagens"] = [mensagem_saida(msg) for msg in mensagens if msg.papel != regra.SISTEMA or msg.blocos]
    return saida


# ---------- Abrir e conferir o dono ----------


def _nova(db: Session, *, tipo: str, cliente_id=None, usuario_id=None, marca=None, chave_hash=None) -> m.ConversaAssistente:
    momento = agora()
    conversa = m.ConversaAssistente(
        id=uuid.uuid4().hex,
        tipo=tipo,
        cliente_id=cliente_id,
        usuario_id=usuario_id,
        chave_hash=chave_hash,
        marca=marca,
        status=regra.ATIVA,
        contexto={},
        criada_em=momento,
        atualizada_em=momento,
        expira_em=_validade(momento),
    )
    sessao.adicionar(db, conversa)
    sessao.gerar_ids(db)
    boas_vindas = m.MensagemAssistente(
        conversa_id=conversa.id,
        papel=regra.ASSISTENTE,
        conteudo=prompts.BOAS_VINDAS[tipo],
        blocos=[
            {"tipo": "sugestoes", "itens": regras_cliente.SUGESTOES if tipo == regra.CLIENTE else regras_gerenciais.SUGESTOES[:4]}
        ],
        modo=regra.REGRAS,
        criada_em=momento,
    )
    sessao.adicionar(db, boas_vindas)
    return conversa


def abrir_cliente(db: Session, *, cliente: m.Cliente | None, marca: str | None) -> tuple[m.ConversaAssistente, str]:
    """Conversa nova no site. Devolve a chave (só agora: no banco fica o hash)."""
    chave = secrets.token_urlsafe(24)
    conversa = _nova(db, tipo=regra.CLIENTE, cliente_id=cliente.id if cliente else None, marca=marca, chave_hash=_hash(chave))
    sessao.confirmar(db)
    return conversa, chave


def conversa_do_site(db: Session, conversa_id: str, chave: str | None, cliente: m.Cliente | None) -> m.ConversaAssistente:
    """A conversa, se esta pessoa pode abri-la; senão 404. Conversa sem dono que recebe um cliente logado
    (com a chave certa) passa a ser dele."""
    conversa = assistente_repository.obter(db, conversa_id, regra.CLIENTE)
    if conversa is None:
        raise NaoEncontrado("Conversa não encontrada.")
    if conversa.cliente_id is not None:
        if cliente is None or cliente.id != conversa.cliente_id:
            raise NaoEncontrado("Conversa não encontrada.")
        return conversa
    if not chave or not conversa.chave_hash or not hmac.compare_digest(_hash(chave), conversa.chave_hash):
        raise NaoEncontrado("Conversa não encontrada.")
    if cliente is not None:
        # Comita já: assim a conversa não segura o cadastro do cliente durante a resposta
        conversa.cliente_id = cliente.id
        sessao.confirmar(db)
    return conversa


def abrir_gerencial(db: Session, usuario: m.Usuario) -> m.ConversaAssistente:
    conversa = _nova(db, tipo=regra.GERENCIAL, usuario_id=usuario.id)
    sessao.confirmar(db)
    return conversa


def conversa_do_usuario(db: Session, conversa_id: str, usuario: m.Usuario) -> m.ConversaAssistente:
    conversa = assistente_repository.obter(db, conversa_id, regra.GERENCIAL)
    if conversa is None or conversa.usuario_id != usuario.id:
        raise NaoEncontrado("Conversa não encontrada.")
    return conversa


def conversas_do_usuario(db: Session, usuario: m.Usuario) -> list[dict]:
    lista = assistente_repository.do_usuario(db, usuario.id)
    perguntas = assistente_repository.contar_mensagens(db, [c.id for c in lista])
    return [
        {**conversa_saida(db, c, com_mensagens=False), "perguntas": perguntas.get(c.id, 0)} for c in lista if perguntas.get(c.id)
    ]


# ---------- Enviar mensagem ----------


def _contexto_cliente(db: Session, conversa: m.ConversaAssistente, cliente: m.Cliente | None) -> Contexto:
    return Contexto(
        tipo=regra.CLIENTE,
        conversa_id=conversa.id,
        origem=regra.REGRAS,
        cliente_id=cliente.id if cliente else None,
        marca_site=conversa.marca,
        memoria=dict(conversa.contexto or {}),
    )


def _contexto_gerencial(conversa: m.ConversaAssistente, usuario: m.Usuario, marca_escopo: str | None) -> Contexto:
    return Contexto(
        tipo=regra.GERENCIAL,
        conversa_id=conversa.id,
        origem=regra.REGRAS,
        usuario_id=usuario.id,
        papel=usuario.papel,
        marca_escopo=marca_escopo,
        memoria=dict(conversa.contexto or {}),
    )


def _dinamico_cliente(db: Session, ctx: Contexto, cliente: m.Cliente | None):
    def montar() -> str:
        lojas = [
            {"id": loja.id, "nome": loja.nome, "cidade": loja.cidade}
            for loja in cadastro_repository.lojas(db, somente_ativas=True, tipo="LOJA")
        ]
        primeiro = cliente.nome.split()[0] if cliente and cliente.nome else None
        return prompts.contexto_cliente(
            memoria=ctx.memoria, marca_site=ctx.marca_site, logado=cliente is not None, primeiro_nome=primeiro, lojas=lojas
        )

    return montar


def _dinamico_gerencial(db: Session, ctx: Contexto, usuario: m.Usuario):
    def montar() -> str:
        modulos = [modulo for modulo in ("financeiro", "estoque", "transferencias") if modulo in ACESSO]
        permite = [ROTULO_MODULO[mod] for mod in modulos if pode_acessar(usuario.papel, mod)]
        nega = [ROTULO_MODULO[mod] for mod in modulos if not pode_acessar(usuario.papel, mod)]
        return prompts.contexto_gerencial(
            nome=usuario.nome.split()[0],
            papel=ROTULO_PAPEL.get(usuario.papel, usuario.papel),
            marca_escopo=ctx.marca_escopo,
            permite=permite,
            nega=nega,
            dados_ate=data(analises.dados_ate(db, ctx.marca_escopo)),
            lojas=ferramentas_gerenciais.lojas_do_contexto(db, ctx.marca_escopo),
            categorias=cadastro_repository.nomes_categorias(db),
        )

    return montar


def _aplicar_acao(db: Session, ctx: Contexto, acao: dict | None) -> None:
    """Botões da tela que escolhem uma peça ("Quero esta"): a peça entra em foco antes da resposta."""
    if not acao or acao.get("tipo") != "FOCAR_PRODUTO":
        return
    produto = catalogo.produto_ativo(db, int(acao.get("produtoId") or 0))
    if produto is None:
        raise NaoEncontrado("Produto não encontrado.")
    ctx.memoria["produtoEmFoco"] = {"id": produto.id, "nome": produto.nome}
    ctx.memoria.pop("corEmFoco", None)
    ctx.acao = acao


def enviar(
    db: Session,
    conversa: m.ConversaAssistente,
    texto: str,
    *,
    id_cliente: str | None = None,
    acao: dict | None = None,
    cliente: m.Cliente | None = None,
    usuario: m.Usuario | None = None,
    marca_escopo: str | None = None,
    request_id: str | None = None,
) -> tuple[m.MensagemAssistente, m.MensagemAssistente]:
    """(pergunta, resposta). Trava a conversa durante a resposta e grava tudo numa transação."""
    texto = (texto or "").strip()
    if not texto:
        raise DadosInvalidos("Escreva uma mensagem.")
    if len(texto) > regra.TEXTO_MAXIMO[conversa.tipo]:
        raise DadosInvalidos(f"Mensagem longa demais (máximo de {regra.TEXTO_MAXIMO[conversa.tipo]} caracteres).")

    assistente_repository.travar(db, conversa.id)
    sessao.descartar_cache(db)
    if conversa.status == regra.ENCERRADA:
        raise Expirado("Esta conversa foi encerrada. Comece uma nova.")
    momento = agora()
    if conversa.atualizada_em < momento - timedelta(hours=settings.IA_CONVERSA_EXPIRA_HORAS):
        conversa.status = regra.ENCERRADA
        sessao.confirmar(db)
        raise Expirado("Esta conversa ficou parada por muito tempo. Comece uma nova.")

    pergunta = assistente_repository.por_id_cliente(db, conversa.id, id_cliente) if id_cliente else None
    if pergunta is not None and (resposta := assistente_repository.resposta_a(db, pergunta.id)) is not None:
        return pergunta, resposta  # reenvio: a resposta já existe

    historico = [
        (msg.papel, msg.conteudo)
        for msg in assistente_repository.mensagens(db, conversa.id, limite=settings.IA_HISTORICO_MENSAGENS + 4)
        if msg.papel != regra.SISTEMA
    ]
    if pergunta is None:
        pergunta = m.MensagemAssistente(
            conversa_id=conversa.id,
            papel=regra.USUARIO,
            conteudo=texto,
            blocos=[],
            id_cliente=id_cliente,
            request_id=request_id,
            criada_em=momento,
        )
        sessao.adicionar(db, pergunta)
        sessao.gerar_ids(db)

    if conversa.tipo == regra.CLIENTE:
        ctx = _contexto_cliente(db, conversa, cliente)
        _aplicar_acao(db, ctx, acao)
        rodada = responder(ASSISTENTE_CLIENTE, texto, ctx, historico, _dinamico_cliente(db, ctx, cliente))
    else:
        ctx = _contexto_gerencial(conversa, usuario, marca_escopo)
        rodada = responder(ASSISTENTE_GERENCIAL, texto, ctx, historico, _dinamico_gerencial(db, ctx, usuario))

    resposta = m.MensagemAssistente(
        conversa_id=conversa.id,
        papel=regra.ASSISTENTE,
        conteudo=rodada.texto,
        blocos=cru(rodada.blocos),
        modo=rodada.modo,
        responde_a_id=pergunta.id,
        request_id=request_id,
        criada_em=agora(),
    )
    sessao.adicionar(db, resposta)
    sessao.gerar_ids(db)
    for execucao in rodada.execucoes:
        sessao.adicionar(
            db,
            m.ChamadaFerramenta(
                conversa_id=conversa.id,
                mensagem_id=resposta.id,
                ferramenta=execucao.nome,
                argumentos=cru(execucao.argumentos)
                if isinstance(execucao.argumentos, dict)
                else {"bruto": str(execucao.argumentos)[:200]},
                sucesso=execucao.sucesso,
                erro=(execucao.erro or "")[:255] or None,
                duracao_ms=execucao.duracao_ms,
                origem=execucao.origem or rodada.modo,
                criada_em=resposta.criada_em,
            ),
        )
    for consumo in rodada.consumos:
        sessao.adicionar(db, m.ConsumoIA(conversa_id=conversa.id, tipo=conversa.tipo, criado_em=resposta.criada_em, **consumo))
    conversa.contexto = _limpar_memoria(rodada.memoria)
    conversa.atualizada_em = resposta.criada_em
    conversa.expira_em = _validade(resposta.criada_em)
    if conversa.titulo is None:
        conversa.titulo = texto[:120]
    sessao.confirmar(db)
    return pergunta, resposta


# ---------- Sacola, atendimento humano e encerramento ----------


def registrar_sacola(db: Session, conversa: m.ConversaAssistente, mensagem_id: int, variacao_id: int) -> None:
    """O cliente tocou em "Adicionar à sacola": o botão vira confirmado e a conversa lembra disso."""
    assistente_repository.travar(db, conversa.id)
    mensagem = assistente_repository.mensagem(db, conversa.id, mensagem_id)
    blocos = list(mensagem.blocos or []) if mensagem else []
    indice = next(
        (
            i
            for i, b in enumerate(blocos)
            if b.get("tipo") == "acao_sacola" and (b.get("item") or {}).get("variacaoId") == variacao_id
        ),
        None,
    )
    if indice is None:
        raise NaoEncontrado("Ação não encontrada nesta conversa.")
    item = blocos[indice]["item"]
    if blocos[indice].get("estado") != "CONFIRMADO":
        blocos[indice] = {**blocos[indice], "estado": "CONFIRMADO"}
        mensagem.blocos = blocos
        descricao = f"O cliente adicionou {item['nome']} ({item['cor']}, {item['tamanho']}) à sacola"
        momento = agora()
        sessao.adicionar(
            db,
            m.MensagemAssistente(conversa_id=conversa.id, papel=regra.SISTEMA, conteudo=descricao, blocos=[], criada_em=momento),
        )
        memoria = dict(conversa.contexto or {})
        memoria["eventos"] = [*(memoria.get("eventos") or []), descricao][-5:]
        memoria["oferta"] = None
        conversa.contexto = _limpar_memoria(memoria)
        conversa.atualizada_em = momento
    sessao.confirmar(db)


def _resumo_para_atendimento(db: Session, conversa: m.ConversaAssistente, motivo: str | None) -> str:
    memoria = conversa.contexto or {}
    linhas = ["Solicitação aberta pelo assistente virtual do site, a pedido do cliente."]
    if motivo:
        linhas.append(f"Motivo: {motivo.strip()[:300]}")
    linhas.append(f"Vitrine: {prompts.NOME_MARCA.get(conversa.marca or '', 'Casa Lorenzi')}")
    if foco := memoria.get("produtoEmFoco"):
        escolha = ", ".join(x for x in (memoria.get("corEmFoco"), memoria.get("tamanhoEmFoco")) if x)
        linhas.append(f"Peça em foco: {foco['nome']}{f' ({escolha})' if escolha else ''}")
    if busca := memoria.get("buscaDescricao"):
        linhas.append(f"Última busca: {busca}")
    linhas.append("Últimas mensagens:")
    for msg in assistente_repository.mensagens(db, conversa.id, limite=8):
        if msg.papel == regra.SISTEMA or not msg.conteudo:
            continue
        autor = "Cliente" if msg.papel == regra.USUARIO else "Assistente"
        linhas.append(f"- {autor}: {msg.conteudo.strip()[:300]}")
    linhas.append(f"(Registro do assistente: conversa {conversa.id})")
    return "\n".join(linhas)[:3000]


def _tipo_para_atendimento(db: Session) -> m.TipoSolicitacao:
    tipos = [t for t in cadastro_repository.tipos_solicitacao(db, ativo=True) if not t.exige_venda]
    if not tipos:
        raise DadosInvalidos("Nenhum tipo de solicitação disponível para o encaminhamento.")
    return next((t for t in tipos if t.titulo == "Dúvida sobre produto"), tipos[0])


def encaminhar(db: Session, conversa: m.ConversaAssistente, cliente: m.Cliente | None, motivo: str | None) -> m.Atendimento:
    """Abre um chamado de atendimento (o mesmo do site e do painel) com o resumo da conversa. Idempotente:
    a mesma conversa não abre dois chamados."""
    if cliente is None:
        raise NaoAutenticado("Entre na sua conta para falar com a equipe.")
    assistente_repository.travar(db, conversa.id)
    if conversa.atendimento_id:
        existente = db.get(m.Atendimento, conversa.atendimento_id)
        if existente is not None:
            return existente
    resumo = _resumo_para_atendimento(db, conversa, motivo)
    tipo = _tipo_para_atendimento(db)
    atendimento = atendimentos.abrir_para_cliente(db, cliente, tipo_solicitacao_id=tipo.id, pedido_id=None, descricao=resumo)
    conversa = assistente_repository.obter(db, conversa.id, regra.CLIENTE)
    conversa.atendimento_id = atendimento.id
    conversa.status = regra.ENCAMINHADA
    momento = agora()
    texto = f"Pronto! Abri a solicitação {atendimento.protocolo}. A equipe responde por lá, em Minha conta > Solicitações."
    sessao.adicionar(
        db,
        m.MensagemAssistente(
            conversa_id=conversa.id,
            papel=regra.ASSISTENTE,
            conteudo=texto,
            blocos=[
                {
                    "tipo": "atendimento_aberto",
                    "atendimentoId": atendimento.id,
                    "protocolo": atendimento.protocolo,
                    "link": f"/cliente/solicitacoes/{atendimento.id}",
                }
            ],
            modo=regra.REGRAS,
            criada_em=momento,
        ),
    )
    conversa.atualizada_em = momento
    sessao.confirmar(db)
    return atendimento


def encerrar(db: Session, conversa: m.ConversaAssistente) -> None:
    conversa.status = regra.ENCERRADA
    conversa.atualizada_em = agora()
    sessao.confirmar(db)


def apagar_vencidas(db: Session) -> int:
    """Retenção: apaga as conversas sem atividade há mais de IA_RETENCAO_DIAS (o consumo fica, sem a conversa)."""
    return assistente_repository.apagar_expiradas(db, agora())


# ---------- Uso e custo ----------


def metricas(db: Session, dias: int = 30) -> dict:
    """Uso dos assistentes no período: conversas, respostas por modo, chamadas ao modelo, tokens, custo estimado
    e consultas (com a taxa de falha). Sem dado pessoal."""
    desde = agora() - timedelta(days=dias)
    consumo = assistente_repository.consumo_desde(db, desde)
    por_dia: dict[str, dict] = {}
    total = {
        "chamadas": 0,
        "entrada": 0,
        "saida": 0,
        "cacheLeitura": 0,
        "cacheEscrita": 0,
        "custo": 0.0,
        "erros": 0,
        "recusas": 0,
    }
    por_modelo: dict[str, dict] = {}
    duracoes = []
    for linha in consumo:
        dia = linha.dia.date().isoformat()
        registro = por_dia.setdefault(dia, {"dia": dia, "chamadas": 0, "tokens": 0, "custo": 0.0})
        registro["chamadas"] += linha.chamadas
        registro["tokens"] += int(linha.entrada) + int(linha.saida)
        registro["custo"] += float(linha.custo)
        total["chamadas"] += linha.chamadas
        total["entrada"] += int(linha.entrada)
        total["saida"] += int(linha.saida)
        total["cacheLeitura"] += int(linha.cache_leitura)
        total["cacheEscrita"] += int(linha.cache_escrita)
        total["custo"] += float(linha.custo)
        total["erros"] += linha.chamadas if linha.status in ("ERRO", "TIMEOUT") else 0
        total["recusas"] += linha.chamadas if linha.status == "RECUSA" else 0
        modelo = por_modelo.setdefault(linha.modelo, {"modelo": linha.modelo, "chamadas": 0, "custo": 0.0})
        modelo["chamadas"] += linha.chamadas
        modelo["custo"] += float(linha.custo)
        duracoes.append((float(linha.duracao), linha.chamadas))
    respostas = {}
    for tipo, modo, quantidade in assistente_repository.respostas_desde(db, desde):
        respostas.setdefault(tipo, {})[modo or "SEM_MODO"] = quantidade
    conversas = {}
    for tipo, status, quantidade in assistente_repository.conversas_desde(db, desde):
        conversas.setdefault(tipo, {})[status] = quantidade
    ferramentas_uso = {}
    for nome, sucesso, quantidade, duracao in assistente_repository.ferramentas_desde(db, desde):
        linha = ferramentas_uso.setdefault(nome, {"ferramenta": nome, "chamadas": 0, "falhas": 0, "duracaoMediaMs": 0})
        linha["chamadas"] += quantidade
        linha["falhas"] += 0 if sucesso else quantidade
        linha["duracaoMediaMs"] = max(linha["duracaoMediaMs"], int(duracao))
    peso = sum(q for _, q in duracoes)
    return {
        "dias": dias,
        "modoIA": "LLM" if settings.ANTHROPIC_API_KEY else "REGRAS",
        "modelo": settings.IA_MODELO,
        "conversas": conversas,
        "respostasPorModo": respostas,
        "chamadasAoModelo": total,
        "latenciaMediaMs": int(sum(d * q for d, q in duracoes) / peso) if peso else 0,
        "porDia": sorted(por_dia.values(), key=lambda d: d["dia"]),
        "porModelo": list(por_modelo.values()),
        "ferramentas": sorted(ferramentas_uso.values(), key=lambda f: -f["chamadas"]),
        "precosReferencia": {k: [float(v[0]), float(v[1])] for k, v in regra.PRECOS_MTOK.items()},
    }
