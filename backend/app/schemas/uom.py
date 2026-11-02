"""Shared Unit of Measure schemas.

Consumed by items, documents (line items) and shopping_lists (embedded UoM
on items). Keeping a single source of truth avoids the previous duplicate
copies that drifted out of sync.
"""

from typing import TYPE_CHECKING

from app.core.contracts import UomInfoDTO

if TYPE_CHECKING:
    from app.models.uom import Uom


class UomInfo(UomInfoDTO):
    """Compact UoM representation for embedding in other schemas.

    Same fields as the contract ``UomInfoDTO``; the subclass keeps the
    component name this API has always published.
    """


class UomInfoWithCategory(UomInfo):
    """The embedded UoM plus the category name, as item responses carry it."""

    category_name: str = ''

    @classmethod
    def from_orm_with_category(cls, uom: 'Uom') -> 'UomInfoWithCategory':
        return cls(
            id=uom.id,
            name=uom.name,
            symbol=uom.symbol,
            rounding=uom.rounding,
            category_name=uom.category.name if uom.category else '',
        )


__all__ = ['UomInfo', 'UomInfoWithCategory']
