"""invitation gains a recipient, a redemption trace and a revocation mark

Revision ID: invrecipient01
Revises: invrole02
Create Date: 2026-08-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'invrecipient01'
down_revision: str | None = 'invrole02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All nullable: rows issued before this migration keep working as bearer
    # codes until they expire, so a deployment does not invalidate whatever is
    # in flight.
    op.add_column(
        'organization_invitations',
        sa.Column('invited_email', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'organization_invitations',
        sa.Column('used_by_user_id', sa.UUID(), nullable=True),
    )
    op.add_column(
        'organization_invitations',
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'organization_invitations',
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_organization_invitations_used_by_user_id_users',
        'organization_invitations',
        'users',
        ['used_by_user_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_organization_invitations_used_by_user_id_users',
        'organization_invitations',
        type_='foreignkey',
    )
    op.drop_column('organization_invitations', 'revoked_at')
    op.drop_column('organization_invitations', 'used_at')
    op.drop_column('organization_invitations', 'used_by_user_id')
    op.drop_column('organization_invitations', 'invited_email')
