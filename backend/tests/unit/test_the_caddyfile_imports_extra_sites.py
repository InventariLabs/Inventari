"""An installation can serve a site of its own through the production Caddy.

The Caddyfile ends by importing every ``*.caddy`` file of ``/etc/caddy/extra``
and the production compose file mounts ``CADDY_EXTRA_DIR`` (default
``./caddy-extra``) there, read-only. The hook has to be in these two files and
not in a second compose file: every documented command names
``-f docker-compose.prod.yml``, which makes Compose ignore ``COMPOSE_FILE`` and
the override file, so an addition made there would drop out at the next
update. The directory ships with its README only, so a stack that has no extra
site configures what it always did.

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


def test_caddyfile_ends_by_importing_the_extra_sites() -> None:
    lines = [
        line.strip()
        for line in (_REPO_ROOT / 'Caddyfile').read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.strip().startswith('#')
    ]
    assert lines[-1] == 'import /etc/caddy/extra/*.caddy'


def test_compose_mounts_the_extra_directory_read_only_with_a_default() -> None:
    compose = (_REPO_ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')
    assert re.search(
        r'-\s*\$\{CADDY_EXTRA_DIR:-\./caddy-extra\}:/etc/caddy/extra:ro', compose
    ), 'the proxy must mount the extra directory read-only, with a :- default'


def test_the_extra_directory_ships_with_its_readme_only() -> None:
    # The directory itself may hold a site someone is trying out; what the
    # repository ships is whatever the ignore file lets through.
    assert (_REPO_ROOT / 'caddy-extra' / 'README.md').is_file()
    ignore = (_REPO_ROOT / '.gitignore').read_text(encoding='utf-8')
    assert '/caddy-extra/*' in ignore
    exceptions = [
        line for line in ignore.splitlines() if line.startswith('!/caddy-extra/')
    ]
    assert exceptions == ['!/caddy-extra/README.md']
