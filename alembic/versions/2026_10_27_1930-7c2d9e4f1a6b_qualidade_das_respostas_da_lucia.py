"""qualidade das respostas da lucia

Decisões 101, 102 e 104 (docs/registro_decisoes_e4.md): em mensagens_assistente,
- auditoria (JSON): verificação dos números, se a rodada falhou e se a Lúcia passou o cliente para uma pessoa;
- avaliacao, avaliacao_comentario e avaliada_em: o 👍/👎 do cliente em cada resposta.
Só colunas novas, todas opcionais; o downgrade as remove.

Revision ID: 7c2d9e4f1a6b
Revises: c41d7e2a9b10
Create Date: 2026-10-27 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2d9e4f1a6b'
down_revision: Union[str, Sequence[str], None] = 'c41d7e2a9b10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('mensagens_assistente', sa.Column('auditoria', sa.JSON(), nullable=True))
    op.add_column('mensagens_assistente', sa.Column('avaliacao', sa.SmallInteger(), nullable=True))
    op.add_column('mensagens_assistente', sa.Column('avaliacao_comentario', sa.Text(), nullable=True))
    op.add_column('mensagens_assistente', sa.Column('avaliada_em', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint('ck_mensagens_assistente_avaliacao', 'mensagens_assistente', 'avaliacao IN (1, -1)')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_mensagens_assistente_avaliacao', 'mensagens_assistente', type_='check')
    op.drop_column('mensagens_assistente', 'avaliada_em')
    op.drop_column('mensagens_assistente', 'avaliacao_comentario')
    op.drop_column('mensagens_assistente', 'avaliacao')
    op.drop_column('mensagens_assistente', 'auditoria')
