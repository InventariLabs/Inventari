"""add document_number_sequences.

Revision ID: doc_number_sequence01
Revises: doc_corrects_line01
Create Date: 2026-09-01

The next document number was derived by scanning the numbers already taken
and adding one to the highest. That reads the register as if it were the
counter, and the register forgets: a draft deleted the same afternoon
dropped out of the scan and handed its number to the next document.

This table is the counter Odoo (ir.sequence) and ERPNext (Naming Series)
keep instead — one row per prefix, and the prefix already carries the type
and the period, so a new year starts a new count on its own.

Nothing is backfilled. An organization's first number under a prefix seeds
the counter from the highest number already in use under it, so a warehouse
that has been running keeps counting from where it was.

Downgrade drops the table; the numbering falls back to the scan.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_number_sequence01'
down_revision: str | None = 'doc_corrects_line01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'document_number_sequences',
        sa.Column('organization_id', sa.UUID(as_uuid=True), nullable=False),
        sa.Column('prefix', sa.String(length=120), nullable=False),
        sa.Column('next_value', sa.Integer(), nullable=False, server_default='1'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('organization_id', 'prefix'),
    )


def downgrade() -> None:
    op.drop_table('document_number_sequences')
