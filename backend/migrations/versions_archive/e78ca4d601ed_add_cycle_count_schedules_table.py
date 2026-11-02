"""add cycle count schedules table

Revision ID: e78ca4d601ed
Revises: f7a67cdf1d33
Create Date: 2026-05-09 21:25:44.484241

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e78ca4d601ed'
down_revision: Union[str, None] = 'f7a67cdf1d33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cycle_count_schedules',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column(
            'frequency',
            sa.Enum('DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY', name='cyclecountfrequency'),
            nullable=False,
        ),
        sa.Column(
            'scope',
            sa.Enum('ALL', 'ZONE', 'CATEGORY', name='cyclecountscope'),
            nullable=False,
        ),
        sa.Column('scope_filter', sa.JSON(), nullable=True),
        sa.Column('sample_size', sa.Integer(), nullable=True),
        sa.Column('tolerance_percent', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_cycle_count_schedules_organization_id'),
        'cycle_count_schedules',
        ['organization_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_cycle_count_schedules_organization_id'), table_name='cycle_count_schedules')
    op.drop_table('cycle_count_schedules')
    op.execute('DROP TYPE IF EXISTS cyclecountfrequency')
    op.execute('DROP TYPE IF EXISTS cyclecountscope')
