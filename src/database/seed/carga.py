"""Popula o banco com os dados de demonstração.

Uso:
    python -m src.database.seed            # só popula se o banco estiver vazio
    python -m src.database.seed --recriar  # apaga todos os dados e popula de novo

Todas as contas da equipe usam a senha "lorenzi2026" e todos os clientes o PIN "1234".
As datas são relativas ao momento da carga.
"""

import argparse
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import Base, SessionLocal
from src.database.seed.dados import (
    CATEGORIAS,
    CLIENTES,
    DETALHES_PRODUTOS,
    LOJAS,
    PIN_DEMO,
    PRODUTOS,
    SENHA_DEMO,
    TIPOS_SOLICITACAO,
    USUARIOS,
)
from src.database.seed.gerador import Relogio, montar_atendimentos, montar_estoque, montar_pedidos, montar_variacoes
from src.entities.pagamento import PARCELAS_MAX, status_inicial
from src.utils.datas import de_ms
from src.utils.seguranca import gerar_hash

# ---------------------------------------------------------------------------
# Gravação no banco
# ---------------------------------------------------------------------------


def _ajustar_sequencias(db: Session) -> None:
    """Depois de inserir ids explícitos, o próximo id gerado pelo PostgreSQL precisa vir depois deles."""
    if db.get_bind().dialect.name != "postgresql":
        return
    for tabela in Base.metadata.sorted_tables:
        db.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{tabela.name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {tabela.name}), 0) + 1, false)"
            )
        )


def _pagamento(pedido: dict) -> tuple[str, int]:
    """(método, parcelas) de demonstração, variando de forma determinística pelo id do pedido."""
    pid = pedido["id"]
    if pedido["canal"] == "E-commerce":
        return ("PIX", 1) if pid % 3 == 0 else ("CARTAO", 1 + pid % PARCELAS_MAX)
    metodo = ("CARTAO", "DEBITO", "PIX", "DINHEIRO")[pid % 4]
    return metodo, (1 + pid % 3) if metodo == "CARTAO" else 1


def apagar_tudo(db: Session) -> None:
    for tabela in reversed(Base.metadata.sorted_tables):
        db.execute(tabela.delete())


def popular(db: Session) -> None:
    relogio = Relogio()
    senha = gerar_hash(SENHA_DEMO)
    pin = gerar_hash(PIN_DEMO)  # um hash só para todos: bcrypt é lento de propósito
    variacoes = montar_variacoes()
    estoques, movimentacoes, transferencias = montar_estoque(relogio, variacoes)
    pedidos = montar_pedidos(relogio, variacoes)
    atendimentos, mensagens = montar_atendimentos(relogio, pedidos, variacoes)

    db.add_all(m.Loja(id=i, nome=n, cidade=c, uf=uf) for i, n, c, uf in LOJAS)
    db.add_all(m.Categoria(id=i, nome=nome) for i, nome in enumerate(CATEGORIAS, start=1))
    db.flush()
    db.add_all(m.Usuario(id=i, nome=n, email=e, papel=p, loja_id=loja, senha_hash=senha) for i, n, e, p, loja in USUARIOS)
    db.add_all(
        m.Cliente(
            id=i,
            nome=n,
            email=e.lower(),
            telefone=tel,
            pin_hash=pin,
            tentativas_pin=0,
            cliente_desde=date.fromisoformat(desde),
            loja_preferida_id=loja,
        )
        for i, n, e, tel, desde, loja in CLIENTES
    )
    categoria_id = {nome: i for i, nome in enumerate(CATEGORIAS, start=1)}
    db.add_all(
        m.Produto(
            id=p["id"],
            nome=p["nome"],
            categoria_id=categoria_id[p["categoria"]],
            preco_base=p["preco"],
            genero=p["genero"],
            estacao=p["estacao"],
            ativo=p.get("ativo", True),
            **DETALHES_PRODUTOS.get(p["id"], {}),
        )
        for p in PRODUTOS
    )
    db.flush()
    db.add_all(m.Variacao(**v) for v in variacoes)
    db.add_all(
        m.TipoSolicitacao(
            id=i, titulo=t, categoria=c, exige_venda=ev, ordem_exibicao=o, descricao=d, conta_pos_venda=pv, ativo=True
        )
        for i, t, c, ev, o, d, pv in TIPOS_SOLICITACAO
    )
    db.flush()
    db.add_all(
        m.Estoque(
            id=e["id"],
            loja_id=e["loja_id"],
            variacao_id=e["variacao_id"],
            quantidade=e["quantidade"],
            quantidade_min=e["minimo"],
            atualizado_em=de_ms(e["atualizado"]),
        )
        for e in estoques
    )
    db.add_all(
        m.Transferencia(
            id=t["id"],
            codigo=t["codigo"],
            variacao_id=t["variacao_id"],
            loja_origem_id=t["loja_origem_id"],
            loja_destino_id=t["loja_destino_id"],
            quantidade=t["quantidade"],
            status=t["status"],
            solicitante_id=t["solicitante_id"],
            responsavel_id=t["responsavel_id"],
            observacao=t["observacao"],
            criado_em=de_ms(t["criado"]),
            enviado_em=t["enviado"] and de_ms(t["enviado"]),
            recebido_em=t["recebido"] and de_ms(t["recebido"]),
        )
        for t in transferencias
    )
    db.flush()
    db.add_all(
        m.Movimentacao(
            id=mv["id"],
            estoque_id=mv["estoque_id"],
            tipo=mv["tipo"],
            quantidade=mv["quantidade"],
            origem=mv["origem"],
            usuario_id=mv["usuario_id"],
            transferencia_id=mv.get("transferencia_id"),
            saldo_resultante=mv["saldo"],
            criado_em=de_ms(mv["criado"]),
        )
        for mv in movimentacoes
    )
    for p in pedidos:
        metodo, parcelas = _pagamento(p)
        criado = de_ms(p["criado"])
        db.add(
            m.Pedido(
                id=p["id"],
                numero=p["numero"],
                cliente_id=p["cliente_id"],
                loja_id=p["loja_id"],
                canal=p["canal"],
                status=p["status"],
                codigo_rastreio=p["rastreio"],
                # Os pedidos de demonstração não têm frete nem endereço (iguais aos mocks do frontend)
                subtotal=p["total"],
                total=p["total"],
                criado_em=criado,
                itens=[
                    m.ItemPedido(variacao_id=it["variacao_id"], quantidade=it["quantidade"], preco_unitario=it["preco"])
                    for it in p["itens"]
                ],
                pagamentos=[
                    m.Pagamento(
                        metodo=metodo,
                        valor=p["total"],
                        parcelas=parcelas,
                        status=status_inicial(p["status"]),
                        criado_em=criado,
                        atualizado_em=criado,
                    )
                ],
            )
        )
    db.flush()
    db.add_all(
        m.Atendimento(
            id=a["id"],
            protocolo=a["protocolo"],
            cliente_id=a["solicitante_id"],
            responsavel_id=a["responsavel_id"],
            tipo_solicitacao_id=a["tipo_id"],
            status=a["status"],
            pedido_id=a["pedido_id"],
            loja_id=a["loja_id"],
            criado_em=de_ms(a["criado"]),
            atualizado_em=de_ms(a["atualizado"]),
        )
        for a in atendimentos
    )
    db.flush()
    db.add_all(
        m.Mensagem(
            id=x["id"],
            atendimento_id=x["atendimento_id"],
            # autor_id só aponta para a equipe; mensagens do cliente ficam sem autor
            autor_id=None if x["autor_tipo"] == "CLIENTE" else x["autor_id"],
            autor_tipo=x["autor_tipo"],
            conteudo=x["conteudo"],
            enviado_em=de_ms(x["enviado"]),
        )
        for x in mensagens
    )
    db.flush()
    _ajustar_sequencias(db)


def main() -> None:
    parser = argparse.ArgumentParser(description="Popula o banco com os dados de demonstração.")
    parser.add_argument("--recriar", action="store_true", help="apaga todos os dados antes de popular")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.recriar:
            apagar_tudo(db)
        elif db.scalar(select(func.count()).select_from(m.Usuario)):
            print("O banco já tem dados. Use --recriar para apagar tudo e popular de novo.")
            return
        popular(db)
        db.commit()
        resumo = {
            "lojas": m.Loja,
            "produtos": m.Produto,
            "variações": m.Variacao,
            "estoques": m.Estoque,
            "movimentações": m.Movimentacao,
            "transferências": m.Transferencia,
            "pedidos": m.Pedido,
            "pagamentos": m.Pagamento,
            "atendimentos": m.Atendimento,
            "clientes": m.Cliente,
            "usuários": m.Usuario,
        }
        contagens = ", ".join(f"{db.scalar(select(func.count()).select_from(t))} {nome}" for nome, t in resumo.items())
        print(f"Dados de demonstração carregados: {contagens}.")
        print(f"Senha de todas as contas da equipe: {SENHA_DEMO} · PIN dos clientes: {PIN_DEMO}")


if __name__ == "__main__":
    main()
