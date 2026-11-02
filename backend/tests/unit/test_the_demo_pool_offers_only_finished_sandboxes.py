"""``manage.py demo fill-pool``: what it seeds, in what order, and when it refuses.

The command opens its own database connections, which the test suite cannot
reach, so its collaborators stand in here and the test reads the order of
the calls. The property that matters is that a sandbox is offered to the pool
only once it is onboarded, seeded and dressed: a visitor must never be handed
an organization that is half there.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from typer.testing import CliRunner

import app.cli.commands_demo as commands_demo
import app.database as database
import seed_demo_data
import seed_demo_showcase
from app.config import settings
from app.services import demo_sandbox_service
from app.services.demo_sandbox_service import PoolState

ORG, ADMIN, EMAIL = uuid.uuid4(), uuid.uuid4(), 'visitor-1@sandbox.example.com'


class _NoSession:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_exc: object) -> None:
        return None


@pytest.fixture
def steps(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Every collaborator of one sandbox's seeding, recording what it was asked."""
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(database, 'SessionLocal', _NoSession)
    monkeypatch.setattr(
        commands_demo, 'open_sandbox_account', lambda _db: (ORG, ADMIN, EMAIL)
    )

    async def onboard(email: str) -> None:
        calls.append(('onboard', email))

    async def offer(_db: object, org: uuid.UUID, admin: uuid.UUID) -> None:
        calls.append(('offer', (org, admin)))

    async def run_on_a_session(work: Any) -> Any:
        return await work(object())

    monkeypatch.setattr(commands_demo, '_complete_onboarding', onboard)
    monkeypatch.setattr(commands_demo, '_on_async_db', run_on_a_session)
    monkeypatch.setattr(demo_sandbox_service, 'add_to_pool_async', offer)
    monkeypatch.setattr(
        seed_demo_data,
        'seed_from_cli',
        lambda *, items, admin_email, report: calls.append(
            ('seed', (items, admin_email))
        ),
    )
    monkeypatch.setattr(
        seed_demo_showcase,
        'dress_from_cli',
        lambda *, admin_email, report: calls.append(('dress', admin_email)),
    )
    return calls


def test_a_sandbox_is_offered_only_once_it_is_seeded_and_dressed(steps) -> None:
    commands_demo._seed_one_sandbox(items=7)

    assert steps == [
        ('onboard', EMAIL),
        ('seed', (7, EMAIL)),
        ('dress', EMAIL),
        ('offer', (ORG, ADMIN)),
    ]


def test_a_seed_that_fails_offers_nothing(steps, monkeypatch) -> None:
    def broken(**_kwargs: object) -> None:
        raise RuntimeError('seed failed')

    monkeypatch.setattr(seed_demo_data, 'seed_from_cli', broken)

    with pytest.raises(RuntimeError):
        commands_demo._seed_one_sandbox(items=7)

    assert ('offer', (ORG, ADMIN)) not in steps


def test_fill_pool_seeds_what_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    seeded: list[int] = []
    monkeypatch.setenv(commands_demo.DEMO_MARKER_ENV, 'true')
    monkeypatch.setattr(commands_demo, 'bootstrap_db', lambda: None)
    monkeypatch.setattr(settings, 'DEMO_SANDBOX_POOL_SIZE', 3)
    monkeypatch.setattr(settings, 'DEMO_SANDBOX_DAILY_CAP', 100)

    async def one_waiting(_work: Any) -> PoolState:
        return PoolState(ready=1, claimed=5)

    monkeypatch.setattr(commands_demo, '_on_async_db', one_waiting)
    monkeypatch.setattr(commands_demo, '_seed_one_sandbox', seeded.append)

    result = CliRunner().invoke(commands_demo.demo_app, ['fill-pool', '--items', '9'])

    assert result.exit_code == 0, result.output
    assert seeded == [9, 9]
    assert 'Sandbox 2/2' in result.output


def test_fill_pool_refuses_where_no_demo_was_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded: list[int] = []
    monkeypatch.delenv(commands_demo.DEMO_MARKER_ENV, raising=False)
    monkeypatch.setattr(commands_demo, '_seed_one_sandbox', seeded.append)

    result = CliRunner().invoke(commands_demo.demo_app, ['fill-pool'])

    assert result.exit_code == 1
    assert seeded == []


class _Session:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


async def test_the_work_is_committed_on_an_engine_of_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    monkeypatch.setattr(database, 'init_async_engine', lambda: None)
    monkeypatch.setattr(database, 'AsyncSessionLocal', lambda: session)

    async def work(db: _Session) -> str:
        assert db is session
        return 'done'

    assert await commands_demo._on_async_db(work) == 'done'
    assert session.committed


async def test_no_engine_is_a_loud_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, 'init_async_engine', lambda: None)
    monkeypatch.setattr(database, 'AsyncSessionLocal', None)

    async def work(_db: object) -> None:
        return None

    with pytest.raises(RuntimeError):
        await commands_demo._on_async_db(work)
