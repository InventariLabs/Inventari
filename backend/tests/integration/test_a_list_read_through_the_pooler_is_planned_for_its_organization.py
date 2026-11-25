"""A list read through the pooler is planned for the organization that asks.

In production the backend reaches PostgreSQL through PgBouncer in transaction
mode. PgBouncer keeps the statements the driver prepares on its server
connections and hands every client that prepares the same text the same
statement, so the items list of every organization is one statement executed
over and over. After five executions PostgreSQL may plan such a statement
once for any value (a generic plan), estimating rows as the average over all
organizations. On an instance hosting organizations of very different sizes
the largest one then reads its list through a plan made for one a fraction
of its size: measured at 100 000 products beside sixteen small
organizations, a deep page of the items list took 21 s on that plan and
60 ms on its own.

The database the stack starts runs with ``plan_cache_mode=force_custom_plan``,
so every execution is planned for its own values. That is the planning a
statement prepared afresh pays anyway, which is what the backend does when it
connects without the pooler: its asyncpg statement cache is off
(``app/database.py``), so each read is prepared, planned and run once.

The setting is read from the compose files themselves and applied to the
session, so the assertion is about what the database is started with, not a
value restated here; the statement stands in for the one PgBouncer keeps.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

#: PostgreSQL plans a prepared statement for its values five times before it
#: weighs a generic plan; the sixth execution is the first that may take one.
_EXECUTIONS = 6

_STATEMENT = 'list_read_through_the_pooler'


def _database_command(compose_file: str) -> list[str]:
    compose = yaml.safe_load((_REPO_ROOT / compose_file).read_text(encoding='utf-8'))
    return compose['services']['db']['command'].split()


def _plan_cache_mode(compose_file: str) -> str:
    """The ``plan_cache_mode`` the file starts the database with (PostgreSQL's
    own default, ``auto``, when the command does not name one)."""
    command = _database_command(compose_file)
    settings = dict(
        command[i + 1].split('=', 1) for i, word in enumerate(command) if word == '-c'
    )
    return settings.get('plan_cache_mode', 'auto')


@pytest.mark.parametrize(
    'compose_file',
    [
        # Production, and the demo built on it.
        'docker-compose.prod.yml',
        # The warehouse-scale measurement tunes the database as production does.
        'docker-compose.scale.yml',
        # Development and the test stacks.
        'docker-compose.yml',
    ],
)
async def test_a_statement_executed_again_and_again_is_planned_for_its_values(
    compose_file: str, real_async_db_session: AsyncSession
):
    db = real_async_db_session
    mode = _plan_cache_mode(compose_file)
    assert mode.replace('_', '').isalpha(), mode
    await db.execute(text(f"SET LOCAL plan_cache_mode = '{mode}'"))
    await db.execute(
        text(
            f'PREPARE {_STATEMENT}(uuid) AS '
            'SELECT id FROM items WHERE organization_id = $1 '
            'ORDER BY created_at DESC LIMIT 50'
        )
    )
    try:
        organization = uuid4()
        for _ in range(_EXECUTIONS):
            await db.execute(text(f"EXECUTE {_STATEMENT}('{organization}')"))
        generic, custom = (
            await db.execute(
                text(
                    'SELECT generic_plans, custom_plans FROM pg_prepared_statements '
                    'WHERE name = :name'
                ),
                {'name': _STATEMENT},
            )
        ).one()
    finally:
        await db.execute(text(f'DEALLOCATE {_STATEMENT}'))

    assert (generic, custom) == (0, _EXECUTIONS), (
        f'{compose_file} starts the database with plan_cache_mode={mode}: '
        f'{generic} of {_EXECUTIONS} executions ran a generic plan'
    )


def test_the_demo_starts_the_production_database():
    """The demo file adds to production's services; a ``command`` of its own
    on the database would drop production's settings, this one among them."""
    compose = yaml.safe_load(
        (_REPO_ROOT / 'docker-compose.demo.yml').read_text(encoding='utf-8')
    )
    assert 'command' not in compose['services'].get('db', {})
