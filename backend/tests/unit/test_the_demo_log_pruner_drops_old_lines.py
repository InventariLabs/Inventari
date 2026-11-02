"""The demo's logs are held for a bounded time (docs/DEMO.md, "Logs")."""

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
REPO = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
SCRIPT = REPO / 'scripts' / 'demo-prune-logs.sh'
SH = shutil.which('sh') or '/bin/sh'


def _line(age_days: float, text: str) -> str:
    when = datetime.now(UTC) - timedelta(days=age_days)
    # Compact, the way the Docker daemon writes a line.
    return json.dumps(
        {
            'log': text + '\n',
            'stream': 'stdout',
            'time': when.strftime('%Y-%m-%dT%H:%M:%S.%f') + '000Z',
        },
        separators=(',', ':'),
    )


def _prune(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SH, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


def test_a_line_older_than_the_period_is_gone_and_a_newer_one_stays(tmp_path):
    log = tmp_path / 'c-json.log'
    log.write_text(
        '\n'.join(
            [
                _line(9, '203.0.113.7 GET /old'),
                _line(7.5, '203.0.113.8 GET /just-over'),
                _line(6.5, '203.0.113.9 GET /just-under'),
                _line(0.1, '203.0.113.10 GET /fresh'),
                'not json, so it has no time and stays',
            ]
        )
        + '\n'
    )
    inode = log.stat().st_ino

    result = _prune('7', str(log))

    assert result.returncode == 0, result.stderr
    kept = log.read_text()
    assert '/old' not in kept
    assert '/just-over' not in kept
    assert '/just-under' in kept
    assert '/fresh' in kept
    assert 'not json' in kept
    # Rewritten in place: the daemon appends to the file it already holds.
    assert log.stat().st_ino == inode


def test_the_period_is_the_first_argument(tmp_path):
    log = tmp_path / 'c-json.log'
    log.write_text(_line(2, 'two days old') + '\n' + _line(0.1, 'fresh') + '\n')

    assert _prune('1', str(log)).returncode == 0

    kept = log.read_text()
    assert 'two days old' not in kept
    assert 'fresh' in kept


def test_a_period_that_is_not_a_number_is_refused(tmp_path):
    log = tmp_path / 'c-json.log'
    log.write_text(_line(30, 'old') + '\n')

    result = _prune('a week', str(log))

    assert result.returncode == 2
    assert 'old' in log.read_text()


def test_the_containers_are_stopped_while_their_logs_are_rewritten(tmp_path):
    """The daemon appends without a lock, so a running container's log is not rewritten."""
    log = tmp_path / 'c-json.log'
    log.write_text(_line(30, 'old') + '\n' + _line(0.1, 'fresh') + '\n')
    calls = tmp_path / 'calls'
    shim = tmp_path / 'bin' / 'docker'
    shim.parent.mkdir()
    shim.write_text(
        f"""#!/bin/sh
case "$1" in
    ps) case "$*" in *service=demo-reset*) ;; *) echo abc123 ;; esac ;;
    inspect) echo "{log}" ;;
    stop) echo "stop: $(grep -c old "{log}") old lines" >> "{calls}" ;;
    start) echo "start: $(grep -c old "{log}") old lines" >> "{calls}" ;;
esac
"""
    )
    shim.chmod(0o755)

    result = subprocess.run(
        [SH, str(SCRIPT), '7'],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, 'PATH': f'{shim.parent}:{os.environ["PATH"]}'},
    )

    assert result.returncode == 0, result.stderr
    # Stopped before the rewrite (the old line still there), started after it.
    assert calls.read_text().splitlines() == [
        'stop: 1 old lines',
        'start: 0 old lines',
    ]


def test_a_log_rotated_as_the_container_stops_is_pruned_too(tmp_path):
    """The files are listed once nothing writes, so a rotation during the stop is seen."""
    log = tmp_path / 'c-json.log'
    rotated = tmp_path / 'c-json.log.1'
    log.write_text(_line(0.1, 'fresh') + '\n')
    shim = tmp_path / 'bin' / 'docker'
    shim.parent.mkdir()
    # The daemon rotates the active file while the container is being stopped.
    shim.write_text(
        f"""#!/bin/sh
case "$1" in
    ps) case "$*" in *service=demo-reset*) ;; *) echo abc123 ;; esac ;;
    inspect) echo "{log}" ;;
    stop) cp "{log}" "{rotated}"
          printf '%s\\n' '{_line(30, 'old')}' > "{log}"
          cat "{rotated}" >> "{log}"
          printf '%s\\n' '{_line(30, 'old')}' > "{rotated}" ;;
esac
"""
    )
    shim.chmod(0o755)

    result = subprocess.run(
        [SH, str(SCRIPT), '7'],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, 'PATH': f'{shim.parent}:{os.environ["PATH"]}'},
    )

    assert result.returncode == 0, result.stderr
    assert 'old' not in rotated.read_text()
    assert 'fresh' in log.read_text()


def test_the_reset_service_is_paused_not_restarted(tmp_path):
    """Starting demo-reset rebuilds the demo, so pruning must not stop it."""
    log = tmp_path / 'c-json.log'
    log.write_text(_line(30, 'old') + '\n' + _line(0.1, 'fresh') + '\n')
    calls = tmp_path / 'calls'
    shim = tmp_path / 'bin' / 'docker'
    shim.parent.mkdir()
    shim.write_text(
        f"""#!/bin/sh
case "$1" in
    ps)
        case "$*" in
            *service=demo-reset*) echo reset1 ;;
            *) echo web1; echo reset1 ;;
        esac ;;
    inspect) echo "{log}" ;;
    *) echo "$1 $(echo $* | cut -d' ' -f2-): $(grep -c old "{log}") old lines" >> "{calls}" ;;
esac
"""
    )
    shim.chmod(0o755)

    result = subprocess.run(
        [SH, str(SCRIPT), '7'],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, 'PATH': f'{shim.parent}:{os.environ["PATH"]}'},
    )

    assert result.returncode == 0, result.stderr
    # Only the web container is stopped and started; the reset one never is.
    assert calls.read_text().splitlines() == [
        'stop web1: 1 old lines',
        'pause reset1: 1 old lines',
        'unpause reset1: 0 old lines',
        'start web1: 0 old lines',
    ]
