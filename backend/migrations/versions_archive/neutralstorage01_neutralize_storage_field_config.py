"""neutralize storage field configuration

This migration makes the storage configuration screen vertical-agnostic by:

1. **Backfilling ``categories.context_tag`` from legacy ``category_type``** for
   rows where ``context_tag`` is NULL. The mapping is:
   - ``FREEZER``/``FRIDGE`` → ``cold_storage``
   - ``PANTRY``             → ``dry_goods``
   - anything else          → kept as-is (``category_type`` stays for back-compat)

2. **Stripping food/equipment-biased keys from ``storage_locations.context_schema``**:
   ``freeze_date``, ``expiry_date``, ``production_date``, ``brand``,
   ``serial_number``, ``manufacturer``, ``model``, ``equipment_status`` are no
   longer storage toggles. Vertical-specific fields now live on
   ``Category.field_definitions`` and are merged at item-form render time.

The migration is idempotent: re-running it is a no-op because the WHERE clauses
filter on NULL / containing food keys.

The module also exposes ``_run_upgrade_sql(bind)`` so tests can invoke the
upgrade logic directly without alembic's revision tracking (which would
otherwise skip a re-run when the DB is already at head).

Revision ID: neutralstorage01
Revises: bughunt01
Create Date: 2026-07-02 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'neutralstorage01'
down_revision: str | None = 'bughunt01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Food/equipment-biased keys that must not appear on a storage's context_schema
# once it is vertical-agnostic. Mirrors the forbidden set in test_seed_data.py.
FORBIDDEN_CONTEXT_SCHEMA_KEYS: tuple[str, ...] = (
    'freeze_date',
    'expiry_date',
    'production_date',
    'brand',
    'serial_number',
    'manufacturer',
    'model',
    'equipment_status',
)


def _run_upgrade_sql(bind: sa.engine.interfaces.Connectable) -> None:
    """Pure-SQL upgrade logic. Exposed at module level so tests can invoke it
    directly without going through alembic's revision tracking (which is
    idempotent and would skip a re-run).

    ``bind`` may be either a SQLAlchemy ``Engine`` (SQLAlchemy 2.0 — must be
    wrapped in ``begin()``) or a live ``Connection`` / alembic ``op`` bind
    (which already manages its own transaction). We detect and adapt.

    Idempotent: re-running leaves the DB in the same state.
    """
    # Engine has no .execute() in SA 2.0; open a connection + transaction.
    if isinstance(bind, sa.engine.Engine):
        with bind.begin() as conn:
            _execute_upgrade_statements(conn)
        return

    # Connection or alembic op bind: caller manages the transaction.
    _execute_upgrade_statements(bind)


def _execute_upgrade_statements(conn: sa.engine.interfaces.Connectable) -> None:
    # 1. Backfill categories.context_tag from categories.category_type where
    #    context_tag is NULL. Mapping is conservative: only the known legacy
    #    food tags are translated; other category_types leave context_tag NULL
    #    so downstream code keeps its existing behaviour.
    conn.execute(
        sa.text(
            """
            UPDATE categories
            SET context_tag = CASE category_type
                WHEN 'FREEZER' THEN 'cold_storage'
                WHEN 'FRIDGE'  THEN 'cold_storage'
                WHEN 'PANTRY'  THEN 'dry_goods'
                ELSE context_tag
            END
            WHERE context_tag IS NULL
              AND category_type IS NOT NULL
              AND category_type IN ('FREEZER', 'FRIDGE', 'PANTRY')
            """
        )
    )

    # 2. Strip food/equipment-biased keys from storage_locations.context_schema.
    #    The column is JSONB; we use jsonb operations to filter the array.
    #
    #    We rebuild the array inline rather than mutating in place because
    #    PostgreSQL JSONB arrays don't support element deletion by value out
    #    of the box. The expression below filters out any element whose
    #    text value matches one of the forbidden keys.
    #
    #    Note: cast to ::jsonb is required because the column is typed as `json`
    #    (not `jsonb`) on some deployments — jsonb_typeof refuses plain `json`.
    #    The forbidden_keys bindparam is a text[]; psycopg2 adapts a Python list
    #    to a PostgreSQL array literal so `= ANY(:forbidden_keys)` works.
    conn.execute(
        sa.text(
            """
            UPDATE storage_locations
            SET context_schema = (
                SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                FROM jsonb_array_elements_text(context_schema::jsonb) AS elem
                WHERE NOT (elem = ANY (:forbidden_keys))
            )
            WHERE context_schema IS NOT NULL
              AND jsonb_typeof(context_schema::jsonb) = 'array'
              AND EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(context_schema::jsonb) AS elem
                  WHERE elem = ANY (:forbidden_keys)
              )
            """
        ).bindparams(
            forbidden_keys=list(FORBIDDEN_CONTEXT_SCHEMA_KEYS),
        )
    )


def upgrade() -> None:
    _run_upgrade_sql(op.get_bind())


def downgrade() -> None:
    # Forward-only by design: after this migration the seed also emits neutral
    # values, so a downgrade would silently disagree with new inserts. We keep
    # the downgrade as a best-effort restore that rebuilds context_schema from
    # the food/equipment keys we had stripped — useful only when rolling back
    # immediately after applying, before any new seeds ran.
    #
    # For categories.context_tag: clear any value we set on upgrade (best-effort
    # — we cannot distinguish our own backfill from a legitimate tag, so we
    # only clear when category_type exactly matches the legacy mapping).
    op.execute(
        sa.text(
            """
            UPDATE categories
            SET context_tag = NULL
            WHERE category_type IN ('FREEZER', 'FRIDGE', 'PANTRY')
              AND context_tag IN ('cold_storage', 'dry_goods')
            """
        )
    )

    # For storage_locations.context_schema: nothing to restore — we did not
    # capture the pre-migration values, and re-adding the food keys would
    # re-introduce the bias that this migration removes. Callers wanting to
    # roll back must restore from a DB backup.
