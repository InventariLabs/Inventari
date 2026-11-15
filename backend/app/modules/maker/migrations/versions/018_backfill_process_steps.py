"""maker module — a stored process step becomes an object with no duration.

``maker_recipes.process_steps`` held a list of bare sentences before a step
could carry its time. The reader now expects ``{text, minutes}`` objects, so
every formula saved with steps before this branch would fail to open. The
schema change is 017; this revision rewrites the rows 017 leaves behind.

A sentence becomes ``{text, minutes: null}`` — a step nobody timed, which is
what it always was. Blank sentences are dropped, as the write path has always
dropped them. The rewrite is batched and selects its rows by the same
predicate that stops matching once a row is done, so an interrupted upgrade
resumes where it stopped and a large installation is not locked row by row.
"""

from collections.abc import Sequence

from alembic import op

revision: str = '018_backfill_process_steps'
down_revision: str | None = '017_costs_out_on_day_one'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = 5000

#: Rows still holding at least one element that is not a step object.
_UPGRADE_WHERE = """
    jsonb_typeof(process_steps) = 'array'
    AND EXISTS (
        SELECT 1
        FROM jsonb_array_elements(process_steps) AS step
        WHERE jsonb_typeof(step) <> 'object'
    )
"""

_UPGRADE_SET = """
    process_steps = COALESCE(
        (
            SELECT jsonb_agg(
                       CASE
                           WHEN jsonb_typeof(step) = 'object' THEN step
                           ELSE jsonb_build_object(
                               'text', btrim(step #>> '{}'),
                               'minutes', NULL
                           )
                       END
                       ORDER BY ordinality
                   )
            FROM jsonb_array_elements(process_steps)
                 WITH ORDINALITY AS t(step, ordinality)
            WHERE jsonb_typeof(step) = 'object'
               OR btrim(step #>> '{}') <> ''
        ),
        '[]'::jsonb
    )
"""

#: The reverse is best effort: the durations this branch added are lost.
_DOWNGRADE_WHERE = """
    jsonb_typeof(process_steps) = 'array'
    AND EXISTS (
        SELECT 1
        FROM jsonb_array_elements(process_steps) AS step
        WHERE jsonb_typeof(step) = 'object'
    )
"""

_DOWNGRADE_SET = """
    process_steps = COALESCE(
        (
            SELECT jsonb_agg(step ->> 'text' ORDER BY ordinality)
            FROM jsonb_array_elements(process_steps)
                 WITH ORDINALITY AS t(step, ordinality)
            WHERE jsonb_typeof(step) = 'object'
              AND coalesce(step ->> 'text', '') <> ''
        ),
        '[]'::jsonb
    )
"""


def _rewrite(where: str, assignment: str) -> None:
    """Rewrite batches until no row matches ``where`` any more."""
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        while True:
            moved = conn.exec_driver_sql(
                f'UPDATE maker_recipes SET {assignment} '
                f'WHERE id IN ('
                f'  SELECT id FROM maker_recipes WHERE {where} '
                f'  ORDER BY id LIMIT {_BATCH}'
                f')'
            ).rowcount
            if not moved:
                break


def upgrade() -> None:
    _rewrite(_UPGRADE_WHERE, _UPGRADE_SET)


def downgrade() -> None:
    _rewrite(_DOWNGRADE_WHERE, _DOWNGRADE_SET)
