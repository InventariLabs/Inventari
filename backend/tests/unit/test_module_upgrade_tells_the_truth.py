"""An upgrade whose migrations failed must not read as a completed one.

The tracking entry used to be written before the module's migrations ran,
so a failure — or a kill mid-flight — left the tracking saying v0.2.0 while
the schema sat wherever the failure left it, on every surface an operator
reads. The entry is now written only after the migrations succeed: until
then it keeps naming the old version, the one the schema can actually
answer for, and a retry of the same package walks the forward path — no
flag to read, no force to pass, no hand-edited database to recover.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli import _module_meta, _module_upgrade


@pytest.fixture
def tracking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / 'tracking.json'
    path.write_text(
        json.dumps(
            {
                'modules': {
                    'demo_mod': {
                        'version': '0.1.0',
                        'source': './pkg',
                        'has_backend': True,
                        'has_frontend': False,
                        'declares_frontend': False,
                        'requires': [],
                    }
                }
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', path)
    return path


def _run_upgrade(
    tracking: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    migrations: str,
) -> None:
    """Drive _do_upgrade with the filesystem and the migration step faked."""
    source = tracking.parent / 'pkg'
    (source / 'backend').mkdir(parents=True, exist_ok=True)
    (source / 'module.yaml').write_text(
        json.dumps(
            {
                'name': 'demo_mod',
                'version': '0.2.0',
                'components': {'backend': True, 'frontend': False},
                'requires': [],
                'inventari_min_version': '0.0.0',
            }
        ),
        encoding='utf-8',
    )

    def fake_swap(name, source_dir, meta):
        return True, False

    def fake_migrations(name):
        if migrations == 'fail':
            # The real runner catches the migration's own error, prints the
            # honest summary and exits — the exit is what the caller sees.
            raise SystemExit(1)
        return None

    monkeypatch.setattr(
        _module_upgrade,
        '_parse_module_yaml',
        lambda d: {
            'name': 'demo_mod',
            'version': '0.2.0',
            'components': {'backend': True, 'frontend': False},
            'requires': [],
            'inventari_min_version': '0.0.0',
        },
    )
    monkeypatch.setattr(
        'app.cli.module_packaging._verify_package_signature',
        lambda *a, **k: {
            'signature_status': 'unsigned',
            'signature_key_id': '',
            'signature_verified_at': None,
        },
    )
    monkeypatch.setattr(_module_upgrade, '_swap_module_files', fake_swap)
    monkeypatch.setattr(
        _module_upgrade, '_run_module_migrations_after_upgrade', fake_migrations
    )

    _module_upgrade._do_upgrade(
        source,
        original_source='./pkg',
        source_rev=None,
        source_commit=None,
        signature_file=None,
        allow_unsigned=True,
        force=False,
    )


class TestTheEntryWaitsForTheSchema:
    def test_a_failed_migration_leaves_the_entry_at_the_old_version(
        self,
        tracking: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        with pytest.raises(SystemExit):
            _run_upgrade(tracking, monkeypatch, migrations='fail')

        entry = json.loads(tracking.read_text(encoding='utf-8'))['modules']['demo_mod']
        assert entry['version'] == '0.1.0'
        assert 'upgraded_at' not in entry

    def test_a_successful_upgrade_records_the_new_version(
        self,
        tracking: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        _run_upgrade(tracking, monkeypatch, migrations='ok')

        entry = json.loads(tracking.read_text(encoding='utf-8'))['modules']['demo_mod']
        assert entry['version'] == '0.2.0'
        assert entry['previous_version'] == '0.1.0'


class TestTheSameVersionGuard:
    def test_a_clean_same_version_still_needs_force(self):
        """The entry says 0.2.0 only once 0.2.0's migrations succeeded, so
        reinstalling the same version remains a decision the operator makes
        with --force."""
        with pytest.raises(SystemExit):
            _module_upgrade._check_version_direction(
                'demo_mod',
                '0.2.0',
                '0.2.0',
                force=False,
            )

    def test_a_retry_after_a_failed_migration_walks_the_forward_path(self):
        """The entry never claimed 0.2.0, so 0.1.0 → 0.2.0 is an ordinary
        upgrade — the recovery needs no exception carved into the guard."""
        _module_upgrade._check_version_direction(
            'demo_mod',
            '0.1.0',
            '0.2.0',
            force=False,
        )
