"""The shipped-module lists answer for directories the repository ships.

``REPO_SHIPPED_MODULES`` decides who stands behind a module on the store
screen: only a name on the list keeps its manifest's ``module_type``.
A name on the list without a directory behind it is the one shape a
dropped directory can exploit — nothing in the repository answers to the
name, so a directory appearing under ``app/modules/`` with that name can
only be somebody else's drop, and it used to inherit the repository's
own trust from the list entry: Official, trusted, always-on, from a
manifest the dropper wrote themselves. Five product features without
module directories (core, items, locations, categories, announcements)
sat in the list exactly that way.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.core import module_registry as module_registry_module
from app.core.module_safety import (
    ALWAYS_ON_MODULES,
    ALWAYS_ON_SHIPPED_MODULES,
    REPO_SHIPPED_MODULES,
    TRUSTED_CORE_MODULES,
    TRUSTED_SHIPPED_MODULES,
    is_always_on,
)
from app.core.module_tracking import load_module_tracking

MODULES_ROOT = Path(__file__).resolve().parents[2] / 'app' / 'modules'


def _tree_module_names() -> set[str]:
    """Names the repository actually ships as module directories."""
    return {
        d.name
        for d in MODULES_ROOT.iterdir()
        if d.is_dir() and (d / 'manifest.json').is_file()
    }


class TestTheShippedListIsTheTree:
    def test_every_shipped_name_has_a_directory(self):
        ghosts = REPO_SHIPPED_MODULES - _tree_module_names()
        assert not ghosts, (
            f'names shipped by no directory: {sorted(ghosts)} — a dropped '
            "directory taking one of them reads as the repository's own"
        )

    def test_every_module_directory_is_shipped(self):
        # A directory the module store INSTALLED is not the repository's
        # to ship: ``module install`` copies it under app/modules/ with a
        # tracking entry and no list membership, and it reads as community
        # by design. Without this subtraction the gate went red on every
        # machine holding a legally installed module.
        installed = set(load_module_tracking())
        forgotten = _tree_module_names() - REPO_SHIPPED_MODULES - installed
        assert not forgotten, (
            'module directories missing from REPO_SHIPPED_MODULES: '
            f'{sorted(forgotten)} — the store would read them as community'
        )

    def test_first_party_trust_reaches_only_shipped_directories(self):
        assert TRUSTED_SHIPPED_MODULES == TRUSTED_CORE_MODULES & REPO_SHIPPED_MODULES

    def test_a_feature_name_without_a_directory_is_never_first_party(self):
        assert 'announcements' not in REPO_SHIPPED_MODULES
        assert 'announcements' not in TRUSTED_SHIPPED_MODULES

    def test_always_on_feature_names_stay_on_the_policy_side(self):
        """The always-on FEATURE policy keeps its names — virtual features
        (no module directory) keep their grant through ``is_always_on``,
        which the enablement API, the route guard and the store card all
        read."""
        assert 'announcements' in ALWAYS_ON_MODULES
        assert 'announcements' not in REPO_SHIPPED_MODULES

    def test_a_legally_installed_module_does_not_fail_the_gate(self, monkeypatch):
        """``module install`` copies a module under app/modules/ with a
        tracking entry and no shipped-list membership — by design. The
        gate reads the tracking file, so a machine holding installed
        modules keeps a green pre-push gate."""
        from app.core import module_tracking

        # The fake tree mixes two names the repository really ships with
        # one a store installation would have copied in.
        fake_tree = {
            *sorted(REPO_SHIPPED_MODULES)[:2],
            'installed_thing',
        }
        installed = fake_tree
        monkeypatch.setattr(
            'tests.unit.test_module_shipped_lists._tree_module_names',
            lambda: installed,
        )
        monkeypatch.setattr(
            module_tracking,
            'load_module_tracking',
            lambda: {'installed_thing': MagicMock()},
        )
        forgotten = (
            installed
            - REPO_SHIPPED_MODULES
            - set(module_tracking.load_module_tracking())
        )
        assert forgotten == set(), (
            'a tracked, installed module is not the repository to ship'
        )

    def test_a_shipped_module_stays_always_on(self):
        assert ALWAYS_ON_SHIPPED_MODULES == {'stats', 'printing'}
        assert is_always_on('stats') is True
        assert is_always_on('printing') is True

    def test_a_virtual_feature_keeps_always_on(self):
        # No module directory answers to the name, so the feature grant
        # stands — the banner and the bell are furniture, not a drop.
        assert is_always_on('announcements') is True

    def test_a_dropped_directory_cannot_wear_always_on(self, monkeypatch):
        """The registry knows a manifest for the name — a discovered
        module with no shipped directory behind it. Its always-on grant
        dies here: the store card and the toggle refusal read the same
        predicate, so the card never offers an action the API refuses."""
        monkeypatch.setattr(
            module_registry_module.module_registry,
            'get',
            lambda name: MagicMock() if name == 'announcements' else None,
        )
        assert is_always_on('announcements') is False
