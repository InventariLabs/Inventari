"""Which modules an installation has is deployment state, not repository content.

`backend/community_modules.json` was a tracked file that the installer writes
to. A self-hoster who installed any module got an `M` on a file they never
edited, and a conflict on the documented update path — `git pull` — with
nothing in DEPLOYMENT.md or MODULES_GUIDE.md warning them.
"""

from __future__ import annotations

import json

import pytest

from app.core import module_tracking


@pytest.mark.unit
class TestRegistryLocation:
    def test_the_registry_lives_outside_the_tracked_tree(self):
        # Whether git tracks it cannot be asserted from here — the backend
        # container mounts backend/ and has no .git to ask. What is testable,
        # and what the ignore rule keys on, is that the file sits in the data
        # directory rather than loose among the repository's own files.
        assert module_tracking.TRACKING_FILE.parent.name == 'data'
        assert module_tracking.TRACKING_FILE.name == 'community_modules.json'
        assert module_tracking.LEGACY_TRACKING_FILE.parent.name != 'data'


@pytest.mark.unit
class TestReadingAcrossTheMove:
    def test_a_registry_at_the_old_path_is_still_read(self, monkeypatch, tmp_path):
        """An installation that predates the move must not appear to have lost
        its modules — the list is the only record of what is installed."""
        legacy = tmp_path / 'community_modules.json'
        legacy.write_text(json.dumps({'modules': {'old_module': {'version': '1.0.0'}}}))

        monkeypatch.setattr(
            module_tracking, 'TRACKING_FILE', tmp_path / 'data' / 'x.json'
        )
        monkeypatch.setattr(module_tracking, 'LEGACY_TRACKING_FILE', legacy)

        assert 'old_module' in module_tracking.load_module_tracking()

    def test_the_current_path_wins_when_both_exist(self, monkeypatch, tmp_path):
        legacy = tmp_path / 'community_modules.json'
        legacy.write_text(json.dumps({'modules': {'old_module': {'version': '1.0.0'}}}))
        current = tmp_path / 'data' / 'community_modules.json'
        current.parent.mkdir()
        current.write_text(
            json.dumps({'modules': {'new_module': {'version': '2.0.0'}}})
        )

        monkeypatch.setattr(module_tracking, 'TRACKING_FILE', current)
        monkeypatch.setattr(module_tracking, 'LEGACY_TRACKING_FILE', legacy)

        tracked = module_tracking.load_module_tracking()
        assert 'new_module' in tracked
        assert 'old_module' not in tracked

    def test_an_install_creates_the_directory_it_needs(self, monkeypatch, tmp_path):
        """A fresh checkout has no backend/data/ — the first install makes it."""
        from app.cli import _module_meta

        target = tmp_path / 'data' / 'community_modules.json'
        monkeypatch.setattr(_module_meta, 'TRACKING_FILE', target)

        _module_meta._save_tracking({'shelf_labels': {'version': '1.0.0'}})

        assert json.loads(target.read_text())['modules']['shelf_labels']
