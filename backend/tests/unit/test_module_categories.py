"""Every module in the store belongs somewhere findable.

The store grouped modules by the category declared on their *frontend launcher
tile*, which only modules with a tile declare. Six had none, so three of the
eight filters — Core, Analytics, System — matched nothing and answered "No
modules found", the sentence a failed search gets. Someone looking for
Statistics under Analytics concluded it was not installed.

The category now travels with the module, through ``/modules/available``. This
test is what keeps it declared: a new module that forgets lands in ``other``,
and ``other`` is a bucket, not an answer.
"""

import pytest

from app.api.modules import get_available_modules_list
from app.core.module_registry import module_registry


def _store_modules():
    if not module_registry.get_all():
        module_registry.discover_modules()
    return get_available_modules_list()


@pytest.mark.unit
class TestModuleCategories:
    def test_every_module_declares_one(self):
        uncategorised = [m.name for m in _store_modules() if m.category == 'other']

        assert not uncategorised, (
            'these modules would be filed under "other" in the store: '
            + ', '.join(sorted(uncategorised))
        )

    def test_the_check_is_not_vacuous(self):
        # A run that discovered nothing would pass the check above by
        # describing an empty store.
        modules = _store_modules()

        assert len(modules) >= 10
        assert {'stats', 'webhooks'} <= {m.name for m in modules}

    def test_a_manifest_that_omits_it_says_other(self):
        # The field is opt-in, so adding it did not silently reclassify a
        # community module that has never heard of the taxonomy.
        from app.core.module_manifest_schema import ModuleManifest

        assert (
            ModuleManifest(
                name='maker', version='1.0.0', module_type='community'
            ).category
            == 'other'
        )


@pytest.mark.unit
class TestReferenceModule:
    """A worked example is documentation, not something to install.

    ``example_widgets`` sat in the store between Documents and Purchase
    Orders, describing itself as a "Reference module demonstrating Inventari
    module patterns" — an invitation for an administrator to switch on a demo
    of the plugin system next to their warehouse.
    """

    def test_the_store_does_not_offer_it(self):
        assert 'example_widgets' not in {m.name for m in _store_modules()}

    def test_it_stays_registered_for_the_scaffold_and_the_tests(self):
        if not module_registry.get_all():
            module_registry.discover_modules()

        names = {m.metadata.name for m in module_registry.get_all()}
        assert 'example_widgets' in names

    def test_a_scaffolded_module_does_not_inherit_the_mark(self, tmp_path):
        import json
        import shutil

        from app.cli.module_generator import _process_copied_files

        dst = tmp_path / 'bookmarks'
        dst.mkdir()
        shutil.copy('app/modules/example_widgets/manifest.json', dst / 'manifest.json')

        _process_copied_files(dst, 'bookmarks', 'Bookmark', 'Bookmarks')

        assert 'is_reference' not in json.loads((dst / 'manifest.json').read_text())
