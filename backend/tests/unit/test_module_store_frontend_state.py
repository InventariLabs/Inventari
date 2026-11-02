"""The store has to say when a module has no screens on this installation.

Measured on a fresh install: a community module whose frontend never landed
appeared in the App Store, toggled to 200, drew a ✓ ENABLED badge and a
Deactivate button — and existed nowhere in the launcher, the navigation or any
route. The tracking file knew the whole time; nothing carried the fact to the
one screen where somebody decides to switch a module on.
"""

from __future__ import annotations

import pytest

from app.api.modules import _frontend_state_of


@pytest.mark.unit
class TestFrontendStateOf:
    def test_a_module_nobody_tracks_has_its_screens(self):
        # Everything in the tree ships a frontend sibling; only a community
        # install can be missing one.
        assert _frontend_state_of('equipment', {}) == 'present'

    def test_a_complete_community_install_has_its_screens(self):
        tracked = {'shelf_labels': {'has_frontend': True, 'declares_frontend': True}}

        assert _frontend_state_of('shelf_labels', tracked) == 'present'

    def test_screens_that_were_declared_and_never_arrived_are_incomplete(self):
        tracked = {'shelf_labels': {'has_frontend': False, 'declares_frontend': True}}

        assert _frontend_state_of('shelf_labels', tracked) == 'incomplete'

    def test_a_module_that_never_claimed_screens_is_headless(self):
        tracked = {'sync_agent': {'has_frontend': False, 'declares_frontend': False}}

        assert _frontend_state_of('sync_agent', tracked) == 'headless'

    def test_an_entry_written_before_the_declaration_was_recorded(self):
        """Old entries cannot tell the two apart, so they get the mild reading."""
        tracked = {'sync_agent': {'has_frontend': False}}

        assert _frontend_state_of('sync_agent', tracked) == 'headless'


@pytest.mark.unit
class TestTheStoreListCarriesIt:
    def test_every_listed_module_states_its_frontend(self, monkeypatch):
        from app.api import modules as modules_api

        monkeypatch.setattr('app.core.module_tracking.load_module_tracking', lambda: {})

        listed = modules_api.get_available_modules_list()

        assert listed, 'the store list came back empty'
        assert all(m.frontend_state == 'present' for m in listed)

    def test_a_module_with_no_screens_is_marked_in_the_list(self, monkeypatch):
        from app.api import modules as modules_api
        from app.core.module_registry import module_registry

        target = next(
            m.metadata.name
            for m in module_registry.get_all()
            if not m.metadata.is_reference
        )
        monkeypatch.setattr(
            'app.core.module_tracking.load_module_tracking',
            lambda: {target: {'has_frontend': False, 'declares_frontend': True}},
        )

        listed = modules_api.get_available_modules_list()
        marked = {m.name: m.frontend_state for m in listed}

        assert marked[target] == 'incomplete'
