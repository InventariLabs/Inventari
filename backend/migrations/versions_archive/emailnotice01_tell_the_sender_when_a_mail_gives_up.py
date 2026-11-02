"""email_jobs.failure_notice_enc — say who to tell when a mail gives up

Revision ID: emailnotice01
Revises: auditidx02
Create Date: 2026-10-09

A mail whose delivery matters to one person (the registration link an
administrator just approved) can carry a notice for that person: when the queue
marks the row ``failed`` the notice becomes an in-app notification, so the link
is not lost with the row. Encrypted like ``smtp_config_enc``: the content may
hold the link itself. Nullable; every existing row keeps behaving as before.
"""

import sqlalchemy as sa
from alembic import op

revision = 'emailnotice01'
down_revision = 'auditidx02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'email_jobs', sa.Column('failure_notice_enc', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('email_jobs', 'failure_notice_enc')
