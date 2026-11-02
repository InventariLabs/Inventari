"""Unit tests for module context-tag scoping helper."""

from unittest.mock import MagicMock

from app.core.module_scope import get_claimed_context_tags


def _module(name: str, context_tags: list[str | None]):
    """Build a fake module instance with categories carrying context_tags."""
    mod = MagicMock()
    mod.metadata.name = name
    mod.metadata.categories = [MagicMock(context_tag=t) for t in context_tags]
    return mod


def test_returns_empty_when_no_modules(monkeypatch):
    monkeypatch.setattr('app.core.module_scope.module_registry.get_all', lambda: [])
    assert get_claimed_context_tags() == set()


def test_collects_tags_from_every_registered_module(monkeypatch):
    equipment = _module('equipment', ['equipment', 'equipment', 'equipment'])
    library = _module('library', ['media'])
    core = _module('core', [None])  # core declares no vertical tag
    monkeypatch.setattr(
        'app.core.module_scope.module_registry.get_all',
        lambda: [equipment, library, core],
    )
    assert get_claimed_context_tags() == {'equipment', 'media'}


def test_a_disabled_module_still_claims_its_tag(monkeypatch):
    """Turning a module off must not release the data it left behind.

    The organization that stops using ``equipment`` keeps its laptops; if
    the claim followed the enabled set, every one of them would reappear
    among the groceries the moment the module was switched off.
    """
    equipment = _module('equipment', ['equipment'])
    library = _module('library', ['media'])
    monkeypatch.setattr(
        'app.core.module_scope.module_registry.get_all',
        lambda: [equipment, library],
    )
    assert get_claimed_context_tags() == {'equipment', 'media'}


def test_skips_none_tags(monkeypatch):
    mod = _module('m', ['equipment', None, ''])
    monkeypatch.setattr('app.core.module_scope.module_registry.get_all', lambda: [mod])
    assert get_claimed_context_tags() == {'equipment'}
