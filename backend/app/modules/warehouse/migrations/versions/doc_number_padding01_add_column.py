"""add number_padding to document_profiles.

Revision ID: doc_number_padding01
Revises: doc_inv_period_uq01
Create Date: 2026-07-25

Adds a per-organization `number_padding` column (3..6, default 4) that
controls the sequence width for warehouse documents and purchase orders.

Backfill strategy: extract N from the existing `numbering_format` token
`{SEQ:Nd}`. Fallback to 4 when the token is missing or malformed. Clamp
the result to the validated 3..6 range so an inherited `{SEQ:02d}` or
an extreme value cannot break generation.

Downgrade restores the prior schema (column dropped, data lost).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_number_padding01'
down_revision: str | None = 'doc_inv_period_uq01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_profiles',
        sa.Column(
            'number_padding',
            sa.SmallInteger(),
            nullable=False,
            server_default='4',
        ),
    )

    # Backfill: extract N from existing {SEQ:Nd} token, fallback to 4.
    # Uses regexp_matches returning one row per match; we take the first.
    op.execute(
        r"""
        UPDATE document_profiles
        SET number_padding = COALESCE(
            (
                SELECT (regexp_matches(
                    numbering_format, '\{SEQ:0*([0-9]+)d\}', 'g'
                ))[1]::int
            ),
            4
        )
        WHERE number_padding = 4
          AND numbering_format IS NOT NULL
          AND numbering_format LIKE '%{SEQ:%'
        """
    )

    # Defensive clamp: anything outside 3..6 snaps to 4. This protects against
    # legacy formats that encoded a different width via the raw token.
    op.execute(
        """
        UPDATE document_profiles
        SET number_padding = 4
        WHERE number_padding < 3 OR number_padding > 6
        """
    )

    # Drop the server-side default; the application enforces the default via
    # the SQLAlchemy model so backfills remain explicit.
    op.alter_column('document_profiles', 'number_padding', server_default=None)


def downgrade() -> None:
    op.drop_column('document_profiles', 'number_padding')
