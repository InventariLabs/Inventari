"""equipment: per-person attestation responses with per-item rows.

. Campaigns used to create one ``audit_responses`` row per active
assignment — seven assets held by four people produced seven emails. This
migration adds ``audit_response_items`` so one response per person
(grouped by email) can carry many assets, and makes the legacy
``assignment_id`` column nullable for grouped envelopes.

* Upgrade — creates ``audit_response_items``, makes ``assignment_id``
  nullable, and backfills one item row per legacy response so existing
  campaigns keep rendering on the public page.
* Downgrade — collapses each grouped envelope onto its first item so
  ``assignment_id`` can be NOT NULL again, drops envelopes that have no
  items at all, then drops the items table.

Revision ID: 004_audit_response_items
Revises: 003_lowercase_assigned_to_email
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '004_audit_response_items'
# 003 (lowercase emails) is now in the same tree,
# so the chain is linear: 001 -> 002 -> 003 -> 004.
down_revision: str | None = '003_lowercase_assigned_to_email'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'audit_response_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column(
            'response_id',
            sa.Uuid(),
            sa.ForeignKey('audit_responses.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'assignment_id',
            sa.Uuid(),
            sa.ForeignKey('equipment_assignments.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'item_id',
            sa.Uuid(),
            sa.ForeignKey('items.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('item_name', sa.String(length=255), nullable=False),
        sa.Column('serial_number', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('dispute_type', sa.String(length=30), nullable=True),
        sa.Column('dispute_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_audit_response_items_response_id',
        'audit_response_items',
        ['response_id'],
        unique=False,
    )
    op.create_index(
        'ix_audit_response_items_assignment_id',
        'audit_response_items',
        ['assignment_id'],
        unique=False,
    )
    op.create_index(
        'ix_audit_response_items_item_id',
        'audit_response_items',
        ['item_id'],
        unique=False,
    )
    op.alter_column(
        'audit_responses', 'assignment_id', existing_type=sa.Uuid(), nullable=True
    )

    # Backfill: one item row per legacy response, mirroring its status.
    op.execute(
        """
        INSERT INTO audit_response_items (
            id, response_id, assignment_id, item_id, item_name,
            serial_number, status, dispute_type, dispute_reason, created_at
        )
        SELECT
            gen_random_uuid(),
            r.id,
            r.assignment_id,
            a.item_id,
            COALESCE(i.name, ''),
            COALESCE(
                (i.meta_data -> 'equipment' ->> 'serial_number'),
                i.serial_number
            ),
            r.status,
            r.dispute_type,
            r.dispute_reason,
            r.created_at
        FROM audit_responses r
        JOIN equipment_assignments a ON a.id = r.assignment_id
        LEFT JOIN items i ON i.id = a.item_id
        WHERE r.assignment_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Grouped envelopes carry no assignment_id — the old schema cannot hold
    # them, so collapse each one onto its first item before restoring the
    # NOT NULL constraint. Without this the downgrade fails on every
    # database where a campaign has run, which is every database that used
    # the feature this migration was written for.
    op.execute(
        """
        UPDATE audit_responses r
        SET assignment_id = first_item.assignment_id
        FROM (
            SELECT DISTINCT ON (response_id) response_id, assignment_id
            FROM audit_response_items
            ORDER BY response_id, created_at, id
        ) AS first_item
        WHERE r.id = first_item.response_id
          AND r.assignment_id IS NULL
        """
    )
    # Anything still NULL has no item to fall back on (a campaign that
    # reached nobody); it has no representation in the old schema.
    op.execute('DELETE FROM audit_responses WHERE assignment_id IS NULL')

    op.drop_index('ix_audit_response_items_item_id', table_name='audit_response_items')
    op.drop_index(
        'ix_audit_response_items_assignment_id', table_name='audit_response_items'
    )
    op.drop_index(
        'ix_audit_response_items_response_id', table_name='audit_response_items'
    )
    op.drop_table('audit_response_items')
    op.alter_column(
        'audit_responses', 'assignment_id', existing_type=sa.Uuid(), nullable=False
    )
