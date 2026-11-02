"""A deployment with no www record must still start Caddy.

Compose exports ``WWW_DOMAIN`` to the proxy container whatever ``.env`` says.
Caddy applies the default in ``{$WWW_DOMAIN:...}`` only when the variable is
absent, not when it is exported empty — and an empty site address turns the
block into a key-less one, which Caddy rejects as misplaced global
configuration, so the whole proxy fails to start. The fallback therefore has to
live in the compose file, where ``:-`` also covers a value that is set but empty.

Nothing here starts Docker; the files are parsed as text.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)


def test_compose_exports_a_non_empty_www_address_when_unset() -> None:
    compose = (_REPO_ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')
    match = re.search(r'WWW_DOMAIN=\$\{WWW_DOMAIN:-([^}]*)\}', compose)
    assert match is not None, 'the proxy must get WWW_DOMAIN with a :- fallback'
    assert match.group(1).strip(), 'an empty fallback leaves a key-less Caddy block'


def test_caddyfile_keeps_a_default_for_the_www_address() -> None:
    caddyfile = (_REPO_ROOT / 'Caddyfile').read_text(encoding='utf-8')
    assert re.search(r'\{\$WWW_DOMAIN:[^}]+\}', caddyfile)


def test_compose_exports_a_non_empty_demo_address_when_unset() -> None:
    compose = (_REPO_ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')
    match = re.search(r'DEMO_DOMAIN=\$\{DEMO_DOMAIN:-([^}]*)\}', compose)
    assert match is not None, 'the proxy must get DEMO_DOMAIN with a :- fallback'
    assert match.group(1).strip(), 'an empty fallback leaves a key-less Caddy block'


def test_caddyfile_keeps_a_default_for_the_demo_address() -> None:
    caddyfile = (_REPO_ROOT / 'Caddyfile').read_text(encoding='utf-8')
    assert re.search(r'\{\$DEMO_DOMAIN:[^}]+\}', caddyfile)


def test_the_shared_host_demo_publishes_no_port_and_joins_the_edge_network() -> None:
    shared = _REPO_ROOT / 'docker-compose.demo-shared.yml'
    compose = shared.read_text(encoding='utf-8')
    assert re.search(r'ports: !reset \[\]', compose)
    assert 'inventari-edge' in compose


def test_the_standalone_demo_keeps_its_public_ports() -> None:
    compose = (_REPO_ROOT / 'docker-compose.demo.yml').read_text(encoding='utf-8')
    assert '!reset' not in compose
    assert 'inventari-edge' not in compose
