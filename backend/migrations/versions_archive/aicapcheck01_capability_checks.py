"""an AI connection records what the test found, not just what it claims

Revision ID: aicapcheck01
Revises: svlcurrency01
Create Date: 2026-08-27

``capabilities`` is a claim. Something ticked "reads images" — usually the
form, off the provider's name rather than off the model — and from then on the
card showed VISION as a fact and the purpose picker offered the connection for
reading photographs. A model that cannot see was indistinguishable from one
that can.

The application already knew better and threw the answer away: the connection
test sends a real request through the purpose's contract probe, vision first
precisely because that is where a weaker model gives out, and judges the reply
with the feature's own parser. The verdict reached a toast and nothing else.

This column is where it lands now — per capability, whether the model did the
job when asked and when it was asked. Empty means never tested, which is what
every existing row is: a connection that worked yesterday keeps working, and
nothing is refused for want of a test nobody has run yet.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'aicapcheck01'
down_revision = 'svlcurrency01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'ai_connections',
        sa.Column(
            'capability_checks',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default='{}',
        ),
    )


def downgrade() -> None:
    op.drop_column('ai_connections', 'capability_checks')
