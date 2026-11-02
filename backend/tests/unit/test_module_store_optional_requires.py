"""The store list carries each module's soft companions.

``optional_requires`` never gates enabling, so the only place it can do any
good is the payload the App Store renders — if the field does not arrive,
nobody can be told a companion exists.
"""

import pytest

from app.api.modules import get_available_modules_list
from app.core.module_registry import module_registry


def _store_modules():
    if not module_registry.get_all():
        module_registry.discover_modules()
    return get_available_modules_list()


@pytest.mark.unit
class TestStoreListCarriesOptionalRequires:
    def test_recipes_names_its_shopping_list_companion(self):
        listed = {m.name: m for m in _store_modules()}

        assert listed['recipes'].optional_requires == ['shopping_lists']

    def test_a_module_without_companions_lists_none(self):
        listed = {m.name: m for m in _store_modules()}

        assert listed['webhooks'].optional_requires == []

    def test_the_virtual_module_defaults_to_none(self):
        # `partners` is assembled by hand in the endpoint, so nothing upstream
        # fills the field for it — the schema default has to.
        listed = {m.name: m for m in _store_modules()}

        assert listed['partners'].optional_requires == []
