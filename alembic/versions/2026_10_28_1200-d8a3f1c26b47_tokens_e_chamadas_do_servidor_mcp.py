"""tokens e chamadas do servidor mcp

Decisão 106 (docs/registro_decisoes_e4.md, docs/mcp.md): o copiloto em apps de IA de fora do painel.
- tokens_mcp: token pessoal de cada membro da equipe (só o sha256 e o começo), com validade e revogação;
- chamadas_mcp: auditoria de cada ferramenta chamada pelo servidor MCP.
Só tabelas novas; o downgrade as remove.

Revision ID: d8a3f1c26b47
Revises: 7c2d9e4f1a6b
Create Date: 2026-10-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8a3f1c26b47'
down_revision: Union[str, Sequence[str], None] = '7c2d9e4f1a6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tokens_mcp',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=60), nullable=False),
        sa.Column('hash', sa.String(length=64), nullable=False),
        sa.Column('prefixo', sa.String(length=16), nullable=False),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expira_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ultimo_uso_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revogado_em', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hash'),
    )
    op.create_index(op.f('ix_tokens_mcp_usuario_id'), 'tokens_mcp', ['usuario_id'], unique=False)
    op.create_table(
        'chamadas_mcp',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('ferramenta', sa.String(length=60), nullable=False),
        sa.Column('argumentos', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('sucesso', sa.Boolean(), nullable=False),
        sa.Column('erro', sa.String(length=255), nullable=True),
        sa.Column('duracao_ms', sa.Integer(), nullable=False),
        sa.Column('cliente', sa.String(length=80), nullable=True),
        sa.Column('criada_em', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['token_id'], ['tokens_mcp.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_chamadas_mcp_token_id'), 'chamadas_mcp', ['token_id'], unique=False)
    op.create_index(op.f('ix_chamadas_mcp_usuario_id'), 'chamadas_mcp', ['usuario_id'], unique=False)
    op.create_index(op.f('ix_chamadas_mcp_criada_em'), 'chamadas_mcp', ['criada_em'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_chamadas_mcp_criada_em'), table_name='chamadas_mcp')
    op.drop_index(op.f('ix_chamadas_mcp_usuario_id'), table_name='chamadas_mcp')
    op.drop_index(op.f('ix_chamadas_mcp_token_id'), table_name='chamadas_mcp')
    op.drop_table('chamadas_mcp')
    op.drop_index(op.f('ix_tokens_mcp_usuario_id'), table_name='tokens_mcp')
    op.drop_table('tokens_mcp')
