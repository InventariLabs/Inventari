"""add_household_and_system_to_storage_types

Revision ID: add_household_and_system_to_storage_types
Revises:
Create Date: 2026-01-29

"""
from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_storage_type_fields'
down_revision: Union[str, None] = '688e77e3dcc7'
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    # Add new columns to storage_types table
    op.add_column('storage_types', sa.Column('household_id', sa.Uuid(), nullable=True))
    op.add_column('storage_types', sa.Column('is_system', sa.Boolean(), default=False))
    op.add_column('storage_types', sa.Column('created_by', sa.Uuid(), nullable=True))

    # Create unique constraint for type_code within household (or globally for system types)
    op.execute("""
        CREATE UNIQUE INDEX idx_storage_types_type_code_household
        ON storage_types (type_code)
        WHERE household_id IS NULL
    """)

    op.execute("""
        CREATE UNIQUE INDEX idx_storage_types_type_code_unique
        ON storage_types (type_code, household_id)
        WHERE household_id IS NOT NULL
    """)


def downgrade() -> None:
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_storage_types_type_code_unique")
    op.execute("DROP INDEX IF EXISTS idx_storage_types_type_code_household")

    # Drop columns
    op.drop_column('storage_types', 'created_by')
    op.drop_column('storage_types', 'is_system')
    op.drop_column('storage_types', 'household_id')