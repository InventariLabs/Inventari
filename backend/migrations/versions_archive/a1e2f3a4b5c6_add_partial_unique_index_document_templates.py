"""add partial unique index for document_templates is_default

Revision ID: a1e2f3a4b5c6
Revises: dce8a56741b2
Create Date: 2026-04-23 21:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "a1e2f3a4b5c6"
down_revision: Union[str, None] = "dce8a56741b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_doc_template_default
        ON document_templates (organization_id, module, document_type)
        WHERE is_default = true
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_doc_template_default")
