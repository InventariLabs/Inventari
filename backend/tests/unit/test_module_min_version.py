"""A module says which platform it needs, and the platform believes it.

``check_min_version`` and the ``inventari_min_version`` field have existed
since 0.9, but the only caller was the packaging CLI — the path a community
module takes. None of the official manifests declared the field, so a developer
opening one as a worked example learned to leave out the very thing their own
module will need, and an in-tree manifest could name any floor at all without
anything reading it.

The floor is now checked where modules are discovered. A module that needs more
than the installation has does not load, is recorded as rejected with the reason
in words, and the rest of the installation comes up around it.
"""

import json
from pathlib import Path

import pytest

from app.core.module_validator import _validate_manifest
from app.core.version import get_platform_version, parse_version

MODULES_DIR = Path(__file__).resolve().parents[2] / 'app' / 'modules'


def _manifests() -> dict[str, dict]:
    return {
        d.name: json.loads((d / 'manifest.json').read_text(encoding='utf-8'))
        for d in sorted(MODULES_DIR.iterdir())
        if (d / 'manifest.json').is_file()
    }


def _write_module(tmp_path: Path, name: str, **manifest_fields) -> Path:
    module_dir = tmp_path / name
    module_dir.mkdir()
    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': '0.1.0',
                # Community: a directory the repository does not ship that
                # claims more is refused for the claim (manifest_refusal),
                # whatever its floor says.
                'module_type': 'community',
                **manifest_fields,
            }
        ),
        encoding='utf-8',
    )
    return module_dir


@pytest.mark.unit
class TestOfficialManifestsDeclareTheFloor:
    def test_the_scan_finds_the_modules(self):
        manifests = _manifests()

        assert len(manifests) >= 10
        assert {'recipes', 'stats', 'vision'} <= set(manifests)

    def test_every_one_of_them_names_a_platform_version(self):
        silent = sorted(
            name
            for name, data in _manifests().items()
            if not str(data.get('inventari_min_version', '')).strip()
        )

        assert not silent, (
            'these manifests declare no inventari_min_version, and each one is '
            'a worked example somebody will copy: ' + ', '.join(silent)
        )

    def test_none_of_them_asks_for_more_than_this_platform(self):
        platform = parse_version(get_platform_version())
        unsatisfiable = {
            name: data['inventari_min_version']
            for name, data in _manifests().items()
            if parse_version(str(data.get('inventari_min_version') or '0')) > platform
        }

        assert not unsatisfiable, (
            f'these modules cannot load on {get_platform_version()}: '
            + ', '.join(f'{n} (needs {v})' for n, v in sorted(unsatisfiable.items()))
        )


@pytest.mark.unit
class TestTheRegistryEnforcesIt:
    def test_a_module_from_the_future_does_not_load(self, tmp_path):
        rejections: list[tuple[str, str]] = []
        module_dir = _write_module(
            tmp_path, 'from_the_future', inventari_min_version='99.0.0'
        )

        result = _validate_manifest(
            module_dir, lambda name, reason: rejections.append((name, reason))
        )

        assert result is None
        assert len(rejections) == 1
        name, reason = rejections[0]
        assert name == 'from_the_future'
        # Words, not a traceback: the reason reaches an administrator through
        # get_rejected_modules().
        assert '99.0.0' in reason
        assert get_platform_version() in reason
        assert 'requires Inventari' in reason

    def test_a_module_the_platform_satisfies_loads(self, tmp_path):
        rejections: list[tuple[str, str]] = []
        module_dir = _write_module(
            tmp_path, 'contemporary', inventari_min_version=get_platform_version()
        )

        result = _validate_manifest(
            module_dir, lambda name, reason: rejections.append((name, reason))
        )

        assert rejections == []
        assert result is not None
        assert result.inventari_min_version == get_platform_version()

    def test_a_manifest_that_names_no_floor_is_left_alone(self, tmp_path):
        # The field is opt-in at the schema level: a community module that has
        # never heard of it must not stop working the day the check landed.
        rejections: list[tuple[str, str]] = []
        module_dir = _write_module(tmp_path, 'unopinionated')

        result = _validate_manifest(
            module_dir, lambda name, reason: rejections.append((name, reason))
        )

        assert rejections == []
        assert result is not None
        assert result.inventari_min_version == ''
