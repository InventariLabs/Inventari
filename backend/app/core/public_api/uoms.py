"""Module-safe read-only access to Units of Measure (UOM)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UomCategoryDTO, UomDTO
from app.core.logging import get_logger

logger = get_logger(__name__)


class CoreUomsAPI:
    """Public Core API for module-safe UOM reads."""

    async def get_by_symbol_async(
        self,
        db: AsyncSession,
        symbol: str,
        organization_id: UUID,
        *,
        include_global: bool = False,
    ) -> UomDTO | None:
        """Async: return the UOM DTO whose ``symbol`` matches *symbol* exactly, or ``None``.

        Searches UOMs owned by *organization_id* plus system UOMs
        (``organization_id IS NULL``), preferring the org-specific row.
        Pass ``include_global=True`` (admin/tooling paths only) to match
        UOMs owned by any organization.
        """
        from app.services.uom_service import get_uom_by_symbol_async

        uom = await get_uom_by_symbol_async(
            db, symbol, organization_id=None if include_global else organization_id
        )
        return UomDTO.model_validate(uom) if uom else None

    async def get_async(
        self, db: AsyncSession, uom_id: UUID, organization_id: UUID
    ) -> UomDTO | None:
        """Return the UOM row for *uom_id*, or ``None``.

        Only a unit owned by *organization_id* or a system unit
        (``organization_id IS NULL``) is returned; another organization's
        unit reads as absent. The org is required — a method addressed by an
        id alone leaves isolation to whichever caller remembers it.
        """
        from app.services.uom_service import get_uom_async

        uom = await get_uom_async(db, uom_id, organization_id)
        return UomDTO.model_validate(uom) if uom else None

    async def existing_ids_async(
        self, db: AsyncSession, uom_ids: set[UUID], organization_id: UUID
    ) -> set[UUID]:
        """Return the subset of *uom_ids* that exist for *organization_id* — one query."""
        from app.services.uom_service import existing_uom_ids_async

        return await existing_uom_ids_async(db, uom_ids, organization_id)

    def convert_quantity(
        self, qty: Decimal, source: UomDTO | None, target: UomDTO | None
    ) -> tuple[Decimal, bool]:
        """Convert *qty* from *source* to *target* UoM (factor-ratio, same category).

        Pure computation (no I/O) — hence sync. Returns ``(qty, False)`` when
        conversion is impossible (None UoM, different category, zero factor).
        """
        from app.services.uom_service import convert_quantity

        return convert_quantity(qty, source, target)

    def quantity_step(self, uom: UomDTO | None) -> Decimal:
        """The step quantities in *uom* are counted in — its own ``rounding``,
        floored at the scale the quantity columns keep.

        Pure computation (no I/O) — hence sync.
        """
        from app.services.uom_service import quantity_step

        return quantity_step(uom)

    def quantize(self, qty: Decimal, uom: UomDTO | None) -> Decimal:
        """*qty* on the nearest step of *uom* — the rounding a measurement takes.

        Pass ``uom=None`` to ask only for the scale the quantity columns keep,
        which is the honest answer where no unit's step applies.

        Pure computation (no I/O) — hence sync.
        """
        from app.services.uom_service import quantize_to_uom

        return quantize_to_uom(qty, uom)

    def round_up(self, qty: Decimal, uom: UomDTO | None) -> Decimal:
        """*qty* on the next step of *uom* at or above it — the rounding a
        requirement takes, so that needing part of a step never reads as zero.

        Pure computation (no I/O) — hence sync.
        """
        from app.services.uom_service import round_up_to_uom

        return round_up_to_uom(qty, uom)

    def is_on_step(self, qty: Decimal, uom: UomDTO | None) -> bool:
        """Whether *qty* already sits on a step of *uom*.

        The counterpart of :meth:`round_up`: a requirement it hands back
        unchanged was on its step, so no rounding happened and a card has
        nothing to explain. A quotient's last-place noise does not count
        against the answer.

        Pure computation (no I/O) — hence sync.
        """
        from app.services.uom_service import is_on_uom_step

        return is_on_uom_step(qty, uom)

    async def to_canonical_measure_async(
        self,
        db: AsyncSession,
        qty: Decimal,
        uom: UomDTO | None,
    ) -> tuple[Decimal, str] | None:
        """Express *qty* in the reference unit of *uom*'s category.

        Returns ``(amount, symbol)`` — e.g. ``(Decimal('28.3495'), 'g')``
        for one ounce — or ``None`` when there is no unit or the measures
        don't meet. Counted and packaging units have no canonical measure.
        """
        from app.services.uom_service import to_canonical_measure_async

        measure = await to_canonical_measure_async(db, qty, uom)
        return (measure.amount, measure.symbol) if measure else None

    async def to_stock_uom_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID | None,
        quantity: Decimal,
        uom_id: UUID | None,
    ) -> Decimal:
        """Express *quantity*, stated in *uom_id*, in the product's stock unit.

        Raises ``ValueError`` naming both symbols when the two units do not
        convert. Passes the quantity through when either side names no unit.
        """
        from app.services.uom_service import to_stock_uom_async

        return await to_stock_uom_async(
            db, organization_id, product_template_id, quantity, uom_id
        )

    async def validate_quantity_precision_async(
        self,
        db: AsyncSession,
        uom_id: UUID,
        quantity: Decimal,
        organization_id: UUID,
    ) -> None:
        """Async: raise ValueError if quantity violates the precision rules of the given UoM.

        The unit must be owned by *organization_id* or be a system unit;
        another organization's unit is refused like an unknown one.
        """
        from app.services.uom_service import validate_quantity_precision_async

        return await validate_quantity_precision_async(
            db, uom_id, quantity, organization_id
        )

    async def list_for_org_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> list[UomDTO]:
        """Return all UOM rows visible to *organization_id* (system + org-specific)."""
        from app.services.uom_service import list_uoms_for_org_async

        uoms = await list_uoms_for_org_async(db, organization_id)
        return [UomDTO.model_validate(u) for u in uoms]

    async def list_categories_for_org_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> list[UomCategoryDTO]:
        """Return all UOM categories visible to *organization_id* (system + org-specific)."""
        from app.services.uom_service import list_uom_categories_for_org_async

        categories = await list_uom_categories_for_org_async(db, organization_id)
        return [UomCategoryDTO.model_validate(c) for c in categories]
