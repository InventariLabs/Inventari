"""migrate_document_types_pz_wz_mm_to_in_out_int

Revision ID: 1a681f9d2f97
Revises: 8635b0e5b9cf
Create Date: 2026-04-07 20:45:38.837141

Data migration: rename document type codes from Polish (PZ/WZ/MM) to
international equivalents (IN/OUT/INT) and update document numbers accordingly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a681f9d2f97'
down_revision: Union[str, None] = '8635b0e5b9cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mapping of old type -> new type and number prefix replacement
_TYPE_MAP = [
    ('PZ', 'IN'),
    ('WZ', 'OUT'),
    ('MM', 'INT'),
]


def upgrade() -> None:
    conn = op.get_bind()
    for old_type, new_type in _TYPE_MAP:
        # Update the type column
        conn.execute(
            sa.text(
                "UPDATE documents SET type = :new WHERE type = :old"
            ),
            {'new': new_type, 'old': old_type},
        )
        # Update document numbers: 'PZ/2026/001' -> 'IN/2026/001'
        conn.execute(
            sa.text(
                "UPDATE documents SET number = :new_prefix || substring(number from length(:old_prefix) + 1) "
                "WHERE number LIKE :pattern"
            ),
            {
                'new_prefix': new_type,
                'old_prefix': old_type,
                'pattern': f'{old_type}/%',
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    for old_type, new_type in _TYPE_MAP:
        # Reverse: new -> old
        conn.execute(
            sa.text(
                "UPDATE documents SET type = :old WHERE type = :new"
            ),
            {'old': old_type, 'new': new_type},
        )
        conn.execute(
            sa.text(
                "UPDATE documents SET number = :old_prefix || substring(number from length(:new_prefix) + 1) "
                "WHERE number LIKE :pattern"
            ),
            {
                'old_prefix': old_type,
                'new_prefix': new_type,
                'pattern': f'{new_type}/%',
            },
        )
