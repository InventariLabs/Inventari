"""add default_template_id to document_profiles

Revision ID: dce8a56741b2
Revises: 38f0d55ddde7
Create Date: 2026-04-23 20:24:47.340095

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "dce8a56741b2"
down_revision: Union[str, None] = "38f0d55ddde7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_profiles",
        sa.Column("default_template_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_document_profiles_default_template_id",
        "document_profiles",
        "document_templates",
        ["default_template_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_document_profiles_default_template_id",
        "document_profiles",
        type_="foreignkey",
    )
    op.drop_column("document_profiles", "default_template_id")