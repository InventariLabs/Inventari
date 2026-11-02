"""Exported backup keys stay out of git; the scripts that make them do not."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
REPO = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
GIT = shutil.which('git') or '/usr/bin/git'


def test_backup_key_exports_are_ignored_without_hiding_generator_scripts(tmp_path):
    """Key exports stay private while existing and future generators stay visible."""
    shutil.copyfile(REPO / '.gitignore', tmp_path / '.gitignore')
    subprocess.run([GIT, 'init', '-q', str(tmp_path)], check=True)
    paths = [
        'backup-key.txt',
        'exports/backup-key-recovery.txt',
        'scripts/backup-key.sh',
        'scripts/backup-key-new.sh',
    ]
    result = subprocess.run(
        [GIT, 'check-ignore', '--no-index', *paths],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == paths[:2]
