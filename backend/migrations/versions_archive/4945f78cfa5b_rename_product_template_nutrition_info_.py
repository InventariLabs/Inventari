"""rename_product_template_nutrition_info_to_meta_data

Revision ID: 4945f78cfa5b
Revises: d9eb49e0a845
Create Date: 2026-03-27 20:17:06.520435

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4945f78cfa5b'
down_revision: Union[str, None] = 'd9eb49e0a845'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename column to keep existing data intact (safe rename, no data migration needed).
    # Future: if module-specific indexes are needed on meta_data sub-keys,
    # add partial expression indexes in a separate migration.
    op.alter_column(
        'product_templates',
        'nutrition_info',
        new_column_name='meta_data',
    )


def downgrade() -> None:
    op.alter_column(
        'product_templates',
        'meta_data',
        new_column_name='nutrition_info',
    )
