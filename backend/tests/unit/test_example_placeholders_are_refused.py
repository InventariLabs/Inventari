"""No placeholder from the shipped example files starts a production backend.

``.env.example`` promised that its placeholders are refused outside debug
mode, and only one of them was: ``change-me-generate-with-openssl-rand-hex-32``
passed as a SECRET_KEY (long enough, not on the weak list), the
``CHANGE_ME_...`` values of ``backend/.env.example`` were on no list at all, and
nothing looked at the database password. A copied file started a server whose
JWTs anyone holding the repository could sign.

Every assignment in the three files whose value carries the placeholder
marker — commented-out ones included, since uncommenting is what they are
there for — is fed to a fresh configuration with DEBUG off, and each must be
refused by name.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: The checkout. ``docker-compose.yml`` mounts it at ``/repo`` and names it in
#: ``INVENTARI_REPO_ROOT``; on the host it is three levels above this file.
_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_EXAMPLES = ('.env.example', '.env.production.example', 'backend/.env.example')
_ASSIGNMENT = re.compile(r'^#?\s*([A-Z][A-Z0-9_]*)=(\S+)')

_VALID = {
    'SECRET_KEY': 'a-valid-random-key-that-is-long-enough-abc123xyz',
    'FERNET_SALT': 'a-valid-random-salt-that-is-long-enough',
}


def _placeholders() -> list[tuple[str, str, str]]:
    found = []
    for name in _EXAMPLES:
        for line in (_ROOT / name).read_text(encoding='utf-8').splitlines():
            match = _ASSIGNMENT.match(line)
            if match and re.search('change[-_]me', match.group(2), re.IGNORECASE):
                found.append((name, match.group(1), match.group(2)))
    return found


@pytest.fixture(autouse=True)
def _the_module_is_put_back():
    """The reload leaves a new ``settings`` in ``app.config``; put the old one back
    (the reason is spelled out in ``test_config.py``)."""
    import app.config as mod

    before = dict(mod.__dict__)
    yield
    mod.__dict__.clear()
    mod.__dict__.update(before)


def test_the_files_still_carry_placeholders():
    """Guards the parametrisation below against reading nothing."""
    names = {variable for _file, variable, _value in _placeholders()}

    assert {'SECRET_KEY', 'FERNET_SALT', 'DB_PASSWORD', 'DATABASE_URL'} <= names


@pytest.mark.parametrize(
    ('example', 'variable', 'value'),
    _placeholders(),
    ids=[f'{example}:{variable}' for example, variable, _ in _placeholders()],
)
def test_a_placeholder_is_refused_by_name(monkeypatch, example, variable, value):
    for name, valid in _VALID.items():
        monkeypatch.setenv(name, valid)
    monkeypatch.setenv(variable, value)
    monkeypatch.setenv('DEBUG', 'false')
    monkeypatch.delenv('TESTING', raising=False)

    import app.config as mod

    with pytest.raises(ValueError, match=rf'\b{variable}\b'):
        importlib.reload(mod)
