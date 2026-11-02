"""Discovery itself refuses a module that needs a platform this is not.

The unit test next to the schema proves ``_validate_manifest`` returns None and
hands over a reason. This one runs the path an installation actually takes:
``discover_modules`` walks a directory of modules, and what a rejected module
leaves behind is an entry in ``get_rejected_modules()`` that an administrator
can read — while every other module in the same walk still comes up.
"""

import json
from pathlib import Path

import pytest

from app.core._registry_class import ModuleRegistry
from app.core.version import get_platform_version


def _module_dir(root: Path, name: str, **manifest_fields) -> Path:
    module_dir = root / name
    module_dir.mkdir()
    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': '0.1.0',
                'module_type': 'community',
                **manifest_fields,
            }
        ),
        encoding='utf-8',
    )
    return module_dir


@pytest.mark.integration
class TestDiscoveryHonoursTheFloor:
    @pytest.fixture
    def discovered(self, tmp_path):
        _module_dir(tmp_path, 'from_the_future', inventari_min_version='99.0.0')
        _module_dir(tmp_path, 'contemporary', inventari_min_version='0.1.0')

        # A registry of its own: the singleton carries the real installation and
        # a walk over a temporary directory must not be able to disturb it.
        registry = ModuleRegistry()
        registry.discover_modules(base_path=tmp_path)
        return {r.module_name: r.reason for r in registry.get_rejected_modules()}

    def test_the_module_from_the_future_is_turned_away_in_words(self, discovered):
        assert 'from_the_future' in discovered

        reason = discovered['from_the_future']
        assert 'requires Inventari >= 99.0.0' in reason
        assert get_platform_version() in reason

    def test_the_walk_continues_past_it(self, discovered):
        # Both fixtures are manifest-only, so neither can finish importing —
        # what matters is that the second one got past the floor and failed
        # somewhere else entirely. A floor check that stopped the whole walk
        # would take the rest of the installation down with one bad module.
        assert 'contemporary' in discovered
        assert 'requires Inventari' not in discovered['contemporary']
