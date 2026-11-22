"""The production server's logs outlive a deploy, and a copy leaves the host.

Docker's json-file log is deleted with the container, and every deploy
recreates the containers; journald keeps the lines on the host instead.
``scripts/export-logs.sh`` is the copy that leaves it: one encrypted file per
UTC day, pruned after the stated retention, which the offsite copy sends to the
same destination as the backups. The script runs for real here, against
stand-ins for ``journalctl`` and ``age``, so what is pinned is the script's own
decisions: which day it writes, when it skips, what it deletes and when it
refuses. That journald keeps a removed container's lines and its replacement's
was measured once with the real driver; ``age`` is a stand-in here, as in the
backup test, and production uses the same binary and key the backup image runs.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_SCRIPT = _REPO_ROOT / 'scripts' / 'export-logs.sh'
_BASH = shutil.which('bash') or '/bin/bash'
_KEY = 'age1examplepublickeyexamplepublickeyexamplepublickeyexamplepublic0'

# journalctl: records the day it was asked for, prints one line for it, and
# prints nothing when that day's start is named in EMPTY_DAYS. FAIL_JOURNALCTL
# makes it exit non-zero, as a run without access to the journal would.
_JOURNALCTL = """#!/bin/sh
since=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --since) since="$2"; shift ;;
  esac
  shift
done
printf '%s\\n' "$since" >> "$STUB_DIR/calls"
[ -z "${FAIL_JOURNALCTL:-}" ] || { echo "journalctl: failed" >&2; exit 1; }
case " ${EMPTY_DAYS:-} " in
  *" $since "*) exit 0 ;;
esac
echo "2026-01-01T00:00:00+00:00 host app[1]: entry for $since"
"""

# age: writes a marker line and then whatever it was fed.
_AGE = """#!/bin/sh
while [ "$#" -gt 0 ]; do
  case "$1" in
    --recipient) printf '%s' "$2" > "$STUB_DIR/recipient"; shift ;;
    --output) out="$2"; shift ;;
  esac
  shift
done
{ printf 'age-stub\\n'; cat; } > "$out"
"""


@pytest.fixture
def stubs(tmp_path: Path) -> Path:
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name, body in (('journalctl', _JOURNALCTL), ('age', _AGE)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    return tmp_path


def _day(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime('%Y-%m-%d')


def _start(days_ago: int) -> str:
    """The UTC epoch journalctl is asked for, as the script computes it."""
    day = datetime.now(UTC) - timedelta(days=days_ago)
    midnight = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return str(int(midnight.timestamp()))


def _run(
    stubs: Path,
    *,
    key: str = _KEY,
    keep: str = '3',
    days: str | None = None,
    **env: str,
) -> subprocess.CompletedProcess[str]:
    command = [_BASH, str(_SCRIPT)]
    if days is not None:
        command.append(days)
    return subprocess.run(
        command,
        cwd=_REPO_ROOT,
        env={
            'PATH': f'{stubs / "bin"}:{os.environ.get("PATH", "")}',
            'STUB_DIR': str(stubs),
            'LOG_DIR': str(stubs / 'logs'),
            'LOG_RETENTION_DAYS': keep,
            'AGE_RECIPIENT': key,
            **env,
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _files(stubs: Path) -> list[str]:
    logs = stubs / 'logs'
    if not logs.is_dir():
        return []
    return sorted(path.name for path in logs.iterdir())


def _decrypt(path: Path) -> str:
    raw = path.read_bytes()
    prefix = b'age-stub\n'
    assert raw.startswith(prefix), raw[:40]
    return gzip.decompress(raw[len(prefix) :]).decode()


class TestTheDailyExport:
    def test_one_encrypted_file_is_written_for_each_day_of_the_retention(
        self, stubs: Path
    ) -> None:
        result = _run(stubs)

        assert result.returncode == 0, result.stderr
        assert _files(stubs) == [
            f'journal-{_day(3)}.log.gz.age',
            f'journal-{_day(2)}.log.gz.age',
            f'journal-{_day(1)}.log.gz.age',
        ]
        # The day is the one the file is named after, not today.
        text = _decrypt(stubs / 'logs' / f'journal-{_day(1)}.log.gz.age')
        assert f'entry for @{_start(1)}' in text
        # The journal holds visitors' addresses: root only, like the archives.
        assert (stubs / 'logs').stat().st_mode & 0o077 == 0
        assert (
            stubs / 'logs' / f'journal-{_day(1)}.log.gz.age'
        ).stat().st_mode & 0o077 == 0

    def test_the_file_carries_the_day_asked_for_and_the_recipient_it_was_given(
        self, stubs: Path
    ) -> None:
        assert _run(stubs).returncode == 0

        assert (stubs / 'recipient').read_text() == _KEY
        assert f'entry for @{_start(2)}' in _decrypt(
            stubs / 'logs' / f'journal-{_day(2)}.log.gz.age'
        )

    def test_a_day_already_exported_is_left_alone(self, stubs: Path) -> None:
        """The daily run writes yesterday; the backfill does not rewrite a file."""
        (stubs / 'logs').mkdir()
        existing = stubs / 'logs' / f'journal-{_day(1)}.log.gz.age'
        existing.write_bytes(b'kept as it was')

        assert _run(stubs).returncode == 0

        assert existing.read_bytes() == b'kept as it was'
        calls = (stubs / 'calls').read_text().split()
        assert f'@{_start(1)}' not in calls
        assert f'@{_start(2)}' in calls

    def test_a_day_the_journal_has_nothing_for_leaves_no_empty_file(
        self, stubs: Path
    ) -> None:
        result = _run(stubs, EMPTY_DAYS=f'@{_start(2)}')

        assert result.returncode == 0, result.stderr
        assert f'journal-{_day(2)}.log.gz.age' not in _files(stubs)
        assert f'journal-{_day(1)}.log.gz.age' in _files(stubs)
        assert f'journal-{_day(3)}.log.gz.age' in _files(stubs)

    def test_files_older_than_the_retention_are_deleted_and_newer_ones_kept(
        self, stubs: Path
    ) -> None:
        (stubs / 'logs').mkdir()
        old = stubs / 'logs' / 'journal-2000-01-01.log.gz.age'
        old.write_bytes(b'age-stub\nold')
        today = stubs / 'logs' / f'journal-{_day(0)}.log.gz.age'
        today.write_bytes(b'age-stub\nnew')

        assert _run(stubs, keep='3').returncode == 0

        assert not old.exists()
        assert today.exists()
        assert len(_files(stubs)) == 4  # today's plus three kept days

    def test_a_name_that_is_not_a_day_is_neither_deleted_nor_mistaken_for_one(
        self, stubs: Path
    ) -> None:
        (stubs / 'logs').mkdir()
        other = stubs / 'logs' / 'journal-not-a-day.log.gz.age'
        other.write_bytes(b'not ours')

        assert _run(stubs).returncode == 0

        assert other.exists()

    def test_a_journalctl_that_fails_writes_no_archive(self, stubs: Path) -> None:
        result = _run(stubs, FAIL_JOURNALCTL='1')

        assert result.returncode != 0
        assert _files(stubs) == []


class TestWhatTheScriptRefuses:
    def test_without_a_recipient_nothing_is_written(self, stubs: Path) -> None:
        result = _run(stubs, key='')

        assert result.returncode == 1
        assert 'AGE_RECIPIENT is empty' in result.stderr
        assert _files(stubs) == []

    def test_a_retention_that_is_not_a_whole_number_is_refused(
        self, stubs: Path
    ) -> None:
        result = _run(stubs, keep='a month')

        assert result.returncode == 2
        assert 'LOG_RETENTION_DAYS' in result.stderr
        assert _files(stubs) == []


def _compose(name: str = 'docker-compose.prod.yml') -> dict:
    return yaml.safe_load((_REPO_ROOT / name).read_text(encoding='utf-8'))['services']


class TestWiring:
    def test_every_production_service_logs_to_the_host_journal(self) -> None:
        """Not one json-file log survives a deploy, so none of them is used."""
        for name, service in _compose().items():
            assert service['logging']['driver'] == 'journald', name
            assert service['logging']['options']['tag'] == '{{.Name}}', name

    def test_the_demo_keeps_its_own_bounded_json_file_logs(self) -> None:
        """The pruner rewrites json files in place; journald has no files to rewrite."""
        demo = _compose('docker-compose.demo.yml')

        assert demo['backend']['logging']['driver'] == 'json-file'
        assert demo['backend']['logging']['options']['max-size'] == '10m'
        assert demo['backend']['environment']['LOG_RETENTION_DAYS'] == '7'

    def test_the_offsite_copy_carries_the_exported_logs_beside_the_backups(
        self,
    ) -> None:
        service = _compose()['db-backup-offsite']
        command = ' '.join(service['command'])

        assert './logs:/logs:ro' in service['volumes']
        assert '"$$BACKUP_RCLONE_REMOTE/backups"' in command
        # One bucket: the logs fall in beside the backups. A different
        # retention for logs and backups means a second bucket, and then
        # LOGS_RCLONE_REMOTE names it.
        assert '"$${LOGS_RCLONE_REMOTE:-$$BACKUP_RCLONE_REMOTE/logs}"' in command
        assert 'LOGS_RCLONE_REMOTE' in service['environment']
        assert command.count('--include "*.age"') == 2

    def test_the_exported_logs_are_not_sent_into_the_backups_sync(self) -> None:
        """Each sync owns one subtree, so neither can delete the other's files."""
        command = ' '.join(_compose()['db-backup-offsite']['command'])

        assert 'rclone sync /backups "$$BACKUP_RCLONE_REMOTE/backups"' in command
        assert 'rclone sync /logs "$$logs_remote"' in command

    def test_the_guide_sets_the_retention_and_the_size_cap_on_the_host(self) -> None:
        guide = (_REPO_ROOT / 'DEPLOYMENT.md').read_text(encoding='utf-8')

        assert 'MaxRetentionSec=30day' in guide
        assert 'SystemMaxUse=2G' in guide
        assert 'scripts/export-logs.sh' in guide

    def test_the_bucket_lock_is_shorter_than_the_retention_it_protects(self) -> None:
        """A 30-day Compliance lock would outlive the 30-day deletion promise.

        A day's journal is uploaded the next day, so the lock has to end before
        the local file goes; the lifecycle rule removes the noncurrent version
        once it has. The backups have no such promise and get the longer lock.
        """
        guide = (_REPO_ROOT / 'DEPLOYMENT.md').read_text(encoding='utf-8')

        assert 'Compliance, 21 days' in guide
        assert 'Compliance, 30 days' in guide
        assert 'NoncurrentVersionExpiration' in guide
        assert '"NoncurrentDays": 1' in guide
        assert 'cleanup-hidden' in guide

    def test_the_logs_can_have_their_own_destination(self) -> None:
        guide = (_REPO_ROOT / 'DEPLOYMENT.md').read_text(encoding='utf-8')

        assert 'LOGS_RCLONE_REMOTE' in guide
        assert 'BACKUP_RCLONE_REMOTE/logs' in guide

    def test_the_example_names_the_retention_the_privacy_page_states(self) -> None:
        example = (_REPO_ROOT / '.env.production.example').read_text(encoding='utf-8')

        assert 'LOG_RETENTION_DAYS=30' in example
        assert 'BACKUP_RCLONE_REMOTE=' in example
        assert 'LOGS_RCLONE_REMOTE=' in example

    def test_the_exported_logs_never_enter_the_checkout(self) -> None:
        ignore = (_REPO_ROOT / '.gitignore').read_text(encoding='utf-8')

        assert 'logs/' in ignore.splitlines()

    def test_the_demo_states_the_period_its_pruner_keeps(self) -> None:
        """The page and the host must say the same number."""
        pruner = (_REPO_ROOT / 'scripts' / 'demo-prune-logs.sh').read_text(
            encoding='utf-8'
        )
        demo = _compose('docker-compose.demo.yml')

        assert 'days="${1:-7}"' in pruner
        assert demo['backend']['environment']['LOG_RETENTION_DAYS'] == '7'
