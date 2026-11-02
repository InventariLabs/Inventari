"""A module may not take a name the frontend already owns.

A module's i18n namespace is its own directory name — ``frontend/src/i18n/config.ts``
reads ``modules/<name>/i18n/<language>.json`` under that name — and its
frontend is copied to ``frontend/src/modules/<name>/``. So a module called
``common`` answers the core's ``t("common:...")`` calls from a file nobody in
the core wrote, and a module called ``settings`` writes into a directory the
core keeps. Both names were free: the reserved list held feature names,
virtual modules and shipped module directories, and the installer looked only
at the backend tree, so a module without a backend half installed straight
over the core's frontend.

The names are reserved now, before anything ships under them, and the
installer refuses a collision on either side — a backend directory that is
already there, a frontend directory that is already there — with a message
that says which of them it is. MODULES_GUIDE lists the names next to the name
rule. What keeps the lists honest is here: every one of them is read back out
of the tree it claims to describe.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from app.cli import _module_meta, module_packaging
from app.cli._module_meta import ModuleYaml
from app.core.module_registry import ModuleRegistry
from app.core.module_safety import (
    CORE_FRONTEND_DIRECTORIES,
    CORE_I18N_NAMESPACES,
    REPO_SHIPPED_MODULES,
    reserved_module_names,
)
from app.core.module_tracking import load_module_tracking

GUIDE_RESERVED_START = '<!-- module-reserved-names:start -->'
GUIDE_RESERVED_END = '<!-- module-reserved-names:end -->'

pytestmark = pytest.mark.unit


def _repo_root() -> Path:
    return Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))


def _frontend_src() -> Path:
    return _repo_root() / 'frontend' / 'src'


class TestTheListsAreTheTrees:
    """Both new lists are read back out of the frontend they describe."""

    def test_the_i18n_namespaces_are_the_locale_files(self) -> None:
        """Every namespace the core answers under, and nothing else: the file
        names under ``frontend/src/i18n/locales/<language>/``. A namespace
        added there and not reserved here lets a module take it."""
        locales = _repo_root() / 'frontend' / 'src' / 'i18n' / 'locales'
        from_tree: set[str] = set()
        for language in locales.iterdir():
            if language.is_dir():
                from_tree |= {p.stem for p in language.iterdir() if p.is_file()}

        assert from_tree == set(CORE_I18N_NAMESPACES), (
            'CORE_I18N_NAMESPACES no longer describes frontend/src/i18n/locales: '
            f'{sorted(from_tree ^ set(CORE_I18N_NAMESPACES))} changed'
        )

    def test_the_frontend_directories_are_the_tree(self) -> None:
        """Every directory under ``frontend/src`` — the tree a module's own
        frontend lands inside — plus the directories under
        ``frontend/src/modules`` that are the core's own. Shipped modules and
        modules installed on this machine are subtracted from the module tree:
        those names are already reserved by their own list, and an installed
        one is a legal community module, not core content."""
        src = _frontend_src()
        top_level = {p.name for p in src.iterdir() if p.is_dir()}
        module_tree = {p.name for p in (src / 'modules').iterdir() if p.is_dir()}
        core_module_tree = (
            module_tree - REPO_SHIPPED_MODULES - set(load_module_tracking())
        )

        assert set(CORE_FRONTEND_DIRECTORIES) == top_level | core_module_tree, (
            'CORE_FRONTEND_DIRECTORIES no longer describes frontend/src: '
            f'{sorted(set(CORE_FRONTEND_DIRECTORIES) ^ (top_level | core_module_tree))} changed'
        )

    def test_the_names_that_collided_are_reserved(self) -> None:
        """The names that reached the core's own files, spelled out: a module
        of any of them is refused by the installer and at discovery."""
        reserved = reserved_module_names()

        assert {'common', 'permissions', 'scan'} <= reserved
        assert {'shared', 'settings', 'spaces', 'inventory', 'launcher'} <= reserved
        assert CORE_I18N_NAMESPACES <= reserved
        assert CORE_FRONTEND_DIRECTORIES <= reserved


class TestTheInstallerRefusesEitherSide:
    """``module install`` refuses a collision on the backend side and on the
    frontend side, and every refusal says why the name is taken."""

    @pytest.fixture
    def install_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        dest_backend = tmp_path / 'installed_backend'
        dest_frontend = tmp_path / 'installed_frontend'
        dest_backend.mkdir()
        dest_frontend.mkdir()
        source = tmp_path / 'source'
        (source / 'backend').mkdir(parents=True)
        (source / 'frontend').mkdir(parents=True)
        monkeypatch.setattr(module_packaging, 'BACKEND_MODULES_DIR', dest_backend)
        monkeypatch.setattr(module_packaging, 'FRONTEND_MODULES_DIR', dest_frontend)
        monkeypatch.setattr(
            _module_meta, 'TRACKING_FILE', tmp_path / 'community_modules.json'
        )
        return source, dest_backend, dest_frontend

    @staticmethod
    def _meta(name: str) -> ModuleYaml:
        return ModuleYaml(
            name=name,
            version='0.1.0',
            inventari_min_version='0.1.0',
            author='test',
            description='',
            license='MIT',
            homepage='',
            requires=[],
            components={'backend': True, 'frontend': True},
        )

    def _refusal(
        self, name: str, source: Path, capsys: pytest.CaptureFixture[str]
    ) -> str:
        with pytest.raises(SystemExit):
            module_packaging._check_install_guards(self._meta(name), name, source)
        return capsys.readouterr().out

    def test_a_backend_directory_that_is_already_there_is_refused(
        self, install_env, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The guard that was already there, named: an untracked directory on
        the backend side aborts the install before a file is copied."""
        source, dest_backend, _ = install_env
        (dest_backend / 'stale_mod').mkdir()

        out = self._refusal('stale_mod', source, capsys)

        assert 'backend/app/modules/stale_mod' in out

    def test_a_frontend_directory_that_is_already_there_is_refused(
        self, install_env, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The half the installer never looked at: a module without a
        backend half used to install into whatever the frontend tree already
        held under that name."""
        source, _, dest_frontend = install_env
        (dest_frontend / 'stale_mod').mkdir()

        out = self._refusal('stale_mod', source, capsys)

        assert 'frontend/src/modules/stale_mod' in out

    def test_a_namespace_the_core_translates_under_is_refused(
        self, install_env, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No directory exists to collide with — the collision is the
        namespace itself, and the message says so."""
        source, _, _ = install_env

        out = self._refusal('common', source, capsys)

        assert 'reserved' in out
        assert 'translations' in out

    def test_a_directory_the_core_keeps_is_refused(
        self, install_env, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A core frontend directory with no backend counterpart — the one a
        frontend-only module used to sail past every guard."""
        source, _, _ = install_env

        out = self._refusal('settings', source, capsys)

        assert 'reserved' in out
        assert 'frontend/src' in out


def _drop(tmp_path: Path, name: str) -> Path:
    """A hand-placed module directory: manifest, package, no module class."""
    module_dir = tmp_path / name
    module_dir.mkdir()
    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': '1.0.0',
                'module_type': 'community',
                'capabilities': ['database'],
            }
        ),
        encoding='utf-8',
    )
    (module_dir / '__init__.py').write_text('', encoding='utf-8')
    return module_dir


class TestDiscoveryRefusesTheSameNames:
    def test_a_dropped_directory_named_after_a_namespace_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The installer is not the only gate: a directory planted by hand
        meets discovery, and a namespace or a core frontend directory is
        refused there the same way a feature name is."""
        registry = ModuleRegistry()
        _drop(tmp_path, 'common')
        _drop(tmp_path, 'settings')

        registry.discover_modules(base_path=tmp_path)

        rejected = {r.module_name: r.reason for r in registry.get_rejected_modules()}
        assert 'common' in rejected and 'reserved' in rejected['common'].lower()
        assert 'settings' in rejected and 'reserved' in rejected['settings'].lower()
        assert registry.get('common') is None
        assert registry.get('settings') is None


def test_the_guide_lists_the_reserved_names() -> None:
    """MODULES_GUIDE carries the whole reserved list beside the name rule —
    it can neither forget a name nor invent one."""
    guide = (_repo_root() / 'MODULES_GUIDE.md').read_text(encoding='utf-8')
    match = re.search(
        re.escape(GUIDE_RESERVED_START) + r'(.*?)' + re.escape(GUIDE_RESERVED_END),
        guide,
        re.DOTALL,
    )
    assert match, 'MODULES_GUIDE.md carries no reserved-names block'

    listed = set(re.findall(r'`([a-z_][a-z0-9_]*)`', match.group(1)))
    reserved = set(reserved_module_names())

    assert listed == reserved, (
        'the reserved names in MODULES_GUIDE.md and reserved_module_names() '
        f'differ: {sorted(listed ^ reserved)}'
    )
