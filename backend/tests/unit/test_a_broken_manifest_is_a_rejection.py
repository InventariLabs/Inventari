"""Every way a manifest.json can be broken ends as a rejection, not a crash.

Both validators name the errors they expect from ``ModuleManifest.load``
instead of catching everything, so each spelling of "broken" the loader can
produce is pinned here: text that is not JSON, bytes that are not UTF-8, a
top-level value that is not an object, and an object the schema refuses.
"""

from pathlib import Path

import pytest

from app.cli.module_validator import validate_manifest
from app.core.module_validator import _validate_manifest

BROKEN_MANIFESTS = {
    'not json': b'{"name": ',
    'not utf-8': b'{"name": "\xff"}',
    'an array': b'["name", "test_mod"]',
    'refused by the schema': b'{"name": "test_mod", "version": 7}',
}


def _module_with_manifest(tmp_path: Path, content: bytes) -> Path:
    module_dir = tmp_path / 'test_mod'
    module_dir.mkdir()
    (module_dir / 'manifest.json').write_bytes(content)
    return module_dir


@pytest.mark.unit
@pytest.mark.parametrize('content', BROKEN_MANIFESTS.values(), ids=BROKEN_MANIFESTS)
def test_the_registry_rejects_the_module(tmp_path: Path, content: bytes) -> None:
    rejections: list[tuple[str, str]] = []
    module_dir = _module_with_manifest(tmp_path, content)

    manifest = _validate_manifest(
        module_dir, lambda name, why: rejections.append((name, why))
    )

    assert manifest is None
    assert len(rejections) == 1
    assert rejections[0][0] == 'test_mod'
    assert rejections[0][1].startswith('Invalid manifest.json: ')


@pytest.mark.unit
@pytest.mark.parametrize('content', BROKEN_MANIFESTS.values(), ids=BROKEN_MANIFESTS)
def test_the_cli_reports_the_module(tmp_path: Path, content: bytes) -> None:
    module_dir = _module_with_manifest(tmp_path, content)

    findings = validate_manifest(module_dir)

    assert len(findings) == 1
    assert findings[0].startswith('test_mod: invalid manifest.json (')
