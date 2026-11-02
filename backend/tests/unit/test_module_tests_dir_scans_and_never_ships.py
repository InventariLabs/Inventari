"""The module's tests directory: never shipped, and never a blind spot.

Two defects shared one excuse. The scanner skipped every file whose
ABSOLUTE path carried a `tests` component - so a module checked out
under /tmp/tests/whatever produced a clean report over a tree nobody
read. And the skip leaned on a sentence that was not true:
"they never ship" - while the installer copied backend/ wholesale,
tests and all, and a payload under backend/tests/ landed in the running
tree importable as app.modules.<mod>.tests.<file>.

The scan still skips a module's own tests - tests are the author's
workbench, not runtime code - but the skip now matches the path
RELATIVE to the module root, so only the module's own tests are
skipped. And the install drops backend/tests/ before anything is
copied, which makes "never ship" a fact instead of a promise: what is
not installed cannot execute.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.cli import module_packaging
from app.core.module_safety_analysis import analyze_module_safety

MODULE_YAML = (
    'name: probe_mod\n'
    'version: 0.1.0\n'
    'inventari_min_version: "0.1.0"\n'
    'author: test\n'
    'description: probe\n'
    'license: MIT\n'
    'homepage: ""\n'
    'requires: []\n'
    'components:\n'
    '  backend: true\n'
    '  frontend: false\n'
)

TEST_PAYLOAD = 'import subprocess\nsubprocess.run(["true"])\n'


def _make_module(root: Path) -> Path:
    """A module with one forbidden import in code and one in tests/."""
    module_dir = root / 'probe_mod'
    (module_dir / 'tests').mkdir(parents=True)
    (module_dir / '__init__.py').write_text('')
    # The code violation: app.models is banned for module code.
    (module_dir / 'service.py').write_text(
        'from app.models.item import Item\n\ndef find():\n    return Item\n'
    )
    # The payload a stranger plants under tests/ — same ban, different file.
    (module_dir / 'tests' / 'test_payload.py').write_text(TEST_PAYLOAD)
    (module_dir / 'manifest.json').write_text(
        json.dumps({'name': 'probe_mod', 'version': '0.1.0'})
    )
    return module_dir


@pytest.mark.unit
class TestScanMatchesRelativeToTheModuleRoot:
    def test_a_module_under_a_tests_parent_is_still_scanned(
        self, tmp_path: Path
    ) -> None:
        """The exclusion is a fact about paths INSIDE the module. A module
        that merely LIVES under a directory named tests is scanned like
        any other — the old absolute-path match answered a clean report
        for a tree nobody read. Its own tests/ stay skipped (they never
        ship); its code does not."""
        under_tests = _make_module(tmp_path / 'tests' / 'workshop')

        findings = analyze_module_safety(under_tests, ['database'], use_cache=False)

        subjects = '\n'.join(f.rel_path.as_posix() for f in findings)
        assert 'service.py' in subjects
        assert 'test_payload.py' not in subjects

    def test_the_own_tests_directory_is_still_skipped(self, tmp_path: Path) -> None:
        """Tests are the author's workbench, not runtime code — the skip
        survives, narrowed to the module's own tests directory."""
        module_dir = _make_module(tmp_path / 'normal')

        findings = analyze_module_safety(module_dir, ['database'], use_cache=False)

        subjects = '\n'.join(f.rel_path.as_posix() for f in findings)
        assert 'service.py' in subjects
        assert 'test_payload.py' not in subjects


@pytest.mark.unit
class TestTestsNeverShip:
    def _make_package(self, tmp_path: Path) -> Path:
        """A packagable module whose only suspicious file hides under tests/."""
        source = tmp_path / 'source'
        backend = source / 'backend'
        backend.mkdir(parents=True)
        (backend / 'tests').mkdir()
        (backend / '__init__.py').write_text('')
        (backend / 'module.py').write_text('LABEL = "probe"\n')
        (backend / 'tests' / 'test_payload.py').write_text(TEST_PAYLOAD)
        (backend / 'manifest.json').write_text(
            json.dumps(
                {
                    'name': 'probe_mod',
                    'version': '0.1.0',
                    'inventari_min_version': '0.1.0',
                    'category': 'integrations',
                    'display_name': 'Probe',
                    'description': 'probe module',
                    'icon': 'package',
                    'module_type': 'community',
                    'requires': [],
                    'capabilities': [],
                    'permissions': [],
                }
            )
        )
        (source / 'module.yaml').write_text(MODULE_YAML)
        return source

    def _install(self, tmp_path: Path, source: Path) -> Path:
        dest_backend = tmp_path / 'installed_backend'
        tracking_file = tmp_path / 'community_modules.json'
        with (
            patch.object(module_packaging, 'BACKEND_MODULES_DIR', dest_backend),
            patch.object(module_packaging, 'FRONTEND_MODULES_DIR', tmp_path / 'fe'),
            patch('app.cli._module_meta.BACKEND_MODULES_DIR', dest_backend),
            patch('app.cli._module_meta.FRONTEND_MODULES_DIR', tmp_path / 'fe'),
            patch('app.cli._module_meta.TRACKING_FILE', tracking_file),
        ):
            module_packaging.install_module(
                str(source), allow_unsigned=True
            )  # subject is tests/-shipping, not signatures
        return dest_backend / 'probe_mod'

    def test_an_installed_module_carries_no_tests_directory(
        self, tmp_path: Path
    ) -> None:
        source = self._make_package(tmp_path)

        installed = self._install(tmp_path, source)

        assert installed.exists(), 'the module itself must install'
        assert not (installed / 'tests').exists(), (
            'backend/tests/ shipped with the install — executable code the '
            'scanner skipped landed in the running tree'
        )

    def test_a_scanner_invisible_payload_cannot_ride_tests_into_the_install(
        self, tmp_path: Path
    ) -> None:
        """A module whose ONLY violation hides under tests/ installs clean —
        and still ships no tests directory for the payload to ride in."""
        source = self._make_package(tmp_path)

        installed = self._install(tmp_path, source)

        assert (installed / 'tests' / 'test_payload.py').exists() is False
        # And the scanned copy of what did install is clean, consistently.
        findings = analyze_module_safety(installed, [], use_cache=False)
        assert findings == []


FRONTEND_MODULE_YAML = MODULE_YAML.replace('  frontend: false', '  frontend: true')

FE_TEST_PAYLOAD = (
    "import { writeFileSync } from 'fs'\n"
    "it('runs in node', () => { writeFileSync('/tmp/witness', 'pwned') })\n"
)


@pytest.mark.unit
class TestTestsNeverShipOnEitherHalf:
    """The frontend half had the same hole, with a different runner.

    The installer dropped tests/ on the backend side only, on the grounds
    that "a frontend test cannot run by being copied — nothing in the
    bundle imports it". True of the bundle, and beside the point: vitest
    has no `include`, so it collects **/*.{test,spec}.* from the whole
    tree, and a stranger's test file executed in node — with the file
    system — for anyone who ran `npm run test:run` after installing.
    """

    def _make_package(self, tmp_path: Path) -> Path:
        source = tmp_path / 'source'
        backend = source / 'backend'
        frontend = source / 'frontend'
        backend.mkdir(parents=True)
        (frontend / 'tests').mkdir(parents=True)
        (backend / '__init__.py').write_text('')
        (backend / 'module.py').write_text('LABEL = "probe"\n')
        (backend / 'manifest.json').write_text(
            json.dumps(
                {
                    'name': 'probe_mod',
                    'version': '0.1.0',
                    'inventari_min_version': '0.1.0',
                    'category': 'integrations',
                    'display_name': 'Probe',
                    'description': 'probe module',
                    'icon': 'package',
                    'module_type': 'community',
                    'requires': [],
                    'capabilities': [],
                    'permissions': [],
                }
            )
        )
        (frontend / 'module.ts').write_text("export const label = 'probe'\n")
        (frontend / 'tests' / 'fe.spec.ts').write_text(FE_TEST_PAYLOAD)
        (source / 'module.yaml').write_text(FRONTEND_MODULE_YAML)
        return source

    def _install(self, tmp_path: Path, source: Path) -> tuple[Path, Path]:
        dest_backend = tmp_path / 'installed_backend'
        dest_frontend = tmp_path / 'installed_frontend'
        dest_frontend.mkdir()
        tracking_file = tmp_path / 'community_modules.json'
        with (
            patch.object(module_packaging, 'BACKEND_MODULES_DIR', dest_backend),
            patch.object(module_packaging, 'FRONTEND_MODULES_DIR', dest_frontend),
            patch('app.cli._module_meta.BACKEND_MODULES_DIR', dest_backend),
            patch('app.cli._module_meta.FRONTEND_MODULES_DIR', dest_frontend),
            patch('app.cli._module_meta.TRACKING_FILE', tracking_file),
        ):
            module_packaging.install_module(str(source), allow_unsigned=True)
        return dest_backend / 'probe_mod', dest_frontend / 'probe_mod'

    def test_the_installed_module_carries_no_frontend_tests_either(
        self, tmp_path: Path
    ) -> None:
        source = self._make_package(tmp_path)

        _, installed_frontend = self._install(tmp_path, source)

        assert (installed_frontend / 'module.ts').exists(), 'the screens install'
        assert not (installed_frontend / 'tests').exists(), (
            "frontend/tests/ shipped — the repository's own vitest run would "
            "execute a stranger's test file in node"
        )


@pytest.mark.unit
class TestTheInstallSaysWhatItLeftBehind:
    """A silent drop hands the author a tree they did not send.

    Dropping tests/ is defensible; doing it without a word is not — the
    author whose fixtures or vendored library sit in a directory named
    tests learns about it from a runtime error, and a certifier comparing
    source with install sees holes nobody explained.
    """

    def _make_package(self, tmp_path: Path) -> Path:
        source = tmp_path / 'source'
        backend = source / 'backend'
        (backend / 'tests').mkdir(parents=True)
        (backend / 'data' / 'tests').mkdir(parents=True)
        (backend / '__init__.py').write_text('')
        (backend / 'module.py').write_text('LABEL = "probe"\n')
        (backend / 'tests' / 'test_payload.py').write_text(TEST_PAYLOAD)
        (backend / 'data' / 'tests' / 'fixture.json').write_text('{"rows": []}')
        (backend / 'manifest.json').write_text(
            json.dumps(
                {
                    'name': 'probe_mod',
                    'version': '0.1.0',
                    'inventari_min_version': '0.1.0',
                    'category': 'integrations',
                    'display_name': 'Probe',
                    'description': 'probe module',
                    'icon': 'package',
                    'module_type': 'community',
                    'requires': [],
                    'capabilities': [],
                    'permissions': [],
                }
            )
        )
        (source / 'module.yaml').write_text(MODULE_YAML)
        return source

    def test_the_install_names_every_path_it_dropped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source = self._make_package(tmp_path)
        module_packaging.console.width = 200
        dest_backend = tmp_path / 'installed_backend'
        tracking_file = tmp_path / 'community_modules.json'
        with (
            patch.object(module_packaging, 'BACKEND_MODULES_DIR', dest_backend),
            patch.object(module_packaging, 'FRONTEND_MODULES_DIR', tmp_path / 'fe'),
            patch('app.cli._module_meta.BACKEND_MODULES_DIR', dest_backend),
            patch('app.cli._module_meta.FRONTEND_MODULES_DIR', tmp_path / 'fe'),
            patch('app.cli._module_meta.TRACKING_FILE', tracking_file),
        ):
            module_packaging.install_module(str(source), allow_unsigned=True)

        out = capsys.readouterr().out
        assert 'backend/tests/test_payload.py' in out
        assert 'backend/data/tests/fixture.json' in out, (
            'data under a tests directory is dropped too, and the author has '
            'no way to learn that from a silent install'
        )
