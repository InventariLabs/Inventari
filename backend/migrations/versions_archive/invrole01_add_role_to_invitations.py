"""carry a role on the invitation code

Revision ID: invrole01
Revises: catgrouplabel01
Create Date: 2026-08-22

The join flow set ``user.role = 'user'`` outright, so an administrator
inviting a warehouse manager had to wait for them to arrive and then promote
them — while the API already accepted a role on the other invite endpoint,
the one no interface called.

Existing rows keep the behaviour they were issued under: ``'user'``.
"""

import sqlalchemy as sa
from alembic import op

revision = 'invrole01'
down_revision = 'catgrouplabel01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'organization_invitations',
        sa.Column(
            'role',
            sa.String(length=50),
            nullable=False,
            server_default='user',
        ),
    )


def downgrade() -> None:
    op.drop_column('organization_invitations', 'role')
