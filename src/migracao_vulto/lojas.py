"""Domínio lojas: as lojas da Vulto (tabela lojas do vulto.db) entram como lojas da marca VULTO.

- 1 a 4 (Pinheiros, Eldorado, Savassi, Batel) são lojas físicas; 7 é o CD Cajamar.
- 5 (E-commerce) e 6 (App) não viram lojas: são canais. O estoque do site e do app é físico no CD,
  então os pedidos online saem do CD Cajamar (ou de Pinheiros, no ship from store).

O legado não tem UF, endereço, telefone nem horários: a UF vem da cidade e o resto fica para a
equipe completar na central administrativa (ocorrência PENDENTE).
"""

from sqlalchemy.orm import Session

from src import models as m
from src.entities.marca import VULTO
from src.entities.pedido import CANAL_APP, CANAL_SITE
from src.migracao_vulto.relatorio import Resultado
from src.repositories import cadastro_repository, migracao_repository

DOMINIO = "lojas"
ORIGEM = "vulto.db:lojas"

# id no legado → (nome, cidade, UF, tipo)
LOJAS = {
    1: ("Vulto Pinheiros", "São Paulo", "SP", "FISICA"),
    2: ("Vulto Shopping Eldorado", "São Paulo", "SP", "FISICA"),
    3: ("Vulto Savassi", "Belo Horizonte", "MG", "FISICA"),
    4: ("Vulto Batel", "Curitiba", "PR", "FISICA"),
    7: ("CD Cajamar", "Cajamar", "SP", "CD"),
}
# Lojas virtuais do legado → canal dos pedidos
CANAL_DA_LOJA_VIRTUAL = {5: (CANAL_SITE, "Vulto E-commerce"), 6: (CANAL_APP, "Vulto App")}
ID_LEGADO_CD = 7
ID_LEGADO_PINHEIROS = 1


def loja_da_vulto(db: Session, id_legado: int) -> m.Loja | None:
    """Loja da plataforma que corresponde à loja do legado (None para 5 e 6, que são canais)."""
    loja_id = migracao_repository.destino(db, ORIGEM, str(id_legado), "lojas")
    return cadastro_repository.loja(db, loja_id) if loja_id else None


def migrar(db: Session) -> Resultado:
    """Cadastra (ou atualiza) as lojas da Vulto, sem confirmar. Pode rodar quantas vezes precisar."""
    resultado = Resultado(DOMINIO, lidos=len(LOJAS) + len(CANAL_DA_LOJA_VIRTUAL))
    migracao_repository.limpar_ocorrencias(db, DOMINIO)

    for id_legado, (nome, cidade, uf, tipo) in LOJAS.items():
        loja = loja_da_vulto(db, id_legado) or cadastro_repository.loja_por_nome(db, nome)
        if loja is None:
            loja = m.Loja(nome=nome, cidade=cidade, uf=uf, endereco="", telefone="", horarios=[], ativa=True)
            db.add(loja)
        elif loja.marca != VULTO:
            raise RuntimeError(f"Já existe uma loja da Casa Lorenzi chamada {nome!r}: a migração não mexe nela.")
        loja.nome, loja.cidade, loja.uf, loja.marca, loja.tipo = nome, cidade, uf, VULTO, tipo
        db.flush()
        migracao_repository.vincular(db, ORIGEM, str(id_legado), "lojas", loja.id)
        resultado.carregados += 1
        if not loja.endereco:
            migracao_repository.registrar_ocorrencia(
                db,
                codigo_problema="LOJA_SEM_ENDERECO",
                dominio=DOMINIO,
                origem=ORIGEM,
                id_origem=str(id_legado),
                descricao="O legado só tem nome e cidade: UF deduzida da cidade; endereço, telefone e "
                "horários ficam para a equipe completar na central administrativa.",
                acao_tomada="PENDENTE",
                valor_original=f"{nome} · {cidade}",
                valor_final=f"{nome} · {cidade}/{uf}",
            )

    for id_legado, (canal, nome) in CANAL_DA_LOJA_VIRTUAL.items():
        migracao_repository.registrar_ocorrencia(
            db,
            codigo_problema="LOJA_VIRTUAL_VIRA_CANAL",
            dominio=DOMINIO,
            origem=ORIGEM,
            id_origem=str(id_legado),
            descricao=f"{nome} não vira loja: é o canal {canal}. O estoque online é físico no CD Cajamar, "
            "de onde os pedidos saem (ou de Pinheiros, no ship from store).",
            acao_tomada="CORRIGIDO",
            valor_original=f"loja {id_legado} · {nome}",
            valor_final=f"canal {canal} · expedição CD Cajamar",
        )
        resultado.corrigidos += 1

    db.flush()
    resultado.ocorrencias = migracao_repository.ocorrencias_por_acao(db, DOMINIO)
    return resultado
