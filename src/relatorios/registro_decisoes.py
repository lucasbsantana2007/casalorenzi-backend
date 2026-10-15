"""Gera docs/registro_decisoes.md no formato da banca, a partir de `migracao_ocorrencias` e dos números da
diretoria. Os textos (o que encontramos, o que decidimos e por quê) estão aqui; os números vêm do banco.

    python -m src.relatorios.registro_decisoes --saida docs/registro_decisoes.md

Rode depois da migração (`python -m src.migracao_vulto --tudo`), contra o banco que tem os dados.
"""

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import SessionLocal
from src.entities.marca import VULTO
from src.migracao_vulto.fidelidade import CATEGORIA_DECLARADA
from src.use_cases import diretoria

# ---------- Formatação ----------


def reais(valor, sinal: bool = False) -> str:
    numero = Decimal(str(valor or 0)).quantize(Decimal("0.01"))
    texto = f"{abs(numero):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    prefixo = "−" if numero < 0 else ("+" if sinal and numero > 0 else "")
    return f"{prefixo}R$ {texto}"


def milhar(numero, sinal: bool = False) -> str:
    inteiro = int(numero or 0)
    prefixo = "−" if inteiro < 0 else ("+" if sinal and inteiro > 0 else "")
    return prefixo + f"{abs(inteiro):,}".replace(",", ".")


UNIDADES = {"REAIS": None, "PONTOS": "pontos", "UNIDADES": "peças", "REGISTROS": "registros"}


# ---------- Os números ----------


class Numeros(dict):
    """Tudo o que os textos citam: ocorrências (n_CODIGO, i_CODIGO), a ponte do faturamento (p_passo), os
    totais das três respostas e algumas contagens direto do staging. Usado com str.format(**numeros)."""

    def __init__(self, db: Session):
        super().__init__()
        self.ocorrencias: dict[str, dict] = {}
        for dominio, codigo, acao, registros, impacto, unidade, origem, descricao in db.execute(
            select(
                m.MigracaoOcorrencia.dominio,
                m.MigracaoOcorrencia.codigo_problema,
                func.string_agg(func.distinct(m.MigracaoOcorrencia.acao_tomada), "/"),
                func.count(),
                func.sum(m.MigracaoOcorrencia.impacto),
                func.max(m.MigracaoOcorrencia.impacto_unidade),
                func.max(m.MigracaoOcorrencia.origem),
                func.min(m.MigracaoOcorrencia.descricao),
            ).group_by(m.MigracaoOcorrencia.dominio, m.MigracaoOcorrencia.codigo_problema)
        ):
            self.ocorrencias[codigo] = {
                "dominio": dominio, "acao": acao, "registros": registros, "impacto": impacto, "unidade": unidade,
                "origem": origem, "descricao": descricao,
            }  # fmt: skip
            self[f"n_{codigo}"] = milhar(registros)
            self[f"i_{codigo}"] = self.impacto(codigo)
            self[f"a_{codigo}"] = milhar(abs(impacto or 0))

        dados = diretoria.numeros(db)
        self.dados = dados
        fat, est, pas = dados["faturamento"], dados["estoque"], dados["passivo"]
        for passo in fat["ponte"]:
            self[f"p_{passo['chave']}"] = reais(passo["valor"], sinal=True)
        margem = {item["item"]: item for item in fat["margem"]["itens"]}
        vazio = next(v for k, v in margem.items() if k.startswith("Status vazio"))
        batel = next(v for k, v in margem.items() if k.startswith("Batel"))
        self.update(
            fat_sem_frete=reais(fat["total"]["semFrete"]), fat_com_frete=reais(fat["total"]["comFrete"]),
            fat_vendas=milhar(fat["total"]["pedidos"]), fat_devolucoes=reais(fat["total"]["devolucoes"]),
            fat_min=reais(fat["margem"]["minimo"]), fat_max=reais(fat["margem"]["maximo"]),
            vazio_vendas=milhar(vazio["registros"]), vazio_valor=reais(vazio["valor"]), batel_valor=reais(batel["valor"]),
            est_total=milhar(est["total"]), est_min=milhar(est["margem"]["minimo"]), est_max=milhar(est["margem"]["maximo"]),
            est_legado=milhar(est["total"] - int(self.ocorrencias["ESTOQUE_DO_LEGADO_SO_COMPARACAO"]["impacto"] or 0)),
        )  # fmt: skip
        cenarios = {c["validadeOuroMeses"]: c for c in pas["cenarios"]}
        faixa = pas["faixa"]
        self.update(
            pas_pontos=milhar(faixa["vigente"]["pontos"]), pas_vigente=reais(faixa["vigente"]["valor"]),
            pas_min=reais(faixa["minimo"]["valor"]), pas_max=reais(faixa["maximo"]["valor"]),
            pas_antigo=reais(cenarios[18]["valorAntigo"]), pas_ouro12=reais(cenarios[12]["valorVigente"]),
            pas_dif_ouro=milhar(cenarios[18]["pontos"] - cenarios[12]["pontos"]),
            pas_dobro=milhar(pas["naoAplicados"]["dobroOnline"]), pas_bonus=milhar(pas["naoAplicados"]["bonusOuro"]),
        )  # fmt: skip
        self._staging(db)
        self._plataforma(db)

    def impacto(self, codigo: str) -> str:
        ocorrencia = self.ocorrencias.get(codigo)
        if ocorrencia is None or ocorrencia["impacto"] is None:
            return "—"
        unidade = UNIDADES.get(ocorrencia["unidade"])
        if unidade is None:
            return reais(ocorrencia["impacto"], sinal=True)
        return f"{milhar(ocorrencia['impacto'], sinal=unidade != 'registros')} {unidade}"

    def __missing__(self, chave: str) -> str:
        if chave.startswith(("n_", "i_", "a_")):
            return "—" if chave.startswith("i_") else "0"  # código que não ocorreu nesta carga
        raise KeyError(chave)

    def _staging(self, db: Session) -> None:
        """Contagens que não viram ocorrência: formatos de data, grafias de canal e status, vírgula decimal."""
        formatos: set[str] = set()
        utc = 0
        consultas = (
            "SELECT criado_em FROM legado_vulto.db__vendas",
            "SELECT criado_em FROM legado_vulto.db__compras",
            "SELECT criado_em FROM legado_vulto.db__pontos_mov",
            "SELECT data_hora FROM legado_vulto.atendimentos",
            "SELECT data FROM legado_vulto.clientes__resgates",
        )
        for consulta in consultas:
            for (valor,) in db.execute(text(consulta)):
                formato = re.sub(r"[a-zç]{3}", "mmm", re.sub(r"\d", "9", (valor or "").strip().lower()))
                formatos.add(formato)
                utc += (valor or "").strip().endswith("Z")
        canais = db.scalar(text("SELECT count(DISTINCT coalesce(canal, '')) FROM legado_vulto.db__vendas"))
        status = db.scalar(text("SELECT count(DISTINCT coalesce(status, '')) FROM legado_vulto.db__vendas"))
        virgula = db.scalar(
            text(
                "SELECT (SELECT count(*) FROM legado_vulto.db__vendas WHERE total LIKE '%,%' OR frete LIKE '%,%' "
                "OR desconto LIKE '%,%') + (SELECT count(*) FROM legado_vulto.db__itens_venda WHERE preco_unit LIKE '%,%')"
            )
        )
        resgates = db.scalar(text("SELECT count(*) FROM legado_vulto.clientes__resgates"))
        estoque_linhas, estoque_negativas = db.execute(
            text("SELECT count(*), count(*) FILTER (WHERE qtd ~ '^-[0-9]+$') FROM legado_vulto.db__estoque")
        ).one()
        self.update(
            n_formatos_data=milhar(len(formatos - {""})), n_utc=milhar(utc), n_grafias_canal=milhar(canais),
            n_status=milhar(status), n_virgula=milhar(virgula), n_resgates_planilha=milhar(resgates),
            n_estoque_linhas=milhar(estoque_linhas), n_estoque_negativas=milhar(estoque_negativas),
        )  # fmt: skip

    def _plataforma(self, db: Session) -> None:
        """Contagens na plataforma: clientes vindos da Vulto, aliases de SKU, itens vendidos abaixo do catálogo."""
        clientes = db.scalar(
            select(func.count(func.distinct(m.DePara.id_destino))).where(
                m.DePara.tabela_destino == "clientes", m.DePara.origem.like("%vulto%") | m.DePara.origem.like("%.xlsx%")
                | m.DePara.origem.like("%.csv%") | m.DePara.origem.like("vulto.db%")
            )
        )  # fmt: skip
        aliases = db.scalar(select(func.count()).select_from(m.SkuAlias))
        abaixo, desconto = db.execute(
            select(
                func.count(),
                func.coalesce(func.sum((m.Produto.preco_base - m.ItemPedido.preco_unitario) * m.ItemPedido.quantidade), 0),
            )
            .select_from(m.ItemPedido)
            .join(m.Pedido, m.Pedido.id == m.ItemPedido.pedido_id)
            .join(m.Loja, m.Loja.id == m.Pedido.loja_id)
            .join(m.Variacao, m.Variacao.id == m.ItemPedido.variacao_id)
            .join(m.Produto, m.Produto.id == m.Variacao.produto_id)
            .where(
                m.Loja.marca == VULTO,
                m.Pedido.tipo == "VENDA",
                m.ItemPedido.preco_unitario < m.Produto.preco_base * Decimal("0.99"),
            )
        ).one()
        divergentes = sum(
            1
            for declarada, categoria in db.execute(
                select(m.ContaPontos.categoria_declarada, m.ContaPontos.categoria).where(
                    m.ContaPontos.categoria_declarada.is_not(None)
                )
            )
            if CATEGORIA_DECLARADA.get(declarada.strip().lower()) != categoria
        )
        saldo_inicial = db.scalar(
            select(func.coalesce(func.sum(m.MovimentoPontos.quantidade), 0)).where(m.MovimentoPontos.tipo == "SALDO_INICIAL")
        )
        self.update(
            n_clientes=milhar(clientes), n_aliases=milhar(aliases), n_itens_abaixo=milhar(abaixo),
            desconto_abaixo=reais(desconto), saldo_inicial=milhar(saldo_inicial),
            n_categoria_diverge=milhar(divergentes),
        )  # fmt: skip


# ---------- O catálogo ----------


@dataclass(frozen=True)
class Problema:
    titulo: str  # O que encontramos
    onde: str
    registros: str
    decisao: str
    porque: str
    impacto: str
    codigos: tuple[str, ...] = ()  # ocorrências que este problema cobre (o apêndice lista todas)


PROBLEMAS = (
    Problema(
        "Valores em centavos × reais, e vírgula decimal",
        '`vulto.db`: `vendas.total`, `itens_venda.preco_unit`, `compras.valor` (app); planilhas com "1.234,56"',
        "{n_VALOR_EM_CENTAVOS} vendas em centavos; {n_virgula} valores com vírgula decimal",
        "Centavos detectados pela razão com o preço do catálogo e convertidos; vírgula decimal e milhar com ponto lidos "
        "por `normalizacao.dinheiro`.",
        'O app grava em centavos ("19081" = R$ 190,81) e o sistema somava como reais; o preço do catálogo diz qual '
        "escala é a certa.",
        "Faturamento: {p_centavos} na ponte (o relatório da Vulto estava inflado). Pontos: {i_CREDITO_INFLADO_BUG_APP} "
        "em {n_CREDITO_INFLADO_BUG_APP} créditos do bug do app v3.4.",
        ("VALOR_EM_CENTAVOS", "CREDITO_INFLADO_BUG_APP"),
    ),
    Problema(
        "Datas em vários formatos, inclusive UTC com `Z`",
        "`vendas.criado_em`, `compras.criado_em`, `pontos_mov.criado_em`, `atendimentos.csv:data_hora`, aba Resgates",
        "{n_formatos_data} formatos diferentes; {n_utc} datas em UTC (`Z`)",
        'Uma função (`normalizacao.data_hora`) lê todos (ISO com e sem `Z`, dd/mm/aaaa, dd/mm/aa, "set/23", número de '
        "série do Excel); sem fuso = Brasília; `Z` = UTC, convertido para Brasília.",
        "Site e app gravam em UTC: somar pelo dia sem converter joga a venda das 21h às 24h para o dia (e às vezes o mês) "
        "seguinte.",
        "Faturamento: {p_fuso} na ponte (vendas que mudam de mês).",
    ),
    Problema(
        "Canal com várias grafias; texto do canal × loja da venda",
        "`vendas.canal` × `vendas.loja_id` (lojas 5 = site e 6 = app no legado)",
        "{n_grafias_canal} grafias; {n_CANAL_TEXTO_DIVERGE} vendas com o texto contradizendo a loja",
        "Canal pela loja do legado (1 a 4 loja física, 5 E-commerce, 6 App); site e app viraram canais, não lojas, e "
        "expedem do CD Cajamar.",
        "A loja é preenchida pelo sistema; o texto é digitado e varia.",
        "Nenhum no total: muda a divisão por canal dessas {n_CANAL_TEXTO_DIVERGE} vendas.",
        ("CANAL_TEXTO_DIVERGE", "LOJA_VIRTUAL_VIRA_CANAL"),
    ),
    Problema(
        "Status com várias grafias, inclusive vazio",
        "`vendas.status`",
        "{n_status} grafias; {n_STATUS_VAZIO_COMO_PAGO} vendas com status vazio",
        "Status mapeado para o da plataforma; vazio = pago.",
        "As vendas com status vazio são de lojas físicas (jan–fev/25), com itens e conta fechando: o PDV deixava em "
        "branco o que era pago.",
        "Faturamento: as {vazio_vendas} vendas com status vazio somam {vazio_valor}; se alguma não foi paga, o número "
        "cai (é o principal item da margem).",
        ("STATUS_VAZIO_COMO_PAGO",),
    ),
    Problema(
        "Trocas lançadas como venda nova",
        '`vendas` (obs "troca", valor cheio)',
        "{n_TROCA_FORA_DA_RECEITA} trocas",
        "Viram pedido `TROCA`: baixam o estoque da peça nova, mas ficam fora da receita.",
        "A venda original já contou; somar a troca conta a mesma receita duas vezes.",
        "Faturamento: {p_trocas} na ponte.",
        ("TROCA_FORA_DA_RECEITA",),
    ),
    Problema(
        "Devoluções com valor negativo",
        "`vendas` com total negativo",
        "{n_DEVOLUCAO_REFERENCIA} ligadas pela obs, {n_DEVOLUCAO_CLIENTE} pela última compra do cliente, "
        "{n_DEVOLUCAO_SEM_ORIGEM} sem origem",
        "Viram `devolucoes` ligadas à venda (a citada na obs; senão, a última compra do mesmo cliente com a mesma peça; "
        "senão, sem origem) e devolvem a peça ao estoque.",
        "Devolução não é venda negativa: é a saída da receita na data em que aconteceu.",
        "Faturamento líquido: −{fat_devolucoes} de devoluções na data em que aconteceram; na ponte, {p_devolucoes} (o "
        "relatório da Vulto já descontava).",
        ("DEVOLUCAO_REFERENCIA", "DEVOLUCAO_CLIENTE", "DEVOLUCAO_SEM_ORIGEM"),
    ),
    Problema(
        "Frete: receita ou repasse",
        "`vendas.frete` (e o app somando o frete no total sem gravar na coluna)",
        "{n_FRETE_EMBUTIDO_NO_TOTAL} vendas com o frete embutido no total",
        "Frete separado do total; o faturamento oficial é sem frete (aprovado), com o frete como um passo da ponte.",
        "É assim que o financeiro da Casa Lorenzi já calcula a receita (pelos itens): o frete é repasse à transportadora.",
        "Faturamento: {p_frete} na ponte ({fat_sem_frete} sem frete; {fat_com_frete} com frete).",
        ("FRETE_EMBUTIDO_NO_TOTAL",),
    ),
    Problema(
        "Batel sem PDV (02 a 22/03/2026), com relançamento parcial",
        "`vendas_batel_MANUAL_marco.xlsx` × `vulto.db:vendas`",
        "{n_BATEL_VENDA_MANUAL} vendas só na planilha; {n_BATEL_JA_RELANCADA} já relançadas; {n_BATEL_DATA_INVERTIDA} "
        "com dia e mês trocados",
        "Entra a planilha manual menos o que foi relançado no sistema (mesmo CPF e valor); a relançada volta para a data "
        "real; datas com dia e mês trocados pelo Excel, destrocadas.",
        "Sem isso, março da Batel some do sistema; com os dois, conta em dobro.",
        "Faturamento: {p_batel} na ponte; a planilha manual é parte da margem.",
        (
            "BATEL_VENDA_MANUAL",
            "BATEL_JA_RELANCADA",
            "BATEL_RELANCADA_REDATADA",
            "BATEL_DATA_INVERTIDA",
            "BATEL_RELANCADA_SEM_PAR",
            "BATEL_TOTAL_DA_PLANILHA",
            "BATEL_PIX_FALTANDO",
        ),
    ),  # fmt: skip
    Problema(
        "Servidor do PDV do Eldorado trocado (fev/26)",
        "`vendas.criado_em` da loja 2",
        "{a_ELDORADO_SERVIDOR_TROCADO} vendas que o sistema da Vulto contava no dia seguinte",
        "Desde a troca, as datas do Eldorado vêm em UTC (`Z`): convertidas para Brasília.",
        "O servidor novo grava em UTC; as vendas da noite caíam no dia seguinte.",
        "Faturamento: entra no passo de fuso horário ({p_fuso}).",
        ("ELDORADO_SERVIDOR_TROCADO",),
    ),
    Problema(
        "Ship from store baixando o estoque do site",
        '`vendas` do site com obs "sfs pinheiros"',
        "{n_SHIP_FROM_STORE} pedidos",
        "Pedido do site que saiu de Pinheiros: a loja de expedição é Pinheiros (baixa de lá), o canal continua E-commerce.",
        'O sistema da Vulto baixava da "loja" site, que não tem estoque físico.',
        "Estoque: as peças saem de Pinheiros, não do CD. Faturamento: nenhum.",
        ("SHIP_FROM_STORE",),
    ),
    Problema(
        "Estoque da Vulto com 1.156 linhas negativas",
        "`vulto.db:estoque`",
        '{n_estoque_linhas} linhas, {n_estoque_negativas} negativas; {a_ESTOQUE_DAS_LOJAS_VIRTUAIS} peças nas "lojas" 5 e 6',
        "A tabela não entra: o estoque é reconstruído movimento a movimento e a tabela só serve de comparação.",
        "Sem histórico e com negativos, não dá para confiar no saldo; as vendas online baixavam das lojas 5 e 6.",
        "Estoque em 01/10/2026: {est_total} peças (o sistema da Vulto dizia {est_legado}).",
        ("ESTOQUE_DO_LEGADO_SO_COMPARACAO", "ESTOQUE_DAS_LOJAS_VIRTUAIS"),
    ),
    Problema(
        "Estoque sem histórico",
        "`vulto.db:entradas_estoque`, vendas, contagem de set/26",
        "{n_CONTAGEM_DIFERE_DO_RECONSTRUIDO} itens com contagem diferente do reconstruído; "
        "{a_TRANSFERENCIA_DOS_DOIS_LADOS} peças de transferências anotadas dos dois lados",
        "Histórico reconstruído (notas de entrada, transferências contadas uma vez, vendas e devoluções); a contagem de "
        "set/26 é a âncora; a abertura em 01/01/2025 é a menor que deixa o histórico sem negativo.",
        "É o único jeito de ter o saldo em qualquer data; a contagem é o dado mais confiável.",
        "Estoque: abertura estimada de {a_ABERTURA_ESTIMADA} peças; ajuste da contagem de {i_CONTAGEM_DIFERE_DO_RECONSTRUIDO}. "
        "O saldo de 01/10/2026 é o contado mais os movimentos depois.",
        (
            "ABERTURA_ESTIMADA",
            "CONTAGEM_DIFERE_DO_RECONSTRUIDO",
            "TRANSFERENCIA_DOS_DOIS_LADOS",
            "TRANSFERENCIA_ENTRE_LOJAS",
            "CONTAGEM_SEM_DATA",
            "SALDO_NEGATIVO_DEPOIS_DA_CONTAGEM",
        ),
    ),  # fmt: skip
    Problema(
        "Contagem da Savassi por modelo",
        "`contagem_inventario_set26.xlsx:savassi_por_modelo`",
        "{n_SAVASSI_CONTAGEM_POR_MODELO} modelos",
        "O total de cada modelo foi rateado entre as variações pelo mix de entradas e vendas.",
        "Sem a cor e o tamanho, não dá para saber qual variação foi contada.",
        "Estoque: {a_SAVASSI_CONTAGEM_POR_MODELO} peças na Savassi — total exato, cor e tamanho estimados.",
        ("SAVASSI_CONTAGEM_POR_MODELO", "SAVASSI_MODELO_SEM_PRODUTO"),
    ),
    Problema(
        "SKU em vários formatos e código reaproveitado entre coleções",
        "`catalogo.xlsx`, `itens_venda.sku`, `entradas_estoque.sku`, contagens",
        "{n_aliases} grafias guardadas como alias; {n_CODIGO_REAPROVEITADO} códigos reaproveitados; "
        "{n_GRAFIA_DE_SKU_ILEGIVEL} grafias ilegíveis",
        "SKU canônico `VLT-CAT-NNN-COR-TAM`; cada grafia vira alias com vigência; peça de 2024 com código reaproveitado "
        "vira outro produto, inativo, com SKU terminado em `-2024`.",
        "As vendas antigas precisam apontar para a peça certa da época.",
        "Nenhum direto no total: é o que liga cada venda, entrada e contagem à peça certa.",
        (
            "CODIGO_REAPROVEITADO",
            "GRAFIA_DE_SKU_ILEGIVEL",
            "GRAFIA_SEM_PRODUTO",
            "LINHA_VARIOS_TAMANHOS",
            "VARIACAO_FORA_DO_CATALOGO",
            "VENDIDO_SEM_CADASTRO",
            "EAN_INVALIDO",
            "EAN_DIVERGE_ENTRE_COLECOES",
            "CONTAGEM_SKU_DIGITADO_ERRADO",
            "CONTAGEM_SKU_ILEGIVEL",
        ),
    ),  # fmt: skip
    Problema(
        "Conflito de preço: o da coleção mais nova × o menor",
        "`catalogo.xlsx` (peça em mais de uma aba)",
        "{n_PRECO_ENTRE_COLECOES} peças",
        "Vale o menor preço (Operações/Financeiro, por causa do Procon); o parâmetro aceita o da coleção mais nova.",
        "Cobrar mais do que o anunciado em qualquer coleção vigente é risco no Procon.",
        "Catálogo: {i_PRECO_ENTRE_COLECOES} no preço de venda. Faturamento: nenhum (a venda vale pelo preço vendido).",
        ("PRECO_ENTRE_COLECOES", "PRECO_DIVERGE_NA_ABA", "PRECO_A_REVISAR"),
    ),
    Problema(
        "Conflito de custo: último × médio",
        "`catalogo.xlsx:custo`, notas de entrada",
        "{n_CUSTO_DA_NOTA} peças sem custo na planilha",
        "Guardamos os dois: `preco_custo` = último custo (o da aba mais recente; sem ele, a última nota) e `custo_medio` = "
        "média ponderada das notas de entrada.",
        "Compras usa o último para precificar; o Financeiro, o médio para a margem.",
        "Nenhum no faturamento; muda a margem bruta conforme o custo escolhido.",
        ("CUSTO_DA_NOTA",),
    ),
    Problema(
        "Promoções não registradas",
        "`itens_venda.preco_unit` abaixo do preço do catálogo; total menor que a soma dos itens",
        "{n_itens_abaixo} itens vendidos abaixo do catálogo; {n_DESCONTO_NAO_REGISTRADO} vendas com desconto não registrado",
        "A venda vale pelo preço praticado; diferença entre o total e os itens vira desconto.",
        "A receita é o que o cliente pagou; o preço de catálogo é referência.",
        "Faturamento: nenhum (já é o preço vendido). Diferença para o preço de catálogo: {desconto_abaixo}.",
        ("DESCONTO_NAO_REGISTRADO", "TOTAL_NAO_FECHA"),
    ),
    Problema(
        "Clientes duplicados; `cliente_ref` misturando CPF, e-mail e telefone",
        "`clientes.xlsx` (Clientes, antigos), `vendas.cliente_ref`, `compras.cliente_ref`, contatos do atendimento",
        "{n_CADASTROS_FUNDIDOS} cadastros fundidos; {n_IDENTIFICADORES_LIGADOS} e-mails/telefones ligados; "
        "{n_REFERENCIA_AMBIGUA} referências ambíguas",
        "Uma pessoa = um cliente: junta por CPF, depois e-mail, depois telefone, sem nunca juntar CPFs diferentes; o "
        "`cliente_ref` é classificado (CPF válido vence; celular que também passa como CPF fica marcado).",
        "Sem isso, a mesma pessoa aparece várias vezes e os pontos e pedidos se espalham.",
        "{n_clientes} clientes da Vulto; {n_REFERENCIA_SEM_CLIENTE} referências não identificam ninguém (pedido sem cliente).",
        (
            "CADASTROS_FUNDIDOS",
            "IDENTIFICADORES_LIGADOS",
            "REFERENCIA_AMBIGUA",
            "REFERENCIA_SEM_CLIENTE",
            "EMAIL_DIVERGE_ENTRE_DUPLICATAS",
            "NOME_DIVERGE_ENTRE_DUPLICATAS",
            "TELEFONE_DIVERGE_ENTRE_DUPLICATAS",
            "EMAIL_DE_OUTRA_PESSOA",
            "CPF_INVALIDO",
            "EMAIL_INVALIDO",
            "TELEFONE_INVALIDO",
            "CLIENTE_SEM_NOME",
            "VENDA_SEM_CLIENTE",
            "REFERENCIA_DE_TESTE",
            "NAO_LIGAR_COM_ACEITE",
        ),
    ),  # fmt: skip
    Problema(
        "Coluna Pontos congelada em 01/2025, com formatos misturados",
        "`clientes.xlsx:Clientes.Pontos`",
        '{n_SALDO_COM_FORMATO} com ponto de milhar ou "pts"; {n_SALDO_ARREDONDADO} arredondados ("2,7k"); '
        "{n_SALDOS_DUPLICADOS_SOMADOS} clientes duplicados",
        '"2.203" = 2203; "1389 pts" = 1389; "2,7k" = 2700 (estimado); duplicados somam; os pontos do programa antigo '
        "não somam de novo.",
        'O sistema lia "2,7k" como zero e só a primeira linha do CPF.',
        "Pontos: saldo inicial de {saldo_inicial} pontos em 01/01/2025.",
        ("SALDO_COM_FORMATO", "SALDO_ARREDONDADO", "SALDOS_DUPLICADOS_SOMADOS", "SALDO_SEM_CPF", "PONTOS_ANTIGOS_JA_MIGRADOS"),
    ),
    Problema(
        "Resgates fora do sistema (aba Resgates)",
        "`clientes.xlsx:Resgates`",
        "{n_resgates_planilha} linhas; {n_RESGATE_SO_NA_PLANILHA} só na planilha; {n_RESGATE_SEM_CPF} só com o nome",
        "Resgate de 2025 em diante que não está no sistema (mesmo CPF e pontos, até 7 dias) é debitado; antes de 2025 já "
        "está no saldo congelado; só com o nome fica pendente.",
        "As lojas anotavam resgates no papel; debitar os que já estão no sistema cobraria duas vezes.",
        "Pontos: {a_RESGATE_SO_NA_PLANILHA} pontos debitados; {a_RESGATE_SEM_CPF} pontos pendentes (no mínimo da faixa).",
        ("RESGATE_SO_NA_PLANILHA", "RESGATE_SEM_CPF", "RESGATE_ILEGIVEL"),
    ),
    Problema(
        "Ajustes `AJ` de −1,1 milhão de pontos",
        '`vulto.db:pontos_mov` (tipo AJ, obs "correcao bug app v3.4")',
        "{n_AJUSTE_DO_BUG_SUBSTITUIDO} ajustes do bug; {n_CREDITO_INFLADO_BUG_APP} créditos inflados",
        "Cada crédito inflado (pontos sobre centavos, 08 a 12/06/2026) volta ao valor em reais; os ajustes manuais do bug "
        "saem; os outros 40 ajustes (cortesia, aniversário) ficam.",
        "A correção manual cobriu 18 clientes com o valor exato e esqueceu 12 créditos (+565.711 pontos).",
        "Pontos: {i_CREDITO_INFLADO_BUG_APP} nos créditos e {i_AJUSTE_DO_BUG_SUBSTITUIDO} nos ajustes que saíram.",
        ("AJUSTE_DO_BUG_SUBSTITUIDO", "CREDITO_INFLADO_BUG_APP"),
    ),
    Problema(
        "Valor do ponto: R$ 0,10 × R$ 0,05",
        "`vulto.db:config.valor_ponto` (0,10), README (R$ 10 por 100), aba LEIA ISSO (R$ 5 por 100 desde mar/2025)",
        "Todo o passivo; resgates na planilha dando R$ 0,10 depois de mar/2025",
        "Vigente: R$ 0,05; a faixa vai até R$ 0,10.",
        "A regra mudou em mar/2025, mas o sistema continuou com 0,10 e as lojas também.",
        "Passivo: {pas_vigente} a R$ 0,05; {pas_antigo} a R$ 0,10.",
        ("RESGATE_COM_VALOR_ANTIGO",),
    ),
    Problema(
        "Validade do Ouro: 12 × 18 meses",
        'Aba LEIA ISSO ("combinado com o Diego, ainda não tá no sistema")',
        "48 contas Ouro",
        "Gravado: 18 meses (o combinado, o passivo mais conservador); o passivo mostra os dois.",
        "É o que foi prometido aos clientes Ouro.",
        "Passivo: {pas_dif_ouro} pontos a mais com 18 meses ({pas_ouro12} com 12 × {pas_vigente} com 18, a R$ 0,05).",
    ),
    Problema(
        "Categoria manual × regra",
        "`clientes.xlsx:Clientes.categoria` (BRONZE, brz, Silver, ouro ★, vip?...)",
        "{n_categoria_diverge} contas com a categoria declarada diferente da regra",
        "Vale a regra (pontos do ano: Bronze até 1.999, Prata até 4.999, Ouro 5.000+); a declarada fica guardada.",
        'A própria planilha diz que a categoria "foi colocada na mão, não bate com a regra".',
        "Passivo: muda a validade de quem vira Ouro (18 meses).",
        ("CATEGORIA_DECLARADA_DIVERGE",),
    ),
    Problema(
        "Pontos creditados antes do pagamento aprovado",
        '`/venda` do legado (TODO "só creditar depois que o pagamento aprovar")',
        "{n_CREDITO_ANTES_DO_PAGAMENTO} créditos de vendas aguardando pagamento",
        "Crédito de venda ainda aguardando pagamento sai; venda cancelada sem estorno ganha o estorno.",
        "A regra: ponto só depois do pagamento aprovado; compra cancelada perde os pontos.",
        "Pontos: {i_CREDITO_ANTES_DO_PAGAMENTO}; e {i_CANCELADA_SEM_ESTORNO} de estornos que faltavam "
        "({n_CANCELADA_SEM_ESTORNO} vendas).",
        ("CREDITO_ANTES_DO_PAGAMENTO", "CANCELADA_SEM_ESTORNO", "ESTORNO_DE_CREDITO_QUE_SAIU"),
    ),
    Problema(
        "Atendimentos sem cliente ou pedido identificável",
        "`atendimentos.csv` (contato, pedido)",
        "{n_ATENDIMENTO_SEM_CLIENTE} sem cliente; {n_PEDIDO_NAO_ENCONTRADO} pedidos que não casam",
        "Cliente pelo contato (telefone ou e-mail) ou, sem ele, pelo pedido citado; sem nenhum, `cliente_id` vazio e o "
        "contato guardado. Pedido pela coluna (número do site/app ou id da venda) ou pelo texto.",
        "@ do Instagram e telefone sem DDD não identificam ninguém sozinhos.",
        "{n_CLIENTE_PELO_PEDIDO} atendimentos ganharam o cliente pelo pedido; {n_PEDIDO_DE_OUTRO_CLIENTE} citam pedido de "
        "outro cadastro (provável mesma pessoa).",
        (
            "ATENDIMENTO_SEM_CLIENTE",
            "CLIENTE_PELO_PEDIDO",
            "PEDIDO_NAO_ENCONTRADO",
            "PEDIDO_DE_OUTRO_CLIENTE",
            "PEDIDO_PELO_TEXTO",
            "CONTATO_AMBIGUO",
        ),
    ),  # fmt: skip
    Problema(
        "Senhas em texto puro e `senha_master`",
        "`vulto.db:funcionarios.senha`, `vulto.db:config.senha_master`",
        "{a_SENHA_TEXTO_PURO} funcionários na tabela; 1 senha mestra",
        "Nenhuma senha é copiada (nem para o staging); a senha mestra entra mascarada e não é usada. Os funcionários "
        "entram inativos, sem e-mail e sem senha, e criam a senha pelo convite.",
        "Senha em texto puro e senha mestra são falhas de segurança.",
        "Nenhum número muda; ninguém da Vulto entra sem passar pelo convite.",
        ("SENHA_TEXTO_PURO", "SENHA_MASTER", "SENHAS_NAO_MIGRADAS", "SEM_EMAIL_INATIVOS"),
    ),
)

ALEM_DA_LISTA = (
    Problema(
        "Vendas de teste da TI/QA e duplicatas do app",
        '`vendas` (obs "teste", item TESTE-001, CPF 123.456.789-09; mesmo pedido externo gravado duas vezes)',
        "{n_VENDA_DE_TESTE} de teste; {n_VENDA_DUPLICADA} duplicadas",
        "Ficam de fora (e os pontos delas também).",
        "Não são vendas: são testes e o app enviando o mesmo pedido duas vezes.",
        "Faturamento: {p_testes} (testes) e {p_duplicatas} (duplicatas) na ponte.",
        ("VENDA_DE_TESTE", "VENDA_DUPLICADA", "CREDITO_DE_VENDA_DESCARTADA", "PONTOS_DE_TESTE", "ATENDIMENTO_SPAM"),
    ),
    Problema(
        "Cancelados e vendas aguardando pagamento no relatório da Vulto",
        "`/relatorio/faturamento` do legado (cancelados como TODO)",
        "Ver a ponte",
        "Fora do faturamento: cancelados, estornados e chargebacks; e o que ainda aguarda pagamento.",
        "Não é receita.",
        "Faturamento: {p_cancelados} (cancelados) e {p_aguardando} (aguardando) na ponte.",
    ),
    Problema(
        "Pontos para referência que não é CPF",
        "`pontos_mov.cpf` com telefone ou e-mail",
        "{n_PONTOS_SEM_CPF_VALIDO} movimentos",
        "Saem: pontos só com CPF.",
        'Regra do programa ("telefone/email não vale").',
        "Pontos: {i_PONTOS_SEM_CPF_VALIDO}.",
        ("PONTOS_SEM_CPF_VALIDO", "PONTOS_SEM_CLIENTE"),
    ),
    Problema(
        "Dobro do online e bônus Ouro que o sistema nunca deu",
        '`main.py` do legado (dobrava só "app" e "site" minúsculos; nunca aplicou +50% do Ouro)',
        "Clientes com compras online sem dobro e as contas Ouro",
        "O saldo fica como o cliente via; o que faltou entra só no máximo do passivo.",
        "Creditar agora é uma decisão comercial, não de migração.",
        "Passivo: {pas_dobro} pontos de dobro e {pas_bonus} de bônus ainda válidos (no máximo da faixa).",
        ("ONLINE_SEM_DOBRO", "BONUS_OURO_NUNCA_APLICADO"),
    ),
    Problema(
        "Saldo de pontos negativo",
        "`pontos_mov` (o sistema deixava resgatar mais do que o saldo)",
        "{n_SALDO_FICARIA_NEGATIVO} contas",
        "O saldo para em zero; um ajuste no mesmo instante cobre a diferença e fica registrado.",
        'A regra: "NÃO pode ficar negativo".',
        "Pontos: {a_SALDO_FICARIA_NEGATIVO} pontos cobertos por ajuste.",
        ("SALDO_FICARIA_NEGATIVO",),
    ),
    Problema(
        'Nome "?" ou "Cliente" no atendimento',
        "`atendimentos.csv:nome_contato`",
        "160 cadastros que tinham ficado com esse nome",
        'Texto sem letra e "Cliente" não são nome: o cadastro fica "Cliente Vulto (sem nome)".',
        "Não é o nome da pessoa.",
        "Nenhum número muda.",
    ),
)

DECISOES_DE_REGRA = (
    ("Preço de peça em mais de uma coleção", "Compras: o da coleção mais nova · Operações/Financeiro: o menor (Procon)",
     "O menor", "`src/migracao_vulto/produtos.py: REGRA_PRECO`", "{n_PRECO_ENTRE_COLECOES} peças; {i_PRECO_ENTRE_COLECOES}"),
    ("Custo da peça", "Compras: o último · Financeiro: o médio", "Guardar os dois",
     "`variacoes.preco_custo`, `variacoes.custo_medio`", "Margem bruta conforme o custo escolhido"),
    ("Frete", "Receita × repasse", "Faturamento sem frete (como a Casa Lorenzi); o frete aparece separado",
     "`src/use_cases/diretoria.py` (ponte) · `faturamento_repository`", "{p_frete}"),
    ("Status vazio", "Pago × pendente", "Pago", "`src/migracao_vulto/vendas.py: STATUS_VAZIO`", "{vazio_valor} (margem)"),
    ("Canal da venda", "Texto do canal × loja da venda", "A loja", "`normalizacao.CANAL_POR_LOJA_LEGADO`",
     "{n_CANAL_TEXTO_DIVERGE} vendas mudam de canal"),
    ("Troca", "Venda nova × troca", "Pedido TROCA: baixa o estoque, fora da receita",
     "`src/entities/pedido.py: TIPOS_SEM_RECEITA`", "{p_trocas}"),
    ("Valor do ponto", "config 0,10 · README R$ 10/100 · LEIA ISSO R$ 5/100 desde mar/2025", "R$ 0,05 (faixa até R$ 0,10)",
     "`src/entities/fidelidade.py: VALOR_PONTO_VIGENTE`", "{pas_vigente} × {pas_antigo}"),
    ("Validade do Ouro", "Sistema: 12 meses · Combinado com o Diego: 18", "18 gravado; o passivo mostra os dois",
     "`src/entities/fidelidade.py: VALIDADE_OURO_GRAVADA`", "{pas_dif_ouro} pontos"),
    ("Categoria do Vulto+", "Planilha (à mão) × regra dos pontos do ano", "A regra; a declarada fica guardada",
     "`src/entities/fidelidade.py: FAIXAS_CATEGORIA`", "{n_categoria_diverge} contas"),
    ("Ponto antes do pagamento", "Sistema: na hora · Regra: depois do pagamento", "Depois do pagamento",
     "`src/migracao_vulto/fidelidade.py`", "{i_CREDITO_ANTES_DO_PAGAMENTO}"),
    ("Dobro do online e bônus Ouro não aplicados", "Regra × o que o sistema creditou",
     "Saldo como o cliente via; no máximo da faixa", "`src/migracao_vulto/fidelidade.py`", "{pas_dobro} + {pas_bonus} pontos"),
    ("Data da contagem sem data", "A planilha não diz", "30/09/2026 (estimada)", "`src/migracao_vulto/estoque.py: CONTAGENS`",
     "Eldorado, Savassi e Batel"),
    ("Abertura do estoque (01/01/2025)", "Desconhecida", "A menor que deixa o histórico sem negativo",
     "`src/migracao_vulto/estoque.py`", "{a_ABERTURA_ESTIMADA} peças"),
    ("Clientes duplicados", "Por qual identificador juntar", "CPF → e-mail → telefone, sem juntar CPFs diferentes",
     "`src/migracao_vulto/clientes.py: agrupar`", "{n_CADASTROS_FUNDIDOS} cadastros fundidos"),
    ("Atendimento sem cliente", "Anulável × cliente genérico", "`cliente_id` anulável, contato guardado",
     "`atendimentos.cliente_id`", "{n_ATENDIMENTO_SEM_CLIENTE} atendimentos"),
    ("Janela de um atendimento", "Linhas do mesmo contato e assunto", "72 horas", "`src/migracao_vulto/atendimento.py: JANELA`",
     "Nenhuma junção nesta carga"),
    ("Funcionários da Vulto", "Migrar senha × convite", "Inativos, sem e-mail e sem senha; convite depois",
     "`src/migracao_vulto/usuarios.py`", "Todos os funcionários migrados"),
)  # fmt: skip

LIMITACOES = (
    ("Troca não registra a peça devolvida", "A peça que volta numa troca não entra no histórico; o ajuste da contagem a absorve.",
     "Dentro do ajuste da contagem ({i_CONTAGEM_DIFERE_DO_RECONSTRUIDO})"),
    ("Contagem da Batel incompleta", "{n_BATEL_CONTAGEM_INCOMPLETA} linhas \"faltou contar provador\"/\"recontar\": o contado "
     "pode estar abaixo do real.", "Sem quantidade anotada"),
    ("Data real dos pontos congelados", "Os pontos de antes de 2025 são tratados como ganhos em 01/01/2025 (a hipótese mais "
     "generosa): venceram em 01/01/2026 (Ouro: 01/07/2026) quando não usados.", "Sem dado para estimar"),
    ("Vendas com status vazio", "Lidas como pagas.", "Até {vazio_valor} a menos no faturamento"),
    ("Planilha manual da Batel", "Anotada à mão com o PDV fora do ar; uma venda Pix pode ter ficado de fora (Plan2).",
     "Até {batel_valor} a menos"),
    ("Mesma pessoa em dois cadastros", "Sem CPF, cadastros pelo WhatsApp e pelo e-mail da compra não são fundidos.",
     "{n_PEDIDO_DE_OUTRO_CLIENTE} atendimentos citam pedido de outro cadastro"),
    ("Emojis do atendimento", "Chegaram como \"?\" no CSV: a perda é anterior à migração.", "Só texto"),
    ("Vulto+ depois da virada", "A plataforma ainda não credita, resgata nem vence pontos: o saldo é o de 01/10/2026.",
     "Vencimentos depois de 01/10/2026 não aplicados"),
    ("Lojas sem endereço", "O legado só tem nome e cidade das lojas.", "{n_LOJA_SEM_ENDERECO} lojas para completar"),
)  # fmt: skip


# ---------- O documento ----------


def _linha(*celulas: str) -> str:
    return "| " + " | ".join(celula.replace("|", "\\|").replace("\n", " ") for celula in celulas) + " |"


CABECALHO_PROBLEMAS = _linha(
    "#", "O que encontramos", "Onde (arquivo / tabela / campo)", "Quantos registros afeta", "O que decidimos fazer", "Por quê",
    "Impacto no número final",
)  # fmt: skip


def gerar(db: Session) -> str:
    numeros = Numeros(db)
    f = lambda texto: texto.format_map(numeros)  # noqa: E731
    fat, est, pas = numeros.dados["faturamento"], numeros.dados["estoque"], numeros.dados["passivo"]
    partes = [
        "# Registro de Decisões — Migração Vulto → Casa Lorenzi",
        "",
        "Cada problema encontrado nos dados ou nas regras da Vulto, o que decidimos e quanto isso muda o número final.",
        "Gerado por `python -m src.relatorios.registro_decisoes` a partir da tabela `migracao_ocorrencias` (cada",
        "registro problemático da migração tem uma ocorrência) e dos números da diretoria; não edite à mão.",
        "",
        "## Os três números",
        "",
        f"- **Faturamento da Vulto (jan/2025 a set/2026):** {fat['resposta']} Margem: {f('{fat_min}')} a {f('{fat_max}')}.",
        f"- **Estoque em 01/10/2026:** {est['resposta']} Margem: {f('{est_min}')} a {f('{est_max}')} peças.",
        f"- **Passivo do Vulto+ em 01/10/2026:** {pas['resposta']}",
        "",
        "## Problemas nos dados",
        "",
        "Fizemos X por causa de Y, e isso muda o número em Z: cada linha diz o que encontramos, onde, quantos registros",
        "afeta, o que decidimos, por quê e o impacto. Os códigos entre colchetes levam ao apêndice.",
        "",
        CABECALHO_PROBLEMAS,
        _linha(*["---"] * 7),
    ]
    cobertos: set[str] = set()
    for i, problema in enumerate(PROBLEMAS + ALEM_DA_LISTA, start=1):
        if i == len(PROBLEMAS) + 1:
            partes += ["", "### Encontrados além da lista", "", CABECALHO_PROBLEMAS, _linha(*["---"] * 7)]
        codigos = f" [{', '.join(f'`{c}`' for c in problema.codigos)}]" if problema.codigos else ""
        cobertos.update(problema.codigos)
        partes.append(
            _linha(
                str(i),
                problema.titulo + codigos,
                problema.onde,
                f(problema.registros),
                problema.decisao,
                problema.porque,
                f(problema.impacto),
            )  # fmt: skip
        )
    partes += [
        "",
        "## Decisões de regra (conflitos entre áreas)",
        "",
        _linha("#", "Regra em conflito", "Quem diz o quê", "O que decidimos (default)", "Onde fica o parâmetro", "Impacto"),
        _linha(*["---"] * 6),
    ]
    partes += [_linha(str(i), regra, quem, decisao, onde, f(impacto)) for i, (regra, quem, decisao, onde, impacto)
               in enumerate(DECISOES_DE_REGRA, start=1)]  # fmt: skip
    partes += [
        "",
        "## Limitações conhecidas",
        "",
        "O que não dá para recuperar com os dados entregues e como isso afeta os números.",
        "",
        _linha("#", "Limitação", "Consequência", "Margem de erro"),
        _linha(*["---"] * 4),
    ]
    partes += [_linha(str(i), lim, f(cons), f(margem)) for i, (lim, cons, margem) in enumerate(LIMITACOES, start=1)]

    por_dominio: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for codigo, ocorrencia in numeros.ocorrencias.items():
        por_dominio[ocorrencia["dominio"]].append((codigo, ocorrencia))
    partes += [
        "",
        "## Apêndice: todas as ocorrências da migração",
        "",
        f"{len(numeros.ocorrencias)} tipos de ocorrência, {milhar(sum(o['registros'] for o in numeros.ocorrencias.values()))} "
        "registros. Ação: CORRIGIDO (entrou com valor ajustado), DESCARTADO (não entrou), ESTIMADO (entrou com estimativa), "
        "MANTIDO (entrou como veio, com o aviso), PENDENTE (precisa de alguém).",
    ]
    for dominio in sorted(por_dominio):
        partes += ["", f"### {dominio}", "", _linha("Código", "Ação", "Registros", "Impacto", "Origem", "Exemplo"),
                   _linha(*["---"] * 6)]  # fmt: skip
        for codigo, o in sorted(por_dominio[dominio], key=lambda item: -item[1]["registros"]):
            marca = "" if codigo in cobertos else " ·"
            partes.append(
                _linha(
                    f"`{codigo}`{marca}",
                    o["acao"],
                    milhar(o["registros"]),
                    numeros.impacto(codigo),
                    o["origem"] or "",
                    (o["descricao"] or "")[:180],
                )  # fmt: skip
            )
    partes += ["", "· ocorrência sem linha própria nas tabelas acima (detalhe da migração).", ""]
    return "\n".join(partes)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera o registro de decisões da migração da Vulto.")
    parser.add_argument("--saida", default="docs/registro_decisoes.md")
    saida = Path(parser.parse_args().saida)
    with SessionLocal() as db:
        saida.write_text(gerar(db), encoding="utf-8")
    print(saida)


if __name__ == "__main__":
    main()
