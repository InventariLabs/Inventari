"""The demo's first rebuild must not run while the backend is still starting.

The rebuild drops the schema and puts it back. The backend, started beside it,
seeds system data and initializes modules as its workers come up — code that
reads and writes the very tables the rebuild is dropping. The migration lock
(``app/cli/_migration_lock.py``) keeps the two from migrating over each other,
but the application's own start-up work is not inside that lock, so the reset
waits for the backend's health check once before it begins.

None of this starts Docker. The file is parsed as text, because the failure
worth catching is a later edit quietly dropping the dependency — the demo then
loses the ordering and the race is back, on the one start nobody watches.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)


def _demo_services() -> dict[str, Any]:
    text = (_REPO_ROOT / 'docker-compose.demo.yml').read_text(encoding='utf-8')
    return yaml.safe_load(text)['services']


class TestTheFirstRebuildWaits:
    def test_the_reset_starts_only_after_the_backend_is_healthy(self) -> None:
        depends_on = _demo_services()['demo-reset']['depends_on']

        assert depends_on['backend'] == {'condition': 'service_healthy'}, (
            'the reset can drop the schema while the backend is seeding on '
            'start-up; it has to wait until the backend answers its health '
            'check once, the way it already waits for the database'
        )
