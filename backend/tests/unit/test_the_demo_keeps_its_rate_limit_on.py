"""The public demo runs with the rate limiter on, per API key.

A visitor's AI agent calls the demo's MCP endpoint with a key issued in the
visitor's sandbox, and the one bound on how hard it can hammer the instance is
the application's general limit, which counts an API-key request against the
key (``app.core.limiter``). ``LOAD_TESTING=true`` switches that limiter off:
the development and pool stacks set it, so a load test measures the
application rather than the limiter. The demo is the production compose file
with ``docker-compose.demo.yml`` on top, and the production backend has no
``env_file:`` — a variable reaches it only when one of the two files names
it. So the limiter stays on as long as neither file names ``LOAD_TESTING``
for the backend or hands it an ``env_file:`` that could, which is what this
test pins: docs/DEMO.md tells visitors the limit their agent meets.

None of this starts Docker; the files are parsed as text.
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

#: The files a demo is started with (docs/DEMO.md, "Starting one").
_DEMO_STACK = ('docker-compose.prod.yml', 'docker-compose.demo.yml')


def _backend(compose_file: str) -> dict[str, Any]:
    text = (_REPO_ROOT / compose_file).read_text(encoding='utf-8')
    return yaml.safe_load(text)['services'].get('backend') or {}


def _named(environment: Any) -> set[str]:
    if isinstance(environment, dict):
        return set(environment)
    return {str(entry).split('=', 1)[0] for entry in environment or []}


class TestTheDemoBackendKeepsTheLimiter:
    @pytest.mark.parametrize('compose_file', _DEMO_STACK)
    def test_no_file_switches_the_limiter_off(self, compose_file: str) -> None:
        backend = _backend(compose_file)

        assert 'LOAD_TESTING' not in _named(backend.get('environment')), (
            f'{compose_file} hands the demo backend LOAD_TESTING, which turns '
            f'the rate limiter off for every visitor and their agents'
        )
        assert 'env_file' not in backend, (
            f'{compose_file} gives the backend an env_file, so a LOAD_TESTING '
            f'in .env would reach the demo unseen'
        )
