"""drop the scopes column from api_keys.

Every key stored ``["full"]`` (or, for older rows, ``["read", "write"]``) and
nothing ever read it: the permission set an API key carries is fixed in
``identity_service.API_KEY_PERMISSIONS``. The column existed only to be
rendered by an API response that told administrators something untrue about
what they had just issued.

Revision ID: 002_drop_scopes
Revises: 001_initial
Create Date: 2026-08-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON

revision: str = '002_drop_scopes'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `IF EXISTS`, because `db upgrade-modules` reconciles an installation whose
    # `api_keys` table came from the old core baseline by stamping
    # `001_initial` — and a table that arrived some other way (a schema built
    # from current metadata, say) never had the column. Skipping the drop is
    # not hiding a failed upgrade here: the post-condition is the same either
    # way, which is what makes this different from a real schema change.
    op.execute(sa.text('ALTER TABLE api_keys DROP COLUMN IF EXISTS scopes'))


def downgrade() -> None:
    op.add_column(
        'api_keys',
        sa.Column(
            'scopes',
            JSON,
            nullable=False,
            server_default='["full"]',
        ),
    )
