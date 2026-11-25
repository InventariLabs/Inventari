"""Every demo world build leaves the application's async pool without its connections.

A module seeder opens a session on the application's own async engine, on a
loop of its own that closes when the build ends. A client a test started
before the world was built pools those connections on the dead loop, and the
first request that reaches the pool directly fails with "attached to a
different loop". The pooled sandboxes and the seeded organization are both
built through the same step, so the drop belongs to that step, not to one of
the builds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app import database
from tests.integration import _demo_world

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    'build',
    [
        pytest.param(lambda db: [], id='any-build'),
        pytest.param(
            _demo_world.seeded_organization(items=3), id='seeded-organization'
        ),
    ],
)
def test_a_world_build_drops_the_pool_without_closing_its_connections(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    build: Any,
) -> None:
    disposals: list[bool] = []
    real_dispose = Engine.dispose

    def record(self: Engine, close: bool = True) -> None:
        disposals.append(close)
        real_dispose(self, close=close)

    monkeypatch.setattr(database, 'async_engine', None)
    monkeypatch.setattr(database, 'AsyncSessionLocal', database.AsyncSessionLocal)
    database.init_async_engine()
    monkeypatch.setattr(Engine, 'dispose', record)

    _demo_world._build(db_session, tmp_path / 'world', build)

    # The seeded organization's build replaces the engine it started with; the
    # one it leaves behind is the one whose pool must be empty.
    assert disposals
    assert disposals[-1] is False
