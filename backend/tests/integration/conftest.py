"""Fixtures shared by the integration tests."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.models.user import User
from tests.integration import _demo_world


@pytest.fixture
def demo_world(
    db_session: Session, tmp_path_factory: pytest.TempPathFactory, worker_id: str
) -> Callable[[str, Callable[[Session], Any]], Any]:
    """``demo_world(key, build)``: a seeded demo organization, put back for this test.

    See ``tests/integration/_demo_world.py``: the seed is built once per run
    and copied in for each test, which then owns its copy.
    """
    base = tmp_path_factory.getbasetemp()
    # Under xdist every worker has a base of its own inside the run's one.
    shared = (base if worker_id == 'master' else base.parent) / 'demo-worlds'

    def restore(key: str, build: Callable[[Session], Any]) -> Any:
        return _demo_world.restore(db_session, shared, key, build)

    return restore


@pytest.fixture
def two_sandboxes(
    demo_world, async_engine_fixture, db_session: Session
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Two visitors' organizations, each with its administrator, seeded and dressed.

    Made the way ``demo fill-pool`` makes them, and handed out: each
    administrator is active, as claiming a sandbox leaves it.
    """
    payload = demo_world(
        'pooled-sandboxes', _demo_world.pooled_sandboxes(async_engine_fixture)
    )
    opened = [_demo_world.ids(pair) for pair in payload]
    for _org_id, user_id in opened:
        admin = db_session.get(User, user_id)
        assert admin is not None
        admin.is_active = True  # what handing it to a visitor does
    db_session.commit()
    return opened
