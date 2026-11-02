"""Fixtures shared by the integration tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.orm import Session

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
