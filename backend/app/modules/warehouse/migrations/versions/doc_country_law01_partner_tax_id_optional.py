"""let a document profile defer the partner-tax-id requirement to the country.

Revision ID: doc_country_law01
Revises: doc_rule_locations01
Create Date: 2026-09-26

Whether a partner must carry a tax id is law, and law is where the
organization sits. ``require_partner_tax_id`` becomes tri-state: NULL is
"the profile states no opinion" and the organization's country answers
(``app/modules/warehouse/country_tax_rules.py``) — the same shape
``default_currency`` already has against the organization currency, and
``default_tax_rate`` against the country's rate.

Existing rows keep their True/False: an entry already made stays an entry.

Downgrade restores the strict boolean, reading NULL as False.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_country_law01'
down_revision: str | None = 'doc_rule_locations01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        'document_profiles',
        'require_partner_tax_id',
        existing_type=sa.Boolean(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        'UPDATE document_profiles SET require_partner_tax_id = false '
        'WHERE require_partner_tax_id IS NULL'
    )
    op.alter_column(
        'document_profiles',
        'require_partner_tax_id',
        existing_type=sa.Boolean(),
        nullable=False,
    )
