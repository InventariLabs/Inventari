"""add CHECK constraint for partner type

Revision ID: 5b8c0d4e6f7a
Revises: 4a7b9c3d5e6f
Create Date: 2026-04-25 22:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = '5b8c0d4e6f7a'
down_revision: Union[str, None] = '4a7b9c3d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VALID_TYPES = (
    'SUPPLIER', 'CUSTOMER', 'BOTH',
    'SERVICE_PROVIDER', 'MANUFACTURER', 'EMPLOYEE',
)


def upgrade() -> None:
    op.create_check_constraint(
        'ck_partner_type_valid',
        'partners',
        f"type = ANY(ARRAY[{', '.join(repr(t) for t in _VALID_TYPES)}])",
    )


def downgrade() -> None:
    op.drop_constraint('ck_partner_type_valid', 'partners')
