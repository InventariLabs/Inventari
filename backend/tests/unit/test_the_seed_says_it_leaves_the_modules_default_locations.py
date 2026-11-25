"""The demo seed says out loud that it does not seed a module's default locations.

The module declares starter storage locations, but enabling it without a user
skips them, and the seed builds its own hierarchy (a ``Main Warehouse`` among
it) that would only duplicate them. The module logs the skip; the run's own
output carries it too, so the omission is a decision a reader can see rather
than a warning in a log.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

import seed_demo_data
from app import database
from app.services import module_lifecycle_service


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def commit(self) -> None:
        return None


def test_the_run_reports_that_the_default_locations_are_not_seeded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    enabled: list[Any] = []

    async def _enable(modules: Any, organization_id: Any, *, db: Any, user: Any = None):
        enabled.append((list(modules), user))

    monkeypatch.setattr(module_lifecycle_service, 'enable_modules_async', _enable)
    monkeypatch.setattr(database, 'init_async_engine', lambda: None)
    monkeypatch.setattr(database, 'AsyncSessionLocal', lambda: _Session())

    seed_demo_data._ensure_module_catalogues(uuid.uuid4())

    out = capsys.readouterr().out
    assert [m.metadata.name for m in enabled[0][0]] == ['equipment']
    assert enabled[0][1] is None
    assert 'default storage locations: not seeded' in out
