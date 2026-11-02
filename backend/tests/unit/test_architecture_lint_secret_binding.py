"""Unit tests for the module-secret binding check.

Written the same day as the fix, and deliberately without a baseline: the
tree has no such call site now, so the only thing the gate can ever report
is a new one.
"""

from __future__ import annotations

from pathlib import Path

from app.core.architecture_lint._quality_checks_secrets import (
    _check_module_secret_binding,
)

_UNBOUND = """
from app.core.public_api import core_api


def save(secret):
    return core_api.secrets.encrypt(secret)
"""

_UNBOUND_READ = """
from app.core.public_api import core_api


def read(stored):
    return core_api.secrets.decrypt(stored)
"""

_APP_WIDE_SETTINGS = """
from app.core.public_api import core_api


def save(secret):
    return core_api.settings.encrypt_app_secret(secret)
"""

_BOUND = """
from app.core.public_api import core_api

MODULE_NAME = 'thing'


def save(secret):
    return core_api.secrets.encrypt_for_module(MODULE_NAME, secret)


def read(stored):
    return core_api.secrets.decrypt_for_module(MODULE_NAME, stored)
"""


def _module(tmp_path: Path, source: str, name: str = 'thing') -> Path:
    root = tmp_path / 'modules'
    (root / name).mkdir(parents=True, exist_ok=True)
    (root / name / 'service.py').write_text(source, encoding='utf-8')
    return root


class TestWhatIsRefused:
    def test_the_unbound_write(self, tmp_path: Path):
        findings = _check_module_secret_binding(_module(tmp_path, _UNBOUND))

        assert len(findings) == 1
        assert findings[0].startswith('::error')
        assert 'encrypt_for_module' in findings[0]

    def test_the_unbound_read(self, tmp_path: Path):
        # Reading app-wide is how a module would open somebody else's
        # secret, so it is refused on the same footing as writing one.
        findings = _check_module_secret_binding(_module(tmp_path, _UNBOUND_READ))

        assert len(findings) == 1

    def test_the_app_wide_settings_helper(self, tmp_path: Path):
        findings = _check_module_secret_binding(_module(tmp_path, _APP_WIDE_SETTINGS))

        assert len(findings) == 1


class TestWhatIsAllowed:
    def test_the_bound_pair(self, tmp_path: Path):
        assert _check_module_secret_binding(_module(tmp_path, _BOUND)) == []

    def test_a_module_test_file(self, tmp_path: Path):
        root = tmp_path / 'modules'
        (root / 'thing' / 'tests').mkdir(parents=True)
        (root / 'thing' / 'tests' / 'test_x.py').write_text(_UNBOUND, encoding='utf-8')

        assert _check_module_secret_binding(root) == []
