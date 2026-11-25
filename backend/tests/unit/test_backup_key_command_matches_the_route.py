"""`make backup-key` prints the recreate command of the route the install runs.

On the published images `-f docker-compose.prod.yml` reads the build file
alone, so the command it would print builds the backup image on the server.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

_FAKE_DOCKER = """#!/bin/sh
if [ "$1" = run ]; then
    printf '# public key: age1fake\\nAGE-SECRET-KEY-FAKE\\n'
fi
"""


def _run_backup_key(tmp_path: Path, env_file: str | None) -> str:
    sh = shutil.which('sh')
    if sh is None:
        pytest.skip('no sh')
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copy(_REPO_ROOT / 'scripts' / 'backup-key.sh', scripts / 'backup-key.sh')
    (tmp_path / 'docker' / 'backup').mkdir(parents=True)
    if env_file is not None:
        (tmp_path / '.env').write_text(env_file, encoding='utf-8')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    docker = bin_dir / 'docker'
    docker.write_text(_FAKE_DOCKER, encoding='utf-8')
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    result = subprocess.run(
        [sh, str(scripts / 'backup-key.sh')],
        env={'PATH': f'{bin_dir}:{os.environ["PATH"]}'},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_the_images_route_gets_the_bare_command(tmp_path: Path) -> None:
    out = _run_backup_key(
        tmp_path,
        'COMPOSE_FILE=docker-compose.prod.yml:docker-compose.images.yml\n',
    )

    assert 'AGE_RECIPIENT=age1fake' in out
    assert 'Recreate the backup job:   docker compose up -d db-backup' in out
    assert '-f docker-compose.prod.yml' not in out


def test_the_build_route_keeps_the_file_flag(tmp_path: Path) -> None:
    out = _run_backup_key(tmp_path, 'DOMAIN=example.com\n')

    assert (
        'Recreate the backup job:   docker compose -f docker-compose.prod.yml '
        'up -d db-backup' in out
    )


def test_without_an_env_file_both_commands_are_named(tmp_path: Path) -> None:
    out = _run_backup_key(tmp_path, None)

    assert 'docker compose -f docker-compose.prod.yml up -d db-backup' in out
    assert 'published images' in out
