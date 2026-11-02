"""A manifest written for a newer platform says so, instead of listing its fields.

``ModuleManifest`` refuses unknown fields. A module written for 0.12 that uses
a field added in 0.12 and is installed on 0.11 used to be reported as "Extra
inputs are not permitted"; the administrator needs "requires Inventari >=
0.12.0". The floor is read from the raw JSON when the strict parse fails, and
``manifest_version`` names the shape of the file itself.

``module.yaml`` and ``manifest.json`` also share one name rule, and the fields
they both carry agree in a freshly scaffolded package.
"""

import json
from pathlib import Path

import pytest
import yaml

from app.cli._module_meta import _parse_module_yaml
from app.cli._module_scaffold import scaffold_community_module
from app.cli.module_validator import validate_manifest
from app.core.module_manifest_schema import (
    SUPPORTED_MANIFEST_VERSIONS,
    ModuleManifest,
)
from app.core.module_validator import _validate_manifest
from app.core.version import get_platform_version

NEWER_FLOOR = '99.0.0'


def _module(tmp_path: Path, **fields: object) -> Path:
    module_dir = tmp_path / 'probe'
    module_dir.mkdir()
    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {'name': 'probe', 'version': '0.1.0', 'module_type': 'community', **fields}
        ),
        encoding='utf-8',
    )
    return module_dir


def _rejection(module_dir: Path) -> str | None:
    rejected: list[str] = []
    _validate_manifest(module_dir, lambda _name, reason: rejected.append(reason))
    return rejected[0] if rejected else None


@pytest.mark.unit
class TestTheFloorIsReadBeforeTheStrictParse:
    def test_an_unknown_field_with_a_floor_above_the_platform_names_the_floor(
        self, tmp_path
    ):
        module_dir = _module(
            tmp_path, inventari_min_version=NEWER_FLOOR, a_field_from_the_future=True
        )

        reason = _rejection(module_dir)

        assert reason is not None
        assert f'requires Inventari >= {NEWER_FLOOR}' in reason
        assert 'Extra inputs' not in reason

    def test_an_unknown_field_with_a_satisfied_floor_is_still_an_unknown_field(
        self, tmp_path
    ):
        module_dir = _module(
            tmp_path,
            inventari_min_version=get_platform_version(),
            a_field_from_the_future=True,
        )

        reason = _rejection(module_dir)

        assert reason is not None
        assert 'Extra inputs are not permitted' in reason

    def test_the_cli_validator_gives_the_same_sentence(self, tmp_path):
        module_dir = _module(
            tmp_path, inventari_min_version=NEWER_FLOOR, a_field_from_the_future=True
        )

        errors = validate_manifest(module_dir)

        assert len(errors) == 1
        assert f'requires Inventari >= {NEWER_FLOOR}' in errors[0]

    def test_a_malformed_floor_does_not_hide_the_schema_error(self, tmp_path):
        module_dir = _module(tmp_path, inventari_min_version=7, extra_field=1)

        reason = _rejection(module_dir)

        assert reason is not None
        assert 'Invalid manifest.json' in reason


@pytest.mark.unit
class TestManifestVersion:
    def test_it_defaults_to_the_one_shape_that_exists(self, tmp_path):
        manifest = ModuleManifest.load(_module(tmp_path))

        assert manifest.manifest_version == 1
        assert SUPPORTED_MANIFEST_VERSIONS == (1,)

    def test_a_declared_supported_version_loads(self, tmp_path):
        manifest = ModuleManifest.load(_module(tmp_path, manifest_version=1))

        assert manifest.manifest_version == 1

    @pytest.mark.parametrize('with_unknown_field', [False, True])
    def test_an_unread_version_is_refused_by_naming_the_ones_that_are_read(
        self, tmp_path, with_unknown_field
    ):
        extra = {'a_field_from_the_future': 1} if with_unknown_field else {}
        module_dir = _module(tmp_path, manifest_version=2, **extra)

        reason = _rejection(module_dir)

        assert reason is not None
        assert 'manifest_version 2' in reason
        assert 'it reads: 1' in reason


@pytest.mark.unit
class TestOneNameRule:
    @pytest.mark.parametrize(
        'name',
        ['a', 'ab', 'a1', 'a_b', 'Ab', '1a', '_a', 'a-b', 'a b', ''],
    )
    def test_module_yaml_and_manifest_accept_the_same_names(self, tmp_path, name):
        source = tmp_path / 'package'
        source.mkdir()
        (source / 'module.yaml').write_text(
            yaml.safe_dump({'name': name, 'version': '0.1.0'}), encoding='utf-8'
        )
        try:
            _parse_module_yaml(source)
            yaml_accepts = True
        except ValueError:
            yaml_accepts = False

        try:
            ModuleManifest(name=name, version='0.1.0', module_type='community')
            manifest_accepts = True
        except ValueError:
            manifest_accepts = False

        assert yaml_accepts == manifest_accepts


@pytest.mark.unit
def test_a_scaffolded_package_carries_the_same_identity_in_both_files(tmp_path):
    scaffold_community_module('agree_probe', output_dir=str(tmp_path))
    package = tmp_path / 'agree_probe'

    meta = _parse_module_yaml(package)
    manifest = ModuleManifest.load(package / 'backend')

    assert meta['name'] == manifest.name
    assert meta['version'] == manifest.version
    assert meta['inventari_min_version'] == manifest.inventari_min_version
    assert meta['requires'] == manifest.requires
