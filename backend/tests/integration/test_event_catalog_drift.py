"""CI drift detection: verify committed EVENTS.md matches the generator output.

Same pattern as ``test_core_api_docs_drift.py``: runs the catalog generator and
compares stdout against the committed docs file. ``docker-compose.yml`` mounts
the checkout read-only into the backend container and names it in
``INVENTARI_REPO_ROOT``, so this measures in the container as well as on the
host and in CI.

A missing ``EVENTS.md`` is a failure, not a skip — see that file for why.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
# See test_core_api_docs_drift.py: the parent directory is the repository root
# in a checkout and `/` in the container, which the mount corrects.
_PROJECT_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT') or _BACKEND_DIR.parent)
_GENERATOR_SCRIPT = _BACKEND_DIR / 'scripts' / 'generate_event_catalog.py'
_DOCS_PATH = _PROJECT_ROOT / 'docs' / 'subsystems' / 'EVENTS.md'


@pytest.mark.integration
class TestEventCatalogDrift:
    """Ensure the committed event catalog matches the generator output."""

    def test_docs_are_in_sync_with_generator(self) -> None:
        """Generated markdown must exactly match the committed EVENTS.md."""
        assert _DOCS_PATH.exists(), (
            f'{_DOCS_PATH} is not reachable from here. It is tracked and '
            f'docker-compose.yml mounts it for the backend service, so its '
            f'absence means this check would read nothing while reporting green.'
        )

        gen_result = subprocess.run(
            [sys.executable, str(_GENERATOR_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(_BACKEND_DIR),
        )
        assert gen_result.returncode == 0, (
            f'Generator script failed:\n{gen_result.stderr}'
        )
        generated = gen_result.stdout

        committed = _DOCS_PATH.read_text(encoding='utf-8')

        assert generated.rstrip() == committed.rstrip(), (
            'docs/subsystems/EVENTS.md is out of sync with the generator.\n'
            'Regenerate: `docker compose exec -T backend python '
            'scripts/generate_event_catalog.py > docs/subsystems/EVENTS.md`.'
        )
