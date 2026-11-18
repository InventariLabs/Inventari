"""What the migrations build for the tables that grow, read on a migrated database.

The test databases come from ``create_all``, which leaves out the indexes the
models do not declare, the outbox's partial one among them. So the plans are
asked of a database the chain built, the one production runs.
"""

from __future__ import annotations

import json
import math
import uuid
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select

from app.core.db_isolation import isolated_db_url
from app.core.outbox_relay import unpublished_batch
from app.services.notification_service import NotificationService

pytestmark = pytest.mark.integration


def _plan(engine: Engine, stmt: Select) -> str:
    sql = stmt.compile(
        dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}
    )
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(f'EXPLAIN (FORMAT JSON) {sql}').scalar_one()
    return json.dumps(rows)


def _add_user(conn, user_id: uuid.UUID) -> None:
    conn.execute(
        text(
            'INSERT INTO users (id, email, hashed_password, created_at, '
            'updated_at, role) VALUES (:id, :email, :password, now(), now(), '
            "'user')"
        ),
        {'id': user_id, 'email': f'{user_id}@example.com', 'password': 'x'},
    )


def test_the_reads_of_the_growing_tables_ride_their_indexes(monkeypatch):
    user_id = uuid.uuid4()
    with isolated_db_url('retention') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO event_outbox (id, event, payload, published_at) '
                    "SELECT gen_random_uuid(), 'e', '{}', "
                    'CASE WHEN n > 5 THEN now() END '
                    'FROM generate_series(1, 5000) n'
                )
            )
            _add_user(conn, user_id)
            conn.execute(
                text(
                    'INSERT INTO notifications '
                    '(id, user_id, title, content, type, is_read, created_at) '
                    "SELECT gen_random_uuid(), :user, 't', 'c', 'info', n > 5, "
                    "now() - n * interval '1 minute' "
                    'FROM generate_series(1, 5000) n'
                ),
                {'user': user_id},
            )
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            conn.execute(text('ANALYZE event_outbox'))
            conn.execute(text('ANALYZE notifications'))

        relay = _plan(engine, unpublished_batch(100))
        inbox = _plan(
            engine,
            NotificationService._for_user(user_id, unread_only=True).limit(50),
        )
        engine.dispose()

    assert 'ix_event_outbox_unpublished' in relay
    assert 'Seq Scan' not in relay
    assert 'ix_notifications_user_read_created' in inbox
    assert 'Seq Scan' not in inbox


def test_stored_ai_costs_become_exact_numbers_and_back(monkeypatch):
    """Every float the column can hold survives, or reads as an unknown cost.

    A value no cost can be must not stop the upgrade: the entrypoint migrates
    before the backend starts, so a refused cast keeps the whole instance down.
    """
    org_id = uuid.uuid4()
    costs = {
        'tenth': 0.1,
        'under_a_millionth': 0.0000004,
        'absent': None,
        'not_a_number': math.nan,
        'infinite': math.inf,
        'too_large': 1e9,
    }
    config = Config('alembic.ini')
    with isolated_db_url('retention') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(config, 'notifinbox01')
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO organizations '
                    '(id, name, created_at, enabled_modules, settings) '
                    "VALUES (:id, 'Org', now(), '[]', '{}')"
                ),
                {'id': org_id},
            )
            for model, cost in costs.items():
                conn.execute(
                    text(
                        'INSERT INTO ai_usage_logs (id, organization_id, model_name, '
                        'prompt_tokens, completion_tokens, total_tokens, '
                        'estimated_cost_usd, created_at) VALUES (:id, :org, :model, '
                        '0, 0, 0, :cost, now())'
                    ),
                    {'id': uuid.uuid4(), 'org': org_id, 'model': model, 'cost': cost},
                )

        def stored() -> dict[str, object]:
            with engine.connect() as conn:
                rows = conn.execute(
                    text('SELECT model_name, estimated_cost_usd FROM ai_usage_logs')
                ).all()
            return dict(rows)

        command.upgrade(config, 'head')
        upgraded = stored()
        command.downgrade(config, 'notifinbox01')
        downgraded = stored()
        engine.dispose()

    assert upgraded == {
        'tenth': Decimal('0.1000000000'),
        'under_a_millionth': Decimal('0.0000004000'),
        'absent': None,
        'not_a_number': None,
        'infinite': None,
        'too_large': None,
    }
    assert downgraded['tenth'] == 0.1
    assert isinstance(downgraded['tenth'], float)
