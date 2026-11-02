"""Organization issuer identity: structured address and optional logo.

Revision ID: orgissuer01
Revises: permgrant01
Create Date: 2026-08-24

warehouse document printouts carry no issuer data (name, tax ID,
address, logo), so they cannot circulate outside the app in any country.
The address and the optional logo land on ``organizations`` — the same
identity labels, order PDFs, equipment protocols and e-mails need — instead
of a per-print copy on ``document_profiles``.

The country is deliberately NOT part of the address JSONB: ``organizations``
already has its own ISO ``country`` column, and duplicating it inside the
address would recreate the free-text drift the partner address migration
removed. ``logo_url`` stores the org-scoped file-storage path; no data
backfill is needed — both columns are optional.
"""

import sqlalchemy as sa
from alembic import op  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = 'orgissuer01'
down_revision: str | None = 'permgrant01'
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = 'organizations'


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column('address', sa.JSON(), nullable=True))
    op.add_column(_TABLE, sa.Column('logo_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, 'logo_url')
    op.drop_column(_TABLE, 'address')
