"""A dropped module directory cannot crown itself.

Who stands behind a module is the one fact a store reader cannot guess.
Signatures (ADR-019) are specified but not built, so the only issuer of
trust in the running system is the repository itself: a directory the
repository ships is first-party, anything else is community. A dropped
directory used to keep whatever ``module_type`` its manifest declared —
``official`` or ``core`` on a file the dropper wrote — and a manifest
author line could carry the core team's own name. Discovery now refuses
the title and strips the borrowed name; what it does not do is certify a
community author, so an honest one stays visible as the unverified claim
the store already labels ``unsigned``.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from fastapi import APIRouter

from app.core.module_registry import ModuleRegistry
from app.core.modules import BaseModule, ModuleMetadata


def _drop(tmp_path: Path, name: str, *, module_type: str) -> Path:
    module_dir = tmp_path / name
    module_dir.mkdir()
    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': '1.0.0',
                'module_type': module_type,
                'capabilities': ['database'],
            }
        ),
        encoding='utf-8',
    )
    (module_dir / '__init__.py').write_text('', encoding='utf-8')
    return module_dir


def _rejection(registry: ModuleRegistry, name: str) -> str:
    rejected = {r.module_name: r.reason for r in registry.get_rejected_modules()}
    assert name in rejected, f'{name} was not rejected: {rejected}'
    return rejected[name]


class TestTheTitle:
    @pytest.mark.unit
    def test_official_is_refused_on_an_unshipped_directory(self, tmp_path):
        registry = ModuleRegistry()
        _drop(tmp_path, 'revdemo', module_type='official')

        registry.discover_modules(base_path=tmp_path)

        assert registry.get('revdemo') is None
        assert 'community' in _rejection(registry, 'revdemo')

    @pytest.mark.unit
    def test_core_is_refused_on_an_unshipped_directory(self, tmp_path):
        registry = ModuleRegistry()
        _drop(tmp_path, 'revdemo', module_type='core')

        registry.discover_modules(base_path=tmp_path)

        assert registry.get('revdemo') is None
        assert 'community' in _rejection(registry, 'revdemo')

    @pytest.mark.unit
    def test_a_community_claim_loads(self, tmp_path, monkeypatch):
        registry = ModuleRegistry()
        _drop(tmp_path, 'revdemo', module_type='community')
        package = types.ModuleType('app.modules.revdemo')
        package.Drop = _Drop
        monkeypatch.setitem(sys.modules, 'app.modules.revdemo', package)

        registry.discover_modules(base_path=tmp_path)

        module = registry.get('revdemo')
        assert module is not None
        assert module.metadata.module_type == 'community'


class _Drop(BaseModule):
    """A community module whose code also carries an author claim.

    One stable metadata object, the way every in-tree module holds it — a
    property returning a fresh instance on each access could not carry the
    registry's strip of the borrowed name.
    """

    def __init__(self, author: str | None = 'Some Vendor') -> None:
        self._metadata = ModuleMetadata(
            name='revdemo',
            version='1.0.0',
            display_name='Revision demo',
            description='',
            icon='box',
            author=author,
        )

    @property
    def metadata(self) -> ModuleMetadata:
        return self._metadata

    def register_routes(self) -> APIRouter:
        return APIRouter()


class TestTheAuthor:
    @pytest.mark.unit
    def test_an_unshipped_module_cannot_be_by_the_core_team(
        self, tmp_path, monkeypatch
    ):
        registry = ModuleRegistry()
        _drop(tmp_path, 'revdemo', module_type='community')
        package = types.ModuleType('app.modules.revdemo')

        class Impostor(_Drop):
            def __init__(self) -> None:
                super().__init__(author='Core Team')

        package.Drop = Impostor  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, 'app.modules.revdemo', package)

        registry.discover_modules(base_path=tmp_path)

        module = registry.get('revdemo')
        assert module is not None
        assert module.metadata.author is None

    @pytest.mark.unit
    def test_an_honest_community_author_stays(self, tmp_path, monkeypatch):
        """The store labels an unverified author ``unsigned``; it does not
        erase one. Only the first-party name the registry itself issues is
        stripped."""
        registry = ModuleRegistry()
        _drop(tmp_path, 'revdemo', module_type='community')
        package = types.ModuleType('app.modules.revdemo')
        package.Drop = _Drop
        monkeypatch.setitem(sys.modules, 'app.modules.revdemo', package)

        registry.discover_modules(base_path=tmp_path)

        module = registry.get('revdemo')
        assert module is not None
        assert module.metadata.author == 'Some Vendor'
