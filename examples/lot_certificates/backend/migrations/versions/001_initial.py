"""The certificates on file.

``create_table_if_absent`` / ``create_index_if_absent`` come from
``app.core.module_sdk``: an installation that already holds the table (a
restore) replays this revision without failing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.core.module_sdk import create_index_if_absent, create_table_if_absent

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('lot_certificates',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_absent(
        'lot_certificates_certificates',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('number', sa.String(100), nullable=False),
        sa.Column('filed_by', UUID(as_uuid=True), nullable=True),
        sa.Column(
            'filed_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id', 'number', name='uq_lot_certificates_org_number'
        ),
    )
    create_index_if_absent(
        'ix_lot_certificates_certificates_organization_id',
        'lot_certificates_certificates',
        ['organization_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_lot_certificates_certificates_organization_id',
        table_name='lot_certificates_certificates',
    )
    op.drop_table('lot_certificates_certificates')
