"""login oauth do servidor mcp

Conector do claude.ai (decisão 114, docs/mcp.md): login OAuth 2.1 no servidor MCP, além do token pessoal.
- oauth_clientes: os apps que se conectam (cadastro automático ou ficha publicada no domínio do app);
- oauth_codigos: códigos de autorização (10 minutos, uma vez só, com PKCE);
- oauth_tokens: acessos e renovações de cada conexão (a conexão é uma linha de tokens_mcp).
Só acrescenta: nenhuma tabela ou dado existente muda. O downgrade apaga as três tabelas.

Revision ID: e026a0aedd29
Revises: d8a3f1c26b47
Create Date: 2026-10-28 15:52:04.212759

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e026a0aedd29'
down_revision: Union[str, Sequence[str], None] = 'd8a3f1c26b47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('oauth_clientes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_id', sa.String(length=255), nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('redirect_uris', sa.JSON(), nullable=False),
    sa.Column('metodo_auth', sa.String(length=30), nullable=False),
    sa.Column('segredo_hash', sa.String(length=64), nullable=True),
    sa.Column('origem', sa.String(length=4), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("metodo_auth IN ('none', 'client_secret_post', 'client_secret_basic')", name='ck_oauth_clientes_metodo_auth'),
    sa.CheckConstraint("origem IN ('DCR', 'CIMD')", name='ck_oauth_clientes_origem'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('client_id')
    )
    op.create_table('oauth_codigos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('redirect_uri', sa.Text(), nullable=False),
    sa.Column('code_challenge', sa.String(length=128), nullable=False),
    sa.Column('recurso', sa.String(length=255), nullable=False),
    sa.Column('escopo', sa.String(length=100), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expira_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('usado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('token_mcp_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['cliente_id'], ['oauth_clientes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['token_mcp_id'], ['tokens_mcp.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hash')
    )
    op.create_index(op.f('ix_oauth_codigos_cliente_id'), 'oauth_codigos', ['cliente_id'], unique=False)
    op.create_index(op.f('ix_oauth_codigos_usuario_id'), 'oauth_codigos', ['usuario_id'], unique=False)
    op.create_table('oauth_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_mcp_id', sa.Integer(), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.String(length=9), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('recurso', sa.String(length=255), nullable=False),
    sa.Column('escopo', sa.String(length=100), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expira_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revogado_em', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("tipo IN ('ACESSO', 'RENOVACAO')", name='ck_oauth_tokens_tipo'),
    sa.ForeignKeyConstraint(['cliente_id'], ['oauth_clientes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['token_mcp_id'], ['tokens_mcp.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hash')
    )
    op.create_index(op.f('ix_oauth_tokens_cliente_id'), 'oauth_tokens', ['cliente_id'], unique=False)
    op.create_index(op.f('ix_oauth_tokens_token_mcp_id'), 'oauth_tokens', ['token_mcp_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_oauth_tokens_token_mcp_id'), table_name='oauth_tokens')
    op.drop_index(op.f('ix_oauth_tokens_cliente_id'), table_name='oauth_tokens')
    op.drop_table('oauth_tokens')
    op.drop_index(op.f('ix_oauth_codigos_usuario_id'), table_name='oauth_codigos')
    op.drop_index(op.f('ix_oauth_codigos_cliente_id'), table_name='oauth_codigos')
    op.drop_table('oauth_codigos')
    op.drop_table('oauth_clientes')
