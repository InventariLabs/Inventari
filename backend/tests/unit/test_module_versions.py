"""A module's version number has to mean something a stranger can check.

Two rules, both mechanical. The first is the ceiling: the public surface of a
module is the platform's extension API, so a module cannot promise stability
the thing underneath it has not reached — while the platform is on 0.x, no
module reaches 1.0.0. Compatibility is expressed separately, by
``inventari_min_version``, not by the version number.

The ceiling covers every number the store shows, not only the manifests. A
virtual module — partners, whose data lives in the core tables and which has
no manifest of its own — declares its version on its store card in
``app/api/modules.py``. A scan of manifests alone never saw that number, so it
kept the scaffold's 0.1.0 through the recalibration that moved every manifest.

The second is that there is one number, not two. Four modules build their
metadata by hand instead of through ``define_module``, so they declare a
version in ``module.py`` as well as in ``manifest.json``. Discovery does catch
a mismatch — ``_registry_class`` rejects the module outright — but it catches it
at startup, in a container, with the module gone from the installation. Here it
is a failing test on the machine of whoever changed one of the two.
"""

import json
from pathlib import Path

import pytest

from app.api.modules import get_available_modules_list
from app.core.module_registry import module_registry
from app.core.version import get_platform_version, parse_version

MODULES_DIR = Path(__file__).resolve().parents[2] / 'app' / 'modules'


def _manifest_versions() -> dict[str, str]:
    return {
        d.name: json.loads((d / 'manifest.json').read_text(encoding='utf-8')).get(
            'version', ''
        )
        for d in sorted(MODULES_DIR.iterdir())
        if (d / 'manifest.json').is_file()
    }


def _store_card_versions() -> dict[str, str]:
    if not module_registry.get_all():
        module_registry.discover_modules()
    return {m.name: m.version for m in get_available_modules_list()}


def _all_versions() -> dict[str, str]:
    return {**_store_card_versions(), **_manifest_versions()}


@pytest.mark.unit
class TestModuleVersionCeiling:
    def test_the_scan_finds_the_modules(self):
        # An empty scan would make every assertion below describe an empty world.
        versions = _manifest_versions()

        assert len(versions) >= 10
        assert {'recipes', 'warehouse', 'equipment'} <= set(versions)

    def test_the_scan_sees_the_modules_without_a_manifest(self):
        # Partners has no manifest; its number lives on its store card. A
        # ceiling that cannot see it does not hold it.
        assert 'partners' not in _manifest_versions()
        assert 'partners' in _all_versions()

    def test_no_module_promises_more_stability_than_the_platform_has(self):
        platform = parse_version(get_platform_version())
        # Reaching 1.0.0 lifts the ceiling, and that should be a decision made
        # out loud: a skip here would retire the rule without anyone noticing.
        assert platform < (1, 0, 0), (
            f'the platform is on {get_platform_version()}; the ceiling is lifted, '
            'so delete this test in the change that bumps the version'
        )

        too_confident = {
            name: version
            for name, version in _all_versions().items()
            if parse_version(version) >= (1, 0, 0)
        }

        assert not too_confident, (
            'these modules claim 1.0.0 or above while the platform is on '
            f'{get_platform_version()}: '
            + ', '.join(f'{n} ({v})' for n, v in sorted(too_confident.items()))
        )


@pytest.mark.unit
class TestOneVersionPerModule:
    def test_the_manifest_and_the_registered_metadata_agree(self):
        if not module_registry.get_all():
            module_registry.discover_modules()

        manifests = _manifest_versions()
        drifted = {
            m.metadata.name: (manifests[m.metadata.name], m.metadata.version)
            for m in module_registry.get_all()
            if m.metadata.name in manifests
            and manifests[m.metadata.name] != m.metadata.version
        }

        assert not drifted, (
            'manifest.json and module.py disagree about the version: '
            + ', '.join(
                f'{n}: manifest {a!r} vs metadata {b!r}'
                for n, (a, b) in sorted(drifted.items())
            )
        )
