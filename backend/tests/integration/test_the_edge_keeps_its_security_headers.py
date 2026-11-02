"""Tree guard: an nginx block with a header of its own must repeat the security set.

nginx drops *every* inherited ``add_header`` directive as soon as a location
declares one of its own. The mistake compiles and the edge answers — only
without CSP, X-Frame-Options and the rest, on exactly the routes nobody curls
twice. ``frontend/nginx.conf`` had two such locations (``= /sw.js`` and the
static-asset regex) until this guard existed; the live ``curl -sI`` proves the
build it ran against, this test proves the next diff, including a new location
that quietly adds a cache header.

The rule lives in ``backend/scripts/check_edge_public_routes.py`` — one
implementation, three readers: this test, ``make lint`` on the host, and
``pytest`` inside the backend container. ``INVENTARI_REPO_ROOT`` names the
checkout in the container (``docker-compose.yml`` mounts it at ``/repo``).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_CHECKER = (
    Path(__file__).resolve().parents[2] / 'scripts' / 'check_edge_public_routes.py'
)


def _load_checker():
    spec = importlib.util.spec_from_file_location('check_edge_public_routes', _CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo_root() -> Path:
    return Path(os.environ.get('INVENTARI_REPO_ROOT') or _CHECKER.parents[2])


@pytest.mark.integration
class TestTheEdgeKeepsItsSecurityHeaders:
    """Locations with their own add_header must carry the full security set."""

    def test_every_add_header_block_repeats_the_security_set(self) -> None:
        nginx = _repo_root() / 'frontend' / 'nginx.conf'
        assert nginx.exists(), (
            f'{nginx} is not reachable, so this check would measure nothing; run on '
            'the host, or point INVENTARI_REPO_ROOT at the checkout — '
            'docker-compose.yml mounts it for the backend service.'
        )
        problems = _load_checker().check_nginx_security_headers(nginx.read_text())
        assert not problems, (
            'an nginx block that sets its own header drops the server-level security '
            'headers from its responses:\n  ' + '\n  '.join(problems)
        )

    def test_the_check_refuses_a_location_that_drops_the_policy(self) -> None:
        """Prove the guard has teeth: the old file shape must stay red."""
        checker = _load_checker()
        server_headers = '\n'.join(
            f'    add_header {name} "value" always;'
            for name in checker.SECURITY_HEADERS
        )
        drifting = f"""server {{
{server_headers}
    location = /sw.js {{
        add_header Cache-Control "no-cache";
    }}
}}"""
        problems = checker.check_nginx_security_headers(drifting)
        assert any('/sw.js' in problem for problem in problems), (
            'the check passed a location that kept only Cache-Control: '
            + repr(problems)
        )
