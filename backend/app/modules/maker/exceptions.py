"""Custom exceptions for the maker module.

``ShortageWarning`` and ``ShortageBlocked`` carry the shortage list
so the router can return actionable 422 responses without the caller needing
to re-compute the shortage.
"""

from __future__ import annotations

from uuid import UUID

from .availability_service import ShortageItem


class ShortageError(Exception):
    """Base class for shortage-related exceptions."""

    def __init__(self, shortages: list[ShortageItem]) -> None:
        self.shortages = shortages
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        lines = ['Insufficient stock for production:']
        for s in self.shortages:
            name = s.child_template_name or str(s.child_template_id)
            uom = s.uom_symbol or ''
            if s.shortage is None:
                stock_uom = s.available_uom_symbol or ''
                lines.append(
                    f'  {name}: needed {s.needed} {uom}, in stock '
                    f'{s.available} {stock_uom} — units cannot be compared'
                )
                continue
            lines.append(
                f'  {name}: needed {s.needed} {uom}, available {s.available} {uom}, '
                f'short {s.shortage} {uom}'
            )
        return '\n'.join(lines)

    def to_detail(self) -> list[dict[str, object]]:
        """Serialize shortage list for JSON API responses."""
        return [
            {
                'child_template_id': str(s.child_template_id),
                'child_template_name': s.child_template_name,
                'needed': str(s.needed),
                'available': str(s.available),
                # null, not "None": the shortage of an ingredient whose
                # measures cannot meet is unknown, not zero.
                'shortage': None if s.shortage is None else str(s.shortage),
                'uom_symbol': s.uom_symbol,
                'convertible': s.convertible,
                'available_uom_symbol': s.available_uom_symbol,
            }
            for s in self.shortages
        ]


class ShortageBlockedError(ShortageError):
    """create_on_shortage_strategy=BLOCK: DRAFT creation refused (422)."""


class ShortageWarningError(ShortageError):
    """create_on_shortage_strategy=WARN: returns warning, needs confirm."""


class InsufficientStockError(ShortageError):
    """complete_production: actionable 422 with shortage list.

    ``short_at_create`` says whether the run was born over stock (the
    organization recorded the fact at creation) — the dialog can then say
    "never enough" instead of inventing a theft that never happened.
    """

    def __init__(
        self,
        shortages: list[ShortageItem],
        *,
        short_at_create: bool = False,
    ) -> None:
        super().__init__(shortages)
        self.short_at_create = short_at_create


class EmptyBillOfMaterialsError(Exception):
    """complete_production: the run would consume nothing (422).

    Completing an order whose recipe lists no ingredients used to create the
    output item and its StockQuant row against zero consumption — goods out of
    thin air. The recipe identity travels with the error so the UI can send the
    operator straight to the composition tab.
    """

    def __init__(self, recipe_id: UUID | None, recipe_name: str | None) -> None:
        self.recipe_id = recipe_id
        self.recipe_name = recipe_name
        super().__init__(
            f'Recipe {recipe_name or recipe_id or "(none)"} lists no ingredients; '
            'production would consume nothing'
        )

    def to_detail(self) -> dict[str, object]:
        """Serialize for the JSON API response."""
        return {
            'error': 'empty_bom',
            'recipe_id': str(self.recipe_id) if self.recipe_id else None,
            'recipe_name': self.recipe_name,
        }


class RecipeInUseError(Exception):
    """DELETE recipe refused: referenced by production orders (409)."""


class DuplicateBomLineError(Exception):
    """Adding an ingredient the recipe already lists (409)."""
