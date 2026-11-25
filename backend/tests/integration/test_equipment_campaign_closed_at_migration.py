"""The equipment revision that adds ``closed_at`` fills it for closed campaigns only.

A campaign closed before the column existed keeps the moment it closed from
``updated_at``: that is what lets its record tell a return made before the
close from a later custody move. These tests run the revision's ``upgrade``
against a scratch ``audit_campaigns`` (a temporary table that shadows the real
one for the session) holding a campaign of every status.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from app.core.module_migrations import module_migrations_dir

pytestmark = pytest.mark.integration

_CLOSED_AT = datetime(2026, 3, 4, 12, 30, 15, 123456, tzinfo=UTC)
_STATUSES = ('DRAFT', 'ACTIVE', 'COMPLETED', 'CANCELLED')


@pytest.fixture(scope='module')
def revision():
    path = module_migrations_dir('equipment') / 'versions' / '011_campaign_closed_at.py'
    spec = importlib.util.spec_from_file_location(
        'equipment_011_campaign_closed_at', Path(path)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def campaigns(db_session):
    """A scratch ``audit_campaigns`` with one row per status, as it was before."""
    conn = db_session.connection()
    conn.execute(
        text(
            'CREATE TEMP TABLE audit_campaigns '
            '(id serial PRIMARY KEY, status text, updated_at timestamptz)'
        )
    )
    for status in _STATUSES:
        conn.execute(
            text('INSERT INTO audit_campaigns (status, updated_at) VALUES (:s, :u)'),
            {'s': status, 'u': _CLOSED_AT},
        )
    return conn


def _closed_at(conn) -> dict[str, datetime | None]:
    return dict(
        conn.execute(text('SELECT status, closed_at FROM audit_campaigns')).all()
    )


def test_upgrade_takes_the_close_moment_from_updated_at_of_closed_campaigns_only(
    revision, campaigns
):
    with Operations.context(MigrationContext.configure(campaigns)):
        revision.upgrade()

    assert _closed_at(campaigns) == {
        'DRAFT': None,
        'ACTIVE': None,
        'COMPLETED': _CLOSED_AT,
        'CANCELLED': _CLOSED_AT,
    }


def test_downgrade_drops_the_column(revision, campaigns):
    with Operations.context(MigrationContext.configure(campaigns)):
        revision.upgrade()
        revision.downgrade()

    columns = {
        row[0]
        for row in campaigns.execute(
            text(
                'SELECT column_name FROM information_schema.columns '
                "WHERE table_name = 'audit_campaigns' "
                "AND table_schema LIKE 'pg_temp%'"
            )
        )
    }
    assert 'closed_at' not in columns
    assert 'updated_at' in columns
