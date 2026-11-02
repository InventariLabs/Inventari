"""Code that opens its own ``SessionLocal`` reaches the test database.

``app.database`` builds its sync engine when it is imported, from whatever
``settings.DATABASE_URL`` says at that moment, and the suite's conftest imports
it before pointing that setting at the worker database. Until the conftest
rebound the engine, ``SessionLocal`` kept talking to the database the
environment names: on a developer's stack that is the development database, so
a test committing through it wrote into somebody's working data and passed; in
CI it is an empty database, so the same test failed on a missing table.

The assertion is made against the server, not against the engine's URL: the
database a connection actually lands in is the fact that matters, and it is the
one a stale engine would get wrong.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import SessionLocal


def test_session_local_connects_to_the_database_the_suite_set_up(setup_test_db):
    with SessionLocal() as session:
        landed = session.execute(text('SELECT current_database()')).scalar_one()

    assert landed == make_url(settings.DATABASE_URL).database, (
        f'SessionLocal opened {landed!r}, not the worker database the suite '
        f'provisioned — a commit through it would land outside the test run'
    )
