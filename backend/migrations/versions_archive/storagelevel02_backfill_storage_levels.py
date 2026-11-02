"""backfill storage_locations.level from tree depth

Revision ID: storagelevel02
Revises: storagelevel01
Create Date: 2026-08-15

Data migration (ADR-014): assigns SITE / ZONE / LOCATION from the current
parent chain. Aborts loudly when the tree contains nodes deeper than the
third level, cycles, or dangling parents — repair first, per
docs/subsystems/STORAGE_TREE_INTEGRITY.md.
"""

import sqlalchemy as sa
from alembic import op

revision = 'storagelevel02'
down_revision = 'storagelevel01'
branch_labels = None
depends_on = None

_LEVELS = ('site', 'zone', 'location')


def _compute_levels(parent_by_id: dict) -> dict:
    """Map node id -> level from the parent chain; raise on broken trees.

    Pure function so tests can pin the guards without a database.
    """
    level_by_id: dict = {}
    for node_id in parent_by_id:
        chain = []
        seen = set()
        current = node_id
        while current is not None:
            if current in seen:
                raise RuntimeError(
                    f'Storage hierarchy contains a cycle involving {current}. '
                    'Repair the tree before applying storagelevel02 — see '
                    'docs/subsystems/STORAGE_TREE_INTEGRITY.md.'
                )
            seen.add(current)
            chain.append(current)
            next_id = parent_by_id.get(current)
            if next_id is not None and next_id not in parent_by_id:
                raise RuntimeError(
                    f'Storage location {current} has a dangling parent '
                    f'{next_id}. Repair the tree before applying '
                    'storagelevel02.'
                )
            current = next_id
        depth = len(chain) - 1
        if depth >= len(_LEVELS):
            raise RuntimeError(
                f'Storage location {node_id} sits at depth {depth} — deeper '
                'than the third level. Repair the tree before applying '
                'storagelevel02 (ADR-014).'
            )
        level_by_id[node_id] = _LEVELS[depth]
    return level_by_id


def _run_upgrade_sql(bind) -> None:
    rows = bind.execute(
        sa.text('SELECT id, parent_id FROM storage_locations')
    ).fetchall()
    parent_by_id = {row[0]: row[1] for row in rows}
    level_by_id = _compute_levels(parent_by_id)
    for node_id, level in level_by_id.items():
        bind.execute(
            sa.text('UPDATE storage_locations SET level = :level WHERE id = :id'),
            {'level': level, 'id': node_id},
        )


def upgrade() -> None:
    _run_upgrade_sql(op.get_bind())


def downgrade() -> None:
    # The backfill has no meaningful inverse — levels derived from depth are
    # dropped together with the column by storagelevel01's downgrade.
    pass
