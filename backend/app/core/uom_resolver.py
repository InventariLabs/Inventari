"""Shared UOM resolution helper for import services."""

from typing import get_args
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.i18n._types import Language
from app.i18n.service import get_unit_label

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
    'tablespoon': 'tbsp',
    'tablespoons': 'tbsp',
    'teaspoon': 'tsp',
    'teaspoons': 'tsp',
    'łyżka': 'tbsp',  # PL
    'łyżki': 'tbsp',  # PL
    'łyżeczka': 'tsp',  # PL
    'łyżeczki': 'tsp',  # PL
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
    'unit': 'pcs',  # Odoo writes "Units" and "Unit(s)"
    'units': 'pcs',
    'unit(s)': 'pcs',
    'ea': 'pcs',  # inFlow
    'each': 'pcs',
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
      3. the label the app shows the unit under, in any maintained language,
      4. ``None`` (unknown unit — caller decides how to surface it).
    """

    def __init__(self, db: AsyncSession, organization_id: UUID):
        self.db = db
        self.organization_id = organization_id
        self._cache: dict[str, UUID] = {}
        self._miss_cache: set[str] = set()
        self._labels: dict[str, UUID] | None = None

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
        found = uom.id if uom else (await self._by_label()).get(normalized)
        if found is None:
            self._miss_cache.add(normalized)
            return None
        self._cache[normalized] = found
        return found

    async def _by_label(self) -> dict[str, UUID]:
        """Unit id by each label the app shows for it, whatever the language.

        A sheet is written in its author's language, not necessarily the
        importer's. An organization's own unit wins over a system one that
        shares a label.
        """
        if self._labels is None:
            uoms = await core_api.uoms.list_for_org_async(self.db, self.organization_id)
            own_last = sorted(uoms, key=lambda u: u.organization_id is not None)
            self._labels = {
                get_unit_label(u.symbol, lang).lower().rstrip('.'): u.id
                for lang in get_args(Language)
                for u in own_last
            }
        return self._labels
