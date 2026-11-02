"""Unit tests for UOM alias resolution (recipes A2)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.core.uom_resolver import UOM_ALIASES, UomResolverAsync

_ORG_ID = UUID('00000000-0000-0000-0000-000000000001')


class TestUomAliases:
    """Alias map sanity — every alias must point at a real system symbol."""

    @pytest.mark.parametrize(
        ('alias', 'canonical'),
        [
            ('kilograms', 'kg'),
            ('KGS', 'kg'),
            ('grams', 'g'),
            ('liters', 'l'),
            ('milliliters', 'ml'),
            ('pieces', 'pcs'),
            ('pc', 'pcs'),
            ('szt', 'pcs'),
            ('opakowanie', 'pack'),
        ],
    )
    def test_alias_normalization(self, alias: str, canonical: str) -> None:
        assert UOM_ALIASES.get(alias.lower().strip()) == canonical

    @pytest.mark.parametrize(
        'canonical',
        ['kg', 'g', 'l', 'ml', 'pcs', 'pack', 'm', 'cm'],
    )
    def test_canonical_symbols_are_not_aliases(self, canonical: str) -> None:
        # Canonical symbols resolve through the exact lookup, not the alias map.
        assert UOM_ALIASES.get(canonical) is None

    def test_every_alias_maps_to_seeded_symbol(self) -> None:
        # Canonical symbols seeded in app/_seed_uom.py
        seeded = {
            'g',
            'kg',
            'mg',
            'oz',
            'lb',
            'ml',
            'l',
            'fl oz',
            'cup',
            'pt',
            'qt',
            'gal',
            'pcs',
            'pack',
            'can',
            'bottle',
            'box',
            'bag',
            'm',
            'cm',
        }
        for alias, canonical in UOM_ALIASES.items():
            assert canonical in seeded, f'{alias!r} → {canonical!r} not seeded'


class TestUomResolverAsync:
    """Resolver behavior with a mocked CoreAPI UOM lookup."""

    def _patch_core_api(
        self, monkeypatch: pytest.MonkeyPatch, return_value: object
    ) -> AsyncMock:
        import app.core.uom_resolver as mod

        api = AsyncMock(return_value=return_value)
        core_api = MagicMock()
        core_api.uoms.get_by_symbol_async = api
        # Through monkeypatch, so it is put back: assigned, the mock stayed
        # for every later test on the worker, and a recipe import there
        # resolved no unit at all.
        monkeypatch.setattr(mod, 'core_api', core_api)
        return api

    @pytest.mark.asyncio
    async def test_resolves_canonical_and_aliased_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = self._patch_core_api(monkeypatch, MagicMock(id='uom-kg'))
        resolver = UomResolverAsync(MagicMock(), _ORG_ID)

        assert await resolver.resolve('kg') == 'uom-kg'
        assert await resolver.resolve('kilograms') == 'uom-kg'
        assert await resolver.resolve('KGS') == 'uom-kg'
        # cache hit — repeated canonical symbol does not re-query
        assert await resolver.resolve('kg') == 'uom-kg'
        # kg (exact), kilograms (alias), KGS (uppercase alias) → 3 lookups
        assert api.await_count == 3

    @pytest.mark.asyncio
    async def test_unknown_symbol_returns_none_and_is_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = self._patch_core_api(monkeypatch, None)
        resolver = UomResolverAsync(MagicMock(), _ORG_ID)

        assert await resolver.resolve('furlong') is None
        assert await resolver.resolve('furlong') is None
        assert api.await_count == 1

    @pytest.mark.asyncio
    async def test_empty_symbol_returns_none_without_lookup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = self._patch_core_api(monkeypatch, None)
        resolver = UomResolverAsync(MagicMock(), _ORG_ID)

        assert await resolver.resolve(None) is None
        assert await resolver.resolve('') is None
        assert await resolver.resolve('   ') is None
        api.assert_not_called()
