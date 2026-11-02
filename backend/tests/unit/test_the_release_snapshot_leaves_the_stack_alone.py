"""Cutting a release snapshot reaches nothing of the stack it runs beside.

``scripts/release-db-snapshot.sh`` seeds a scratch database through
``manage.py demo reset``, which is destructive by design: it empties the
uploaded files — with object storage, every object in the configured bucket —
and the public demo inbox. The script runs that reset inside the developer's
own backend container, so whatever storage and inbox that container is
configured with are the ones the reset would empty.
"""

import os
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
REPO = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
SCRIPT = REPO / 'scripts' / 'release-db-snapshot.sh'
BASH = shutil.which('bash') or '/bin/bash'


def _backend_environment(tmp_path) -> dict[str, str]:
    """The ``-e`` overrides the script hands the backend container.

    ``docker`` and ``git`` are stand-ins that log their arguments; the backend
    call fails, so the script stops before it would write a snapshot into the
    tree.
    """
    log = tmp_path / 'docker.log'
    docker = tmp_path / 'docker'
    docker.write_text(
        '#!/bin/sh\n'
        'for arg in "$@"; do printf "%s\\n" "$arg"; done >> "$DOCKER_LOG"\n'
        'echo --- >> "$DOCKER_LOG"\n'
        'case "$*" in *" backend "*) exit 71 ;; esac\n'
    )
    git = tmp_path / 'git'
    git.write_text('#!/bin/sh\necho 0000000\n')
    for stub in (docker, git):
        stub.chmod(0o755)

    result = subprocess.run(
        [BASH, str(SCRIPT)],
        cwd=tmp_path,
        env={
            **os.environ,
            'PATH': f'{tmp_path}:{os.environ["PATH"]}',
            'DOCKER_LOG': str(log),
            'VERSION': '0.0.0-test',
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, 'the stand-in backend call should stop the script'

    calls = [call.strip().split('\n') for call in log.read_text().split('---')]
    (backend,) = [args for args in calls if 'backend' in args]
    env = {}
    for flag, value in pairwise(backend):
        if flag == '-e':
            name, _, setting = value.partition('=')
            env[name] = setting
    return env


def test_the_reset_keeps_its_uploads_on_a_local_directory_of_its_own(tmp_path):
    env = _backend_environment(tmp_path)

    assert env.get('FILE_STORAGE_BACKEND') == 'local'
    # Not the stack's own upload directory (``config.py``, compose).
    assert env.get('FILE_STORAGE_LOCAL_PATH') not in (None, '', '/app/uploads')


def test_the_reset_has_no_demo_inbox_to_empty(tmp_path):
    env = _backend_environment(tmp_path)

    assert env.get('DEMO_INBOX_API_URL') == ''


def test_the_reset_migrates_the_scratch_database_only(tmp_path):
    env = _backend_environment(tmp_path)

    assert env.get('MIGRATION_DATABASE_URL') == ''
