"""Backups of the production database run with or without an encryption key.

They also carry the uploaded files — photographs and attachments live in a
volume of their own, and a backup of the database alone restores records whose
pictures are gone. Each run archives that volume next to the dump, under the
same key or the same root-only mode, with the same retention.

A key demanded at startup makes the first deployment harder and, worse, makes
people produce one only to get past the check — and keep it nowhere. So an
empty ``AGE_RECIPIENT`` now means plain, root-only dumps and a warning at every
run, a key means ciphertext only, and nothing plain ever leaves the host.

The scripts run for real here, against stand-ins for the three tools that need
a server or a key — ``pg_dump``, ``psql`` and ``age`` — so what is pinned is
the script's own decisions: which file it writes, what it says, what it deletes
and when it refuses. That ``age`` really decrypts what it encrypted, and that a
dump really loads, was measured once against a live Postgres and the real
``age`` of the backup image. The scripts are run by ``bash`` because they rely
on ``pipefail``, which the Alpine shell they ship for has and Debian's ``dash``
may not.
"""

from __future__ import annotations

import gzip
import io
import os
import re
import shutil
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_BACKUP = _REPO_ROOT / 'docker' / 'backup'
_BASH = shutil.which('bash') or '/bin/bash'

_DUMP = '-- the database, as pg_dump prints it\nCREATE TABLE widgets (id int);\n'
_KEY = 'age1examplepublickeyexamplepublickeyexamplepublickeyexamplepublic0'
_SECRET = 'AGE-SECRET-KEY-1EXAMPLEEXAMPLEEXAMPLE'

# pg_dump prints _DUMP, or fails when FAIL_DUMP is set.
_PG_DUMP = f"""#!/bin/sh
[ -z "${{FAIL_DUMP:-}}" ] || exit 1
printf '%s' '{_DUMP}'
"""

# age: encrypting writes a marker line and then whatever it was fed, and keeps
# the recipient it was given; decrypting (-i - with a key on stdin) only works
# when the key on stdin is a secret key.
_AGE = """#!/bin/sh
case "$1" in
  --encrypt)
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --recipient) printf '%s' "$2" > "$STUB_DIR/recipient"; shift ;;
        --output) out="$2"; shift ;;
      esac
      shift
    done
    { printf 'age-stub\\n'; cat; } > "$out" ;;
  --decrypt)
    grep -q 'AGE-SECRET-KEY' || { echo "age: error: no secret keys found" >&2; exit 1; }
    for last; do :; done
    tail -n +2 "$last" ;;
esac
"""

# psql: counting tables answers 3, a command (DROP/CREATE DATABASE) does nothing,
# anything else is the dump being loaded and is kept for the test to read.
_PSQL = """#!/bin/sh
case "$*" in
  *information_schema*) echo "${STUB_TABLES:-3}" ;;
  *" -c "*) : ;;
  *) cat > "$STUB_DIR/loaded" ;;
esac
"""


# What the uploads volume holds: a photograph in a nested folder and an attachment.
_UPLOADS = {
    'items/7/photo.jpg': b'\xff\xd8 a photograph',
    'invoice.pdf': b'%PDF an invoice',
}


@pytest.fixture
def stubs(tmp_path: Path) -> Path:
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name, body in (('pg_dump', _PG_DUMP), ('age', _AGE), ('psql', _PSQL)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    for name, content in _UPLOADS.items():
        path = tmp_path / 'uploads' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return tmp_path


def _run(
    script: str,
    stubs: Path,
    *,
    key: str = '',
    stdin: str = '',
    **env: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_BASH, str(_BACKUP / script)],
        env={
            'PATH': f'{stubs / "bin"}:{os.environ.get("PATH", "")}',
            'STUB_DIR': str(stubs),
            'BACKUP_DIR': str(stubs / 'backups'),
            'BACKUP_ONCE': 'true',
            'POSTGRES_HOST': 'db',
            'POSTGRES_DB': 'shop',
            'POSTGRES_USER': 'admin',
            'POSTGRES_PASSWORD': 'x',
            'AGE_RECIPIENT': key,
            'UPLOADS_DIR': str(stubs / 'uploads'),
            **env,
        },
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _backup(stubs: Path, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return _run('backup.sh', stubs, **kwargs)


def _last(stubs: Path, kind: str = '.sql.gz') -> list[Path]:
    """The backups of one kind in last/: dumps (``.sql.gz``) or file archives (``.tar.gz``)."""
    last = (stubs / 'backups' / 'last').iterdir()
    return sorted(
        p
        for p in last
        if p.is_file()
        and not p.is_symlink()
        and kind in p.name
        and not p.name.endswith('.part')
    )


def _members(archive: bytes) -> dict[str, bytes]:
    """The regular files of a gzipped tar, by their path inside it."""
    members: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        for member in tar.getmembers():
            content = tar.extractfile(member) if member.isfile() else None
            if content is not None:
                members[member.name.removeprefix('./')] = content.read()
    return members


class TestWithoutAKey:
    def test_the_stack_still_backs_up_and_says_the_dump_is_plain(
        self, stubs: Path
    ) -> None:
        result = _backup(stubs)

        assert result.returncode == 0, result.stderr
        (dump,) = _last(stubs)
        assert dump.name.endswith('.sql.gz')
        assert gzip.decompress(dump.read_bytes()).decode() == _DUMP
        assert 'UNENCRYPTED' in result.stdout
        assert 'make backup-key' in result.stdout

    def test_the_plain_dump_is_readable_by_its_owner_only(self, stubs: Path) -> None:
        _backup(stubs)

        (dump,) = _last(stubs)
        assert dump.stat().st_mode & 0o077 == 0

    def test_a_failed_dump_leaves_no_backup_and_a_failing_exit(
        self, stubs: Path
    ) -> None:
        result = _backup(stubs, FAIL_DUMP='1')

        assert result.returncode != 0
        assert _last(stubs, kind='') == []


class TestWithAKey:
    def test_the_dump_is_encrypted_to_that_key_and_no_plain_one_is_written(
        self, stubs: Path
    ) -> None:
        result = _backup(stubs, key=_KEY)

        assert result.returncode == 0, result.stderr
        (dump,) = _last(stubs)
        assert dump.name.endswith('.sql.gz.age')
        assert (stubs / 'recipient').read_text() == _KEY
        marker, _, body = dump.read_bytes().partition(b'\n')
        assert marker == b'age-stub'
        assert gzip.decompress(body).decode() == _DUMP
        assert 'UNENCRYPTED' not in result.stdout
        assert not list((stubs / 'backups').rglob('*.sql.gz'))

    def test_the_first_encrypted_backup_replaces_a_plain_newest_one(
        self, stubs: Path
    ) -> None:
        _backup(stubs)
        _backup(stubs, key=_KEY)

        (dump,) = _last(stubs)
        assert dump.name.endswith('.sql.gz.age')
        latest = stubs / 'backups' / 'last' / 'shop-latest.sql.gz.age'
        assert latest.resolve() == dump
        assert not (stubs / 'backups' / 'last' / 'shop-latest.sql.gz').is_symlink()


class TestTheUploadedFiles:
    def test_a_run_archives_them_next_to_the_dump_readable_by_root_only(
        self, stubs: Path
    ) -> None:
        result = _backup(stubs)

        assert result.returncode == 0, result.stderr
        (archive,) = _last(stubs, kind='.tar.gz')
        assert archive.name.startswith('uploads-')
        assert archive.name.endswith('.tar.gz')
        assert _members(archive.read_bytes()) == _UPLOADS
        assert archive.stat().st_mode & 0o077 == 0
        latest = stubs / 'backups' / 'last' / 'uploads-latest.tar.gz'
        assert latest.resolve() == archive

    def test_with_a_key_they_are_encrypted_to_it_and_never_written_plain(
        self, stubs: Path
    ) -> None:
        result = _backup(stubs, key=_KEY)

        assert result.returncode == 0, result.stderr
        (archive,) = _last(stubs, kind='.tar.gz')
        assert archive.name.endswith('.tar.gz.age')
        marker, _, body = archive.read_bytes().partition(b'\n')
        assert marker == b'age-stub'
        assert _members(body) == _UPLOADS
        assert not list((stubs / 'backups').rglob('*.tar.gz'))

    def test_an_empty_volume_is_an_archive_of_nothing_not_a_failure(
        self, stubs: Path
    ) -> None:
        shutil.rmtree(stubs / 'uploads')
        (stubs / 'uploads').mkdir()

        result = _backup(stubs)

        assert result.returncode == 0, result.stderr
        (archive,) = _last(stubs, kind='.tar.gz')
        assert _members(archive.read_bytes()) == {}

    def test_an_unreadable_volume_fails_the_run_and_keeps_the_dump(
        self, stubs: Path
    ) -> None:
        result = _backup(stubs, UPLOADS_DIR=str(stubs / 'not-mounted'))

        assert result.returncode != 0
        assert len(_last(stubs)) == 1
        assert _last(stubs, kind='.tar.gz') == []
        assert 'NOT in this backup' in result.stdout

    def test_turning_the_key_on_keeps_one_archive_and_both_latest_links(
        self, stubs: Path
    ) -> None:
        _backup(stubs)
        _backup(stubs, key=_KEY)

        last = stubs / 'backups' / 'last'
        (archive,) = _last(stubs, kind='.tar.gz')
        assert archive.name.endswith('.tar.gz.age')
        assert (last / 'uploads-latest.tar.gz.age').resolve() == archive
        assert (last / 'shop-latest.sql.gz.age').is_symlink()
        assert not (last / 'uploads-latest.tar.gz').is_symlink()

    def test_they_are_kept_by_day_week_and_month_and_rotated_like_the_dumps(
        self, stubs: Path
    ) -> None:
        daily = stubs / 'backups' / 'daily'
        daily.mkdir(parents=True)
        stale = daily / 'uploads-20200101.tar.gz'
        stale.write_bytes(b'')
        month_ago = time.time() - 31 * 86400
        os.utime(stale, (month_ago, month_ago))

        result = _backup(stubs)

        assert result.returncode == 0, result.stderr
        assert not stale.exists()
        for folder in ('daily', 'weekly', 'monthly'):
            (kept,) = (stubs / 'backups' / folder).glob('uploads-*.tar.gz')
            assert _members(kept.read_bytes()) == _UPLOADS


class TestVerify:
    def _verify(self, stubs: Path, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _run('verify.sh', stubs, **kwargs)

    def test_a_plain_backup_is_loaded_and_the_success_is_recorded(
        self, stubs: Path
    ) -> None:
        _backup(stubs)

        result = self._verify(stubs)

        assert result.returncode == 0, result.stderr
        assert (stubs / 'loaded').read_text() == _DUMP
        when, name, mode, _files = (
            (stubs / 'backups' / 'last-verified').read_text().strip().split('\t')
        )
        assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', when)
        assert name.endswith('.sql.gz')
        assert mode == 'plain'

    def test_an_encrypted_backup_needs_the_private_key_on_stdin(
        self, stubs: Path
    ) -> None:
        _backup(stubs, key=_KEY)

        without = self._verify(stubs, stdin='')

        assert without.returncode != 0
        assert not (stubs / 'backups' / 'last-verified').exists()

        with_key = self._verify(stubs, stdin=_SECRET + '\n')

        assert with_key.returncode == 0, with_key.stderr
        assert (stubs / 'loaded').read_text() == _DUMP
        record = (stubs / 'backups' / 'last-verified').read_text().strip().split('\t')
        assert record[2] == 'encrypted'

    def test_a_dump_that_restores_no_tables_is_not_a_success(self, stubs: Path) -> None:
        _backup(stubs)

        result = self._verify(stubs, STUB_TABLES='0')

        assert result.returncode != 0
        assert not (stubs / 'backups' / 'last-verified').exists()

    def test_the_files_archive_is_read_and_recorded_with_the_dump(
        self, stubs: Path
    ) -> None:
        _backup(stubs)

        result = self._verify(stubs)

        assert result.returncode == 0, result.stderr
        record = (stubs / 'backups' / 'last-verified').read_text().strip().split('\t')
        assert record[3].startswith('uploads-')
        assert record[3].endswith('.tar.gz')
        assert '2 files' in result.stdout

    def test_an_encrypted_dump_and_archive_take_the_key_once(self, stubs: Path) -> None:
        _backup(stubs, key=_KEY)

        result = self._verify(stubs, stdin=_SECRET + '\n')

        assert result.returncode == 0, result.stderr
        record = (stubs / 'backups' / 'last-verified').read_text().strip().split('\t')
        assert record[3].endswith('.tar.gz.age')
        assert '2 files' in result.stdout

    def test_a_backup_without_the_files_is_not_a_success(self, stubs: Path) -> None:
        _backup(stubs)
        for archive in _last(stubs, kind='.tar.gz'):
            archive.unlink()

        result = self._verify(stubs)

        assert result.returncode != 0
        assert 'uploaded files' in result.stderr
        assert not (stubs / 'backups' / 'last-verified').exists()

    def test_a_files_archive_that_does_not_read_is_not_a_success(
        self, stubs: Path
    ) -> None:
        _backup(stubs)
        (archive,) = _last(stubs, kind='.tar.gz')
        archive.write_bytes(b'not a gzip stream')

        result = self._verify(stubs)

        assert result.returncode != 0
        assert not (stubs / 'backups' / 'last-verified').exists()

    def test_no_backup_yet_is_a_failure(self, stubs: Path) -> None:
        (stubs / 'backups' / 'last').mkdir(parents=True)

        result = self._verify(stubs)

        assert result.returncode != 0
        assert 'no backup' in result.stderr


class TestStatus:
    def _status(self, stubs: Path, key: str = '') -> str:
        result = _run('status.sh', stubs, key=key)
        assert result.returncode == 0, result.stderr
        return result.stdout

    def test_a_fresh_install_reads_off_and_never(self, stubs: Path) -> None:
        _backup(stubs)

        out = self._status(stubs)

        assert 'encryption:     OFF' in out
        assert 'restore check:  never' in out

    def test_a_proven_restore_shows_its_time_and_kind(self, stubs: Path) -> None:
        _backup(stubs, key=_KEY)
        _run('verify.sh', stubs, key=_KEY, stdin=_SECRET + '\n')

        out = self._status(stubs, key=_KEY)

        assert 'encryption:     on' in out
        assert re.search(r'restore check:  \d{4}-.*\.sql\.gz\.age, encrypted\)', out)
        assert 'never' not in out

    def test_a_check_made_before_the_key_does_not_vouch_for_the_key(
        self, stubs: Path
    ) -> None:
        _backup(stubs)
        _run('verify.sh', stubs)

        out = self._status(stubs, key=_KEY)

        assert 'verify again with the key' in out

    def test_the_newest_files_archive_is_named(self, stubs: Path) -> None:
        _backup(stubs)

        out = self._status(stubs)

        assert re.search(r'newest files:   uploads-\d{8}-\d{6}\.tar\.gz, 0 h old', out)
        assert 'files check:    never' in out

    def test_a_backup_holding_no_files_says_so(self, stubs: Path) -> None:
        _backup(stubs)
        for archive in _last(stubs, kind='.tar.gz'):
            archive.unlink()

        out = self._status(stubs)

        assert 'newest files:   none' in out

    def test_a_proven_files_archive_shows_with_the_restore_check(
        self, stubs: Path
    ) -> None:
        _backup(stubs)
        _run('verify.sh', stubs)

        out = self._status(stubs)

        assert re.search(r'files check:    uploads-.*\.tar\.gz read back', out)


def _compose() -> dict[str, Any]:
    text = (_REPO_ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')
    return yaml.safe_load(text)['services']


def _healthy(stubs: Path) -> bool:
    """Runs the db-backup healthcheck, as compose has it, against the stub's backups."""
    test = _compose()['db-backup']['healthcheck']['test'][1]
    command = test.replace('/backups/last', str(stubs / 'backups' / 'last'))
    return (
        subprocess.run(['/bin/sh', '-c', command], check=False, timeout=30).returncode
        == 0
    )


class TestTheHealthcheck:
    def test_a_fresh_backup_is_healthy(self, stubs: Path) -> None:
        assert _backup(stubs).returncode == 0

        assert _healthy(stubs)

    def test_a_link_to_an_archive_that_is_gone_is_not_a_backup(
        self, stubs: Path
    ) -> None:
        """last/ holds a -latest link beside each backup; the link alone proves nothing."""
        assert _backup(stubs).returncode == 0
        (archive,) = _last(stubs, kind='.tar.gz')
        archive.unlink()

        assert (stubs / 'backups' / 'last' / 'uploads-latest.tar.gz').is_symlink()
        assert not _healthy(stubs)

    def test_a_link_to_a_dump_that_is_gone_is_not_a_backup(self, stubs: Path) -> None:
        assert _backup(stubs).returncode == 0
        (dump,) = _last(stubs)
        dump.unlink()

        assert not _healthy(stubs)


class TestWiring:
    def test_the_key_is_not_a_startup_requirement(self) -> None:
        services = _compose()

        assert ':?' not in services['db-backup']['environment']['AGE_RECIPIENT']
        assert ':?' not in services['db-backup-offsite']['environment']['AGE_RECIPIENT']

    def test_the_offsite_copy_refuses_plain_backups_and_sends_only_ciphertext(
        self,
    ) -> None:
        command = ' '.join(_compose()['db-backup-offsite']['command'])

        assert '[ -z "$$AGE_RECIPIENT" ]' in command
        assert '--include "*.age"' in command

    def test_the_offsite_command_refuses_without_a_key_and_copies_only_ciphertext(
        self, tmp_path: Path
    ) -> None:
        """Runs the service's own command, as compose composes it, with a stand-in rclone.

        The stand-in honours ``--include`` the way rclone does (only matching
        names are copied), so what lands in the remote is what the real filter
        would let through.
        """
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        # rclone sync <src> <dst> --include <glob> ...: copies the files whose name matches.
        (bin_dir / 'rclone').write_text(
            """#!/bin/sh
src="$2"; dst="$3"; glob="*"
shift 3
while [ "$#" -gt 0 ]; do
  [ "$1" = "--include" ] && { glob="$2"; shift; }
  shift
done
mkdir -p "$dst"
for f in "$src"/*; do
  case "$(basename "$f")" in $glob) cp "$f" "$dst"/ ;; esac
done
"""
        )
        # One pass is enough: the loop's sleep ends the shell running it.
        (bin_dir / 'sleep').write_text('#!/bin/sh\nkill $PPID\n')
        for stub in bin_dir.iterdir():
            stub.chmod(0o755)
        backups = tmp_path / 'backups'
        backups.mkdir()
        (backups / 'shop-1.sql.gz').write_text('plain dump left from before the key')
        (backups / 'shop-1.sql.gz.age').write_text('ciphertext')
        (backups / 'uploads-1.tar.gz.age').write_text('ciphertext')
        remote = tmp_path / 'remote'
        # compose passes `$$` through as a literal `$`.
        command = ' '.join(_compose()['db-backup-offsite']['command']).replace(
            '$$', '$'
        )

        def run(**env: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ['/bin/sh', '-c', command.replace('/backups', str(backups))],
                env={'PATH': f'{bin_dir}:{os.environ.get("PATH", "")}', **env},
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        no_remote = run(BACKUP_RCLONE_REMOTE='', AGE_RECIPIENT=_KEY)
        assert no_remote.returncode == 1
        assert 'BACKUP_RCLONE_REMOTE is empty' in no_remote.stderr

        plain = run(BACKUP_RCLONE_REMOTE=str(remote), AGE_RECIPIENT='')
        assert plain.returncode == 1
        assert 'AGE_RECIPIENT is empty' in plain.stderr
        assert not remote.exists()

        encrypted = run(BACKUP_RCLONE_REMOTE=str(remote), AGE_RECIPIENT=_KEY)
        assert encrypted.returncode != 1, encrypted.stderr
        assert sorted(p.name for p in remote.iterdir()) == [
            'shop-1.sql.gz.age',
            'uploads-1.tar.gz.age',
        ]

    def test_the_healthcheck_counts_a_plain_backup_as_fresh(self) -> None:
        test = _compose()['db-backup']['healthcheck']['test'][1]

        assert "-name '*.sql.gz'" in test
        assert "-name '*.sql.gz.age'" in test

    def test_the_backup_reads_the_volume_the_backend_writes_and_only_reads_it(
        self,
    ) -> None:
        services = _compose()

        assert 'uploads_data:/app/uploads' in services['backend']['volumes']
        assert 'uploads_data:/uploads:ro' in services['db-backup']['volumes']

    def test_the_healthcheck_wants_a_fresh_files_archive_too(self) -> None:
        test = _compose()['db-backup']['healthcheck']['test'][1]

        assert "-name '*.tar.gz'" in test
        assert "-name '*.tar.gz.age'" in test

    def test_the_put_back_procedure_names_the_files_the_backup_writes(self) -> None:
        """The guide restores by the -latest names; a rename in the script strands it."""
        guide = (_REPO_ROOT / 'DEPLOYMENT.md').read_text(encoding='utf-8')
        script = (_BACKUP / 'backup.sh').read_text(encoding='utf-8')

        assert 'publish uploads tar.gz' in script
        assert 'ln -sfn "$file" "$BACKUP_DIR/last/${name}-latest.${ext}"' in script
        assert '/backups/$FROM/uploads-latest.tar.gz.age' in guide
        assert '/backups/$FROM/inventari_db-latest.sql.gz.age' in guide

    def test_the_commands_are_there_and_the_image_carries_their_scripts(self) -> None:
        makefile = (_REPO_ROOT / 'Makefile').read_text(encoding='utf-8')
        dockerfile = (_BACKUP / 'Dockerfile').read_text(encoding='utf-8')

        for target in ('backup-key', 'backup-verify', 'backup-status'):
            assert re.search(rf'^{target}:', makefile, flags=re.MULTILINE)
        assert 'verify.sh' in dockerfile
        assert 'status.sh' in dockerfile
        assert shutil.which('sh')

    def test_the_example_and_the_quickstart_do_not_list_the_key_as_required(
        self,
    ) -> None:
        example = (_REPO_ROOT / '.env.production.example').read_text(encoding='utf-8')
        quick = (_REPO_ROOT / 'QUICK_DEPLOY.md').read_text(encoding='utf-8')
        block = re.search(r'```env\n(.*?)```', quick, flags=re.DOTALL)

        assert re.search(r'^AGE_RECIPIENT=$', example, flags=re.MULTILINE)
        assert 'REQUIRED' not in example.split('AGE_RECIPIENT=')[0].split('\n\n')[-1]
        assert block is not None
        assert 'AGE_RECIPIENT' not in block.group(1)
