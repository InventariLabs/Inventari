"""add checkout_location_id to equipment_assignments

Revision ID: 5aed48d87212
Revises: a46daee2e1d5
Create Date: 2026-04-28 09:06:12.123227

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5aed48d87212'
down_revision: Union[str, None] = 'a46daee2e1d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'equipment_assignments',
        sa.Column('checkout_location_id', sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f('ix_equipment_assignments_checkout_location_id'),
        'equipment_assignments',
        ['checkout_location_id'],
        unique=False,
    )
    op.create_foreign_key(
        None,
        'equipment_assignments',
        'storage_locations',
        ['checkout_location_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        None, 'equipment_assignments', type_='foreignkey'
    )
    op.drop_index(
        op.f('ix_equipment_assignments_checkout_location_id'),
        table_name='equipment_assignments',
    )
    op.drop_column('equipment_assignments', 'checkout_location_id')
