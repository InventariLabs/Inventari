"""equipment: retire the module's own document-template table.

``equipment_document_templates`` was created by ``001_initial`` for
``template_service.py``, which stored handover-protocol bodies per
organization. The module later moved to the core table
(``app.core.template_models.DocumentTemplate``) and the service went with the
dead-code cleanup of 2026-08-07 — leaving a model no production code imports
and a table nothing reads or writes, standing beside the core table that
holds the real templates. Two tables under one name is the shape already
removed a floor above, at the schema level, where the module kept its own
Create/Update schemas beside the core ones its router imported.

Verified empty before removal: no rows in any development database, and no
writer since the service was deleted, so nothing has to be carried over to
the core table. No release ever shipped the table, so no installation can
hold rows this migration would remove.

* Upgrade — removes the table.
* Downgrade — recreates it, empty, as ``001_initial`` made it. It cannot
  bring rows back, and there are none to bring back.

Revision ID: 008_drop_module_doc_templates
Revises: 007_seed_handles_on_locations
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '008_drop_module_doc_templates'
down_revision: str | None = '007_seed_handles_on_locations'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = 'equipment_document_templates'


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_TABLE):
        op.drop_table(_TABLE)


def downgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('document_type', sa.String(30), nullable=False),
        sa.Column('body_html', sa.Text(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    op.create_index('ix_eq_doc_tpl_org', _TABLE, ['organization_id'])
    op.create_index(f'ix_{_TABLE}_organization_id', _TABLE, ['organization_id'])
