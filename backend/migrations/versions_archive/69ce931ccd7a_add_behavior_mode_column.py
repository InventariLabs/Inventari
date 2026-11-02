from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = '69ce931ccd7a'
down_revision = '4fa164d4e46c'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('storage_types', sa.Column('behavior_mode', sa.String(length=50), nullable=True))
    op.execute("UPDATE storage_types SET behavior_mode = 'EXPIRY'")
    op.alter_column('storage_types', 'behavior_mode', nullable=False)

def downgrade() -> None:
    op.drop_column('storage_types', 'behavior_mode')
