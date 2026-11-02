"""putaway rules carry an ordered list of locations.

Revision ID: doc_rule_locations01
Revises: doc_putaway_capacity01
Create Date: 2026-09-16

One target per rule meant one answer: the first shelf filled up and the
rule kept steering every later delivery onto it. The rule now names an
ordered list, and the resolver walks it against capacity. Every existing
rule's single target becomes a list of one — position 0 — and the old
column is dropped, so the list is the only place a rule's shelves live.

Downgrade folds the first list entry back into target_location_id and
drops the list.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_rule_locations01'
down_revision: str | None = 'doc_putaway_capacity01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'putaway_rule_locations',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'rule_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('putaway_rules.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'location_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint(
            'rule_id',
            'location_id',
            name='uq_putaway_rule_locations_rule_loc',
        ),
    )
    op.create_index(
        'ix_putaway_rule_locations_rule',
        'putaway_rule_locations',
        ['rule_id'],
    )
    # Every existing rule's single target becomes the head of its list.
    op.execute(
        """
        INSERT INTO putaway_rule_locations (id, organization_id, rule_id, location_id, position)
        SELECT gen_random_uuid(), organization_id, id, target_location_id, 0
        FROM putaway_rules
        """
    )
    op.drop_column('putaway_rules', 'target_location_id')


def downgrade() -> None:
    op.add_column(
        'putaway_rules',
        sa.Column(
            'target_location_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='CASCADE'),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE putaway_rules r
        SET target_location_id = l.location_id
        FROM putaway_rule_locations l
        WHERE l.rule_id = r.id AND l.position = 0
        """
    )
    op.drop_index(
        'ix_putaway_rule_locations_rule', table_name='putaway_rule_locations'
    )
    op.drop_table('putaway_rule_locations')
