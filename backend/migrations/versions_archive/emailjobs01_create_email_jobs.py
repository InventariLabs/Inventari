"""create email_jobs table (durable email queue)

Revision ID: emailjobs01
Revises: evtoutbox01
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'emailjobs01'
down_revision: str | None = 'evtoutbox01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'email_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('to_email', sa.String(320), nullable=False),
        sa.Column('subject', sa.String(500), nullable=False),
        sa.Column('html_content', sa.Text(), nullable=False),
        sa.Column('attachment_bytes', sa.LargeBinary(), nullable=True),
        sa.Column('attachment_filename', sa.String(255), nullable=True),
        sa.Column('smtp_config_enc', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
        sa.Column(
            'next_attempt_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_email_jobs_status', 'email_jobs', ['status'])
    op.create_index('ix_email_jobs_next_attempt_at', 'email_jobs', ['next_attempt_at'])
    op.create_index('ix_email_jobs_organization_id', 'email_jobs', ['organization_id'])


def downgrade() -> None:
    op.drop_index('ix_email_jobs_organization_id', table_name='email_jobs')
    op.drop_index('ix_email_jobs_next_attempt_at', table_name='email_jobs')
    op.drop_index('ix_email_jobs_status', table_name='email_jobs')
    op.drop_table('email_jobs')
