"""Domínio usuarios: os funcionários da Vulto (e os atendentes do SAC) viram usuários da plataforma.

Decisões aprovadas:
- Ninguém entra com senha: as senhas do legado estão em texto puro e não migram (nem a senha_master).
  Os funcionários vieram sem e-mail, então entram inativos; um administrador cadastra o e-mail, reativa e
  manda o convite (o fluxo que já existe).
- Papel: vendedor e gerente → LOJISTA da loja; operador do CD → OPERADOR; admin (Diego, Paula, Marina) →
  ADMINISTRADOR.
- Ficam de fora as contas de teste e as genéricas sem dono ("TESTE TI", "admin", "Estagiário loja").
- Os atendentes do SAC (Marcos, Júlia, Renata), que não estão na tabela de funcionários, viram LOJISTA do
  CD Cajamar (a operação online), também inativos. "time insta" (conta compartilhada) e o bot não viram
  usuário: ficam só no texto do atendimento.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from src import models as m
from src.entities.papeis import ADMINISTRADOR, LOJISTA, OPERADOR
from src.migracao_vulto import lojas
from src.migracao_vulto.relatorio import Resultado
from src.repositories import migracao_repository
from src.utils.datas import agora

DOMINIO = "usuarios"
ORIGEM_FUNCIONARIOS = "vulto.db:funcionarios"
ORIGEM_ATENDENTES = "atendimentos.csv:atendente"

PAPEL_POR_PERFIL = {"vendedor": LOJISTA, "gerente": LOJISTA, "operador": OPERADOR, "admin": ADMINISTRADOR}
# Contas de teste e genéricas, sem uma pessoa por trás (código no legado)
CONTAS_DESCARTADAS = {"9999": "conta de teste da TI", "admin": "conta genérica de administrador", "estagio": "conta genérica"}
# Contas de função (o nome não é de uma pessoa): migram, mas o nome precisa ser trocado pelo de quem usa
CONTAS_DE_FUNCAO = {"BAT-G", "CD01"}

# Grafias do atendente no CSV → atendente do SAC (None: não vira usuário)
ATENDENTES_SAC = {
    "Marcos (SAC)": ("Marcos SAC",),
    "Júlia (SAC)": ("julia", "Júlia (SAC)"),
    "Renata (SAC)": ("Renata", "renata.sac"),
}
ATENDENTE_POR_GRAFIA = {grafia.lower(): nome for nome, grafias in ATENDENTES_SAC.items() for grafia in grafias}
SEM_USUARIO = {"bot": "bot", "bot vulto": "bot", "time insta": "conta compartilhada do Instagram"}


def atendente(grafia: str | None) -> str | None:
    """Atendente do SAC pela grafia do CSV ("julia" → "Júlia (SAC)"); None para bot e conta compartilhada."""
    return ATENDENTE_POR_GRAFIA.get((grafia or "").strip().lower())


def usuario_do_atendente(db: Session, grafia: str | None) -> int | None:
    nome = atendente(grafia)
    return migracao_repository.destino(db, ORIGEM_ATENDENTES, nome, "usuarios") if nome else None


def _gravar(db: Session, origem: str, id_origem: str, campos: dict) -> bool:
    """Cria o usuário inativo, sem e-mail e sem senha, se ainda não migrou (pelo de_para). Já migrado, não
    mexe: um administrador pode ter corrigido o nome, cadastrado o e-mail e reativado. True se criou."""
    if migracao_repository.destino(db, origem, id_origem, "usuarios"):
        return False
    usuario = m.Usuario(**campos, email=None, senha_hash=None, ativo=False, criado_em=agora())
    db.add(usuario)
    db.flush()
    migracao_repository.vincular(db, origem, id_origem, "usuarios", usuario.id)
    return True


def migrar(db: Session) -> Resultado:
    resultado = Resultado(DOMINIO)
    migracao_repository.limpar_ocorrencias(db, DOMINIO)

    def ocorrencia(codigo, origem, descricao, acao, id_origem=None, original=None, final=None):
        migracao_repository.registrar_ocorrencia(
            db, codigo_problema=codigo, dominio=DOMINIO, origem=origem, id_origem=id_origem, descricao=descricao,
            acao_tomada=acao, valor_original=original, valor_final=final,
        )  # fmt: skip

    linhas = db.execute(
        text(
            "SELECT id, codigo, nome, loja_id, perfil, ativo, _senha_preenchida FROM legado_vulto.db__funcionarios "
            "ORDER BY id::int"
        )
    ).all()
    resultado.lidos = len(linhas)
    cd = lojas.loja_da_vulto(db, lojas.ID_LEGADO_CD)
    codigos: dict[str, list[str]] = {}
    com_senha = 0
    for fid, codigo, nome, loja_id, perfil, ativo, senha in linhas:
        com_senha += senha == "1"
        if codigo in CONTAS_DESCARTADAS:
            motivo = CONTAS_DESCARTADAS[codigo].capitalize()
            ocorrencia("FUNCIONARIO_DESCARTADO", ORIGEM_FUNCIONARIOS, f"{motivo}: não vira usuário.", "DESCARTADO", fid,
                       f"{codigo} · {nome}")  # fmt: skip
            resultado.descartados += 1
            continue
        papel = PAPEL_POR_PERFIL[perfil]
        loja = None if papel == ADMINISTRADOR else lojas.loja_da_vulto(db, int(loja_id)) if loja_id else cd
        if _gravar(db, ORIGEM_FUNCIONARIOS, fid, {"nome": nome.strip(), "papel": papel, "loja_id": loja.id if loja else None}):
            resultado.carregados += 1
        codigos.setdefault(codigo, []).append(nome)
        if codigo in CONTAS_DE_FUNCAO:
            ocorrencia("CONTA_DE_FUNCAO", ORIGEM_FUNCIONARIOS, "Conta com o nome da função, não de uma pessoa: migrada "
                       "inativa; troque pelo nome de quem usa ao cadastrar o e-mail.", "PENDENTE", fid, nome)  # fmt: skip
        if ativo != "1":
            ocorrencia("FUNCIONARIO_INATIVO_NO_LEGADO", ORIGEM_FUNCIONARIOS, "Já estava inativo na Vulto.", "MANTIDO", fid, nome)
    for codigo, nomes in codigos.items():
        if len(nomes) > 1:
            ocorrencia("CODIGO_REPETIDO", ORIGEM_FUNCIONARIOS, f"O mesmo código de vendedor para {len(nomes)} pessoas: as "
                       "vendas com esse código não dizem quem vendeu. Todas viram usuário.", "MANTIDO", codigo,
                       " · ".join(nomes))  # fmt: skip

    for nome in ATENDENTES_SAC:
        resultado.lidos += 1
        if _gravar(db, ORIGEM_ATENDENTES, nome, {"nome": nome, "papel": LOJISTA, "loja_id": cd.id}):
            resultado.carregados += 1
    ocorrencia("ATENDENTES_SEM_USUARIO", ORIGEM_ATENDENTES, '"time insta" (conta compartilhada) e o bot não viram usuário: o '
               "atendimento fica sem responsável e o nome fica no texto.", "MANTIDO")  # fmt: skip
    ocorrencia("SEM_EMAIL_INATIVOS", ORIGEM_FUNCIONARIOS, "Os funcionários da Vulto não têm e-mail: entram inativos e sem senha. "
               "Para dar acesso, um administrador cadastra o e-mail, reativa e manda o convite.", "MANTIDO")  # fmt: skip
    ocorrencia("SENHAS_NAO_MIGRADAS", ORIGEM_FUNCIONARIOS, f"{com_senha} senhas em texto puro (e a senha_master do config) não "
               "migram: cada pessoa cria a sua pelo convite.", "DESCARTADO")  # fmt: skip

    resultado.ocorrencias = migracao_repository.ocorrencias_por_acao(db, DOMINIO)
    total = len(linhas) - resultado.descartados + len(ATENDENTES_SAC)
    resultado.notas = [f"usuários da Vulto: {total} (todos inativos, sem e-mail e sem senha)"]
    return resultado
