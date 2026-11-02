"""A development bind mount names a directory, never a single file.

A file bind pins the host file's inode. Git replaces a file by writing a new
one and renaming it over the old, so after any checkout or merge the running
container keeps reading the deleted original — ``/proc/self/mountinfo`` shows
``//deleted`` — and a check that reads it fails against content nobody has
anymore. A restart does not help (same mount namespace); only recreating the
container does. A directory bind follows the replacement, so the services
mount the directory and read the file by path inside it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)


def _file_binds(compose_file: str) -> list[str]:
    compose = yaml.safe_load((_REPO_ROOT / compose_file).read_text(encoding='utf-8'))
    found: list[str] = []
    for service, spec in (compose.get('services') or {}).items():
        for volume in spec.get('volumes') or []:
            if not isinstance(volume, str):
                continue
            source = volume.split(':', 1)[0]
            if not source.startswith(('.', '/')):
                continue  # a named volume
            if (_REPO_ROOT / source).is_file():
                found.append(f'{service}: {volume}')
    return found


def test_no_bind_mount_names_a_regular_file():
    assert _file_binds('docker-compose.yml') == []
