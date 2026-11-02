"""Shared UOM resolution helper for import services."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

# Unit aliases normalized during import. Maps common spellings / plural
# forms / localized seeds onto canonical system symbols. Keys are already
# lowercase; lookup normalizes with ``.lower().strip()`` before matching.
UOM_ALIASES: dict[str, str] = {
    # Weight
    'kilogram': 'kg',
    'kilograms': 'kg',
    'kgs': 'kg',
    'kg.': 'kg',
    'gram': 'g',
    'grams': 'g',
    'g.': 'g',
    'milligram': 'mg',
    'milligrams': 'mg',
    'mgs': 'mg',
    'mg.': 'mg',
    'ounce': 'oz',
    'ounces': 'oz',
    'oz.': 'oz',
    'pound': 'lb',
    'pounds': 'lb',
    'lbs': 'lb',
    # Volume
    'liter': 'l',
    'liters': 'l',
    'litre': 'l',
    'litres': 'l',
    'l.': 'l',
    'milliliter': 'ml',
    'milliliters': 'ml',
    'millilitre': 'ml',
    'millilitres': 'ml',
    'ml.': 'ml',
    'fluid ounce': 'fl oz',
    'fluid ounces': 'fl oz',
    'cup': 'cup',
    'cups': 'cup',
    'pint': 'pt',
    'pints': 'pt',
    'quart': 'qt',
    'quarts': 'qt',
    'gallon': 'gal',
    'gallons': 'gal',
    # Unit / countable
    'piece': 'pcs',
    'pieces': 'pcs',
    'pc': 'pcs',
    'pcs.': 'pcs',
    'szt': 'pcs',  # PL
    'szt.': 'pcs',  # PL
    'sztuka': 'pcs',  # PL
    'sztuki': 'pcs',  # PL
    'stück': 'pcs',  # DE
    'stk': 'pcs',  # DE
    'unité': 'pcs',  # FR
    'unidades': 'pcs',  # ES
    'packs': 'pack',
    'opak': 'pack',  # PL
    'opakowanie': 'pack',  # PL
    'paquete': 'pack',  # ES
    'can': 'can',
    'cans': 'can',
    'puszka': 'can',  # PL
    'bottle': 'bottle',
    'bottles': 'bottle',
    'butelka': 'bottle',  # PL
    'box': 'box',
    'boxes': 'box',
    'pudełko': 'box',  # PL
    'bag': 'bag',
    'bags': 'bag',
    'torebka': 'bag',  # PL
    # Length
    'meter': 'm',
    'meters': 'm',
    'metre': 'm',
    'metres': 'm',
    'centimeter': 'cm',
    'centimeters': 'cm',
    'centimetre': 'cm',
    'centimetres': 'cm',
}


class UomResolverAsync:
    """Async UOM resolver with caching for use with AsyncSession.

    Org-scoped: resolves against UOMs owned by *organization_id* plus
    system UOMs (``organization_id IS NULL``).

    Resolution order:
      1. exact symbol (case-insensitive, trimmed),
      2. alias map (``UOM_ALIASES``) → canonical symbol,
      3. ``None`` (unknown unit — caller decides how to surface it).
    """

    def __init__(self, db: AsyncSession, organization_id: UUID):
        self.db = db
        self.organization_id = organization_id
        self._cache: dict[str, UUID] = {}
        self._miss_cache: set[str] = set()

    async def resolve(self, symbol: str | None) -> UUID | None:
        if not symbol or not symbol.strip():
            return None
        normalized = symbol.lower().strip().rstrip('.')
        if normalized in self._cache:
            return self._cache[normalized]
        if normalized in self._miss_cache:
            return None
        candidate = UOM_ALIASES.get(normalized, normalized)
        uom = await core_api.uoms.get_by_symbol_async(
            self.db, candidate, self.organization_id
        )
        if uom:
            self._cache[normalized] = uom.id
            return uom.id
        self._miss_cache.add(normalized)
        return None
