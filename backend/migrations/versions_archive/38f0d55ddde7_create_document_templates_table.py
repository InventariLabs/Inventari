"""create document_templates table

Revision ID: 38f0d55ddde7
Revises: f6a7b8c9d0e1
Create Date: 2026-04-23 20:22:48.696575

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "38f0d55ddde7"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_templates",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_by",
            postgresql.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_doc_templates_org_module", "document_templates", ["organization_id", "module"], unique=False)
    op.create_index("ix_doc_templates_organization_id", "document_templates", ["organization_id"], unique=False)
    op.create_index("ix_doc_templates_module", "document_templates", ["module"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_doc_templates_module", table_name="document_templates")
    op.drop_index("ix_doc_templates_organization_id", table_name="document_templates")
    op.drop_index("ix_doc_templates_org_module", table_name="document_templates")
    op.drop_table("document_templates")