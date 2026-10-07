"""Frete configurável (Administração > Frete): valor cobrado, custo para a loja e prazo por região
do CEP, mínimo para o frete grátis e se o Expresso está disponível.

O site recebe só valores e prazos (`condicoes`); o custo é do Administrador. O checkout usa
`opcao_para` e guarda no pedido o custo do dia da compra."""

from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from src import models as m
from src.entities.frete import FRETE_INICIAL, ROTULOS, TIPOS, OpcaoFrete, opcoes_de_frete, regiao_do_cep
from src.repositories import frete_repository, sessao
from src.use_cases import log_acoes
from src.utils.erros import DadosInvalidos
from src.utils.texto import moeda

_CAMPOS = (("valor", "valor"), ("custo", "custo"), ("prazo_dias", "prazoDias"))


def _config(db: Session, travar: bool = False) -> m.ConfigFrete:
    config = frete_repository.config(db, travar=travar)
    if config is None:  # banco sem a linha de configuração: parte da inicial
        config = m.ConfigFrete(id=1, gratis_minimo=FRETE_INICIAL["gratis_minimo"], expresso_ativo=FRETE_INICIAL["expresso_ativo"])
        sessao.adicionar(db, config)
    return config


def _faixa(regiao: m.FreteRegiao, tipo: str, com_custo: bool) -> dict:
    prefixo = tipo.lower()
    faixa = {"valor": float(getattr(regiao, f"{prefixo}_valor")), "prazoDias": getattr(regiao, f"{prefixo}_prazo_dias")}
    if com_custo:
        faixa["custo"] = float(getattr(regiao, f"{prefixo}_custo"))
    return faixa


def _saida(db: Session, com_custo: bool) -> dict:
    config = _config(db)
    return {
        "gratisMinimo": float(config.gratis_minimo),
        "expressoAtivo": config.expresso_ativo,
        "regioes": [
            {
                "regiao": r.regiao,
                "nome": r.nome,
                "padrao": _faixa(r, "PADRAO", com_custo),
                "expresso": _faixa(r, "EXPRESSO", com_custo),
            }
            for r in frete_repository.regioes(db)
        ],
    }


def condicoes(db: Session) -> dict:
    """Público (site): valores cobrados e prazos, sem o custo da loja."""
    return _saida(db, com_custo=False)


def config_completa(db: Session) -> dict:
    """Administrador: a mesma estrutura, com o custo de cada faixa."""
    return _saida(db, com_custo=True)


def opcoes(db: Session, cep: str | None, subtotal: Decimal) -> list[OpcaoFrete]:
    """Opções para o CEP e o subtotal; [] se o CEP não é atendido."""
    codigo = regiao_do_cep(cep)
    regiao = frete_repository.regiao(db, codigo) if codigo else None
    if regiao is None:
        return []
    config = _config(db)
    return opcoes_de_frete(regiao, subtotal, config.gratis_minimo, config.expresso_ativo)


def opcao_para(db: Session, cep: str | None, subtotal: Decimal, tipo: str | None) -> OpcaoFrete | None:
    return next((o for o in opcoes(db, cep, subtotal) if o.tipo == tipo), None)


def simular(db: Session, cep: str | None, subtotal) -> list[dict]:
    """Administrador: o que o cliente pagaria, o custo e o resultado (valor − custo) para a loja."""
    try:
        valor = Decimal(str(subtotal or 0))
    except InvalidOperation:
        valor = Decimal("0")
    return [
        {
            "tipo": o.tipo,
            "label": ROTULOS[o.tipo],
            "valor": float(o.valor),
            "custo": float(o.custo),
            "prazoDias": o.prazo_dias,
            "resultado": float(o.valor - o.custo),
        }
        for o in opcoes(db, cep, valor)
    ]


def _decimal(valor, mensagem: str) -> Decimal:
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        raise DadosInvalidos(mensagem) from None
    if not numero.is_finite() or numero < 0:
        raise DadosInvalidos(mensagem)
    return numero.quantize(Decimal("0.01"))


def _prazo(valor, mensagem: str) -> int:
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        raise DadosInvalidos(mensagem) from None
    if not numero.is_finite() or numero != numero.to_integral_value() or numero <= 0:
        raise DadosInvalidos(mensagem)
    return int(numero)


def salvar(db: Session, usuario: m.Usuario, dados: dict) -> dict:
    """{ gratisMinimo, expressoAtivo, regioes: [{ regiao, padrao: { valor, custo, prazoDias }, expresso }] }.
    Valida tudo antes de gravar e registra no log cada valor que mudou."""
    gratis_minimo = _decimal(dados.get("gratisMinimo"), "Informe um valor mínimo válido para o frete grátis.")
    expresso_ativo = bool(dados.get("expressoAtivo"))
    existentes = {r.regiao: r for r in frete_repository.regioes(db)}

    novos: list[tuple[m.FreteRegiao, dict]] = []
    for entrada in dados.get("regioes") or []:
        regiao = existentes.get((entrada or {}).get("regiao"))
        if regiao is None:
            raise DadosInvalidos("Região de frete desconhecida.")
        campos = {}
        for tipo in TIPOS:
            rotulo = f"{regiao.nome} · {ROTULOS[tipo]}"
            faixa = entrada.get(tipo.lower()) or {}
            mensagem = f"{rotulo}: informe valor e custo válidos."
            campos[f"{tipo.lower()}_valor"] = _decimal(faixa.get("valor"), mensagem)
            campos[f"{tipo.lower()}_custo"] = _decimal(faixa.get("custo"), mensagem)
            campos[f"{tipo.lower()}_prazo_dias"] = _prazo(
                faixa.get("prazoDias"), f"{rotulo}: o prazo deve ser um número inteiro de dias."
            )
        novos.append((regiao, campos))

    config = _config(db, travar=True)
    alteracoes = []

    def anotar(campo: str, de, para, formato=str) -> None:
        if de != para:
            alteracoes.append({"campo": campo, "de": formato(de), "para": formato(para)})

    anotar("Frete grátis a partir de", config.gratis_minimo, gratis_minimo, moeda)
    anotar("Expresso disponível", config.expresso_ativo, expresso_ativo, lambda v: "Sim" if v else "Não")
    for regiao, campos in novos:
        for tipo in TIPOS:
            prefixo = f"{regiao.nome} · {ROTULOS[tipo]}"
            for atributo, rotulo, formato in (
                ("valor", "valor", moeda),
                ("custo", "custo", moeda),
                ("prazo_dias", "prazo", lambda v: f"{v} dias"),
            ):
                nome = f"{tipo.lower()}_{atributo}"
                anotar(f"{prefixo} · {rotulo}", getattr(regiao, nome), campos[nome], formato)
                setattr(regiao, nome, campos[nome])

    config.gratis_minimo = gratis_minimo
    config.expresso_ativo = expresso_ativo
    if alteracoes:
        quantidade = len(alteracoes)
        log_acoes.registrar(
            db,
            usuario,
            "FRETE",
            "EDITOU",
            f"Alterou a configuração de frete ({quantidade} {'valor' if quantidade == 1 else 'valores'})",
            alteracoes,
        )
    sessao.confirmar(db)
    return config_completa(db)
