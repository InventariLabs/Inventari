"""`scripts/init-env.sh` writes a production `.env` an installer can start from.

The guide used to have the reader run `openssl rand -hex 32` six times and paste
each value; one missed paste is a stack that starts with a blank secret or does
not start at all. The command asks for the two things only the installer knows
(the domain and the e-mail address), generates every secret, and refuses to
touch an `.env` that already exists, because an overwritten `FERNET_SALT` or
`ENCRYPTION_KEY` leaves every stored secret unreadable for good.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

_SH = shutil.which('sh') or '/bin/sh'

_SECRETS = (
    'DB_PASSWORD',
    'DB_APP_PASSWORD',
    'REDIS_PASSWORD',
    'SECRET_KEY',
    'FERNET_SALT',
    'ENCRYPTION_KEY',
)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A minimal install tree: the script, the example it fills, the version."""
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'backend').mkdir()
    shutil.copy(_REPO_ROOT / 'scripts/init-env.sh', tmp_path / 'scripts/init-env.sh')
    shutil.copy(_REPO_ROOT / '.env.production.example', tmp_path)
    shutil.copy(_REPO_ROOT / 'backend/pyproject.toml', tmp_path / 'backend')
    return tmp_path


def _run(checkout: Path, *args: str, stdin: str = '') -> subprocess.CompletedProcess:
    return subprocess.run(
        [_SH, str(checkout / 'scripts/init-env.sh'), *args],
        cwd=checkout,
        input=stdin,
        capture_output=True,
        text=True,
    )


def _values(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.match(r'^([A-Z][A-Z0-9_]*)=(.*)$', line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def test_it_writes_every_secret_and_the_two_answers(checkout: Path):
    result = _run(checkout, '--domain', 'inv.example.com', '--email', 'me@example.com')

    assert result.returncode == 0, result.stderr
    values = _values(checkout / '.env')
    assert values['DOMAIN'] == 'inv.example.com'
    assert values['ACME_EMAIL'] == 'me@example.com'
    secrets = [values[name] for name in _SECRETS]
    for secret in secrets:
        assert re.fullmatch(r'[0-9a-f]{64}', secret), 'a hex secret, URL-safe'
    assert len(set(secrets)) == len(secrets), 'each secret is drawn on its own'


def test_it_pins_the_version_of_the_tree_it_was_run_in(checkout: Path):
    """The images file reads it: the compose file and the images it pulls are
    the same release."""
    _run(checkout, '--domain', 'inv.example.com', '--email', 'me@example.com')

    version = re.search(
        r'^version = "([^"]+)"', (checkout / 'backend/pyproject.toml').read_text(), re.M
    )
    assert version
    assert _values(checkout / '.env')['INVENTARI_VERSION'] == version.group(1)


def test_it_leaves_the_rest_of_the_example_as_it_is(checkout: Path):
    _run(checkout, '--domain', 'inv.example.com', '--email', 'me@example.com')

    example = (checkout / '.env.production.example').read_text().splitlines()
    written = (checkout / '.env').read_text().splitlines()
    assert written[len(example) :][-1].startswith('INVENTARI_VERSION=')
    changed = {
        line.split('=', 1)[0]
        for old, line in zip(example, written, strict=False)
        if old != line
    }
    assert changed == {'DOMAIN', 'ACME_EMAIL', *_SECRETS}


def test_the_file_is_private_to_its_owner(checkout: Path):
    _run(checkout, '--domain', 'inv.example.com', '--email', 'me@example.com')

    mode = stat.S_IMODE((checkout / '.env').stat().st_mode)
    assert mode == 0o600


def test_it_never_overwrites_an_existing_env(checkout: Path):
    env = checkout / '.env'
    env.write_text('FERNET_SALT=keep-me\n', encoding='utf-8')

    result = _run(checkout, '--domain', 'inv.example.com', '--email', 'me@example.com')

    assert result.returncode != 0
    assert '.env' in result.stderr
    assert env.read_text(encoding='utf-8') == 'FERNET_SALT=keep-me\n'


def test_it_asks_for_what_it_was_not_given(checkout: Path):
    result = _run(checkout, stdin='inv.example.com\nme@example.com\n')

    assert result.returncode == 0, result.stderr
    values = _values(checkout / '.env')
    assert values['DOMAIN'] == 'inv.example.com'
    assert values['ACME_EMAIL'] == 'me@example.com'


@pytest.mark.parametrize(
    'domain, email',
    [
        ('https://inv.example.com', 'me@example.com'),
        ('inv.example.com/', 'me@example.com'),
        ('', 'me@example.com'),
        ('inv.example.com', 'not-an-address'),
        ('inv.example.com', ''),
    ],
)
def test_a_wrong_answer_writes_nothing(checkout: Path, domain: str, email: str):
    result = _run(checkout, '--domain', domain, '--email', email)

    assert result.returncode != 0
    assert not (checkout / '.env').exists()


def test_the_guide_uses_the_command_instead_of_the_openssl_lines():
    guide = (_REPO_ROOT / 'QUICK_DEPLOY.md').read_text(encoding='utf-8')

    assert 'scripts/init-env.sh' in guide
    assert 'openssl rand' not in guide
