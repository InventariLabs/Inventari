"""What an intermediate product already has on the shelf, before it is made.

A formula line whose ingredient has a recipe of its own — dough in the
bread, a sauce in the dish — used to be exploded all the way down to its
leaves, so the dough made yesterday stayed on the shelf while today's run
took flour again. Every multi-level tool in the field takes the intermediate
from its own stock first and makes only the part the stock does not cover.

``StockPool`` is the one answer to "how much of this intermediate can a run
take from the shelf". The explosion asks it line by line, and every reader of
a plan — availability, the preview, the cost estimate, the shortage list and
completion itself — explodes through the same pool, so they cannot disagree
about the split. A pool is spent as it is asked: two lines that name the same
intermediate do not both count the same dough.

The pool is read lazily, a level of the formula at a time, and only for
ingredients that have a recipe: a leaf is taken from the shelf by the draw as
it always was.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UomDTO
from app.core.public_api import core_api


class _Loaded:
    """What the shelf holds, read once and shared by every fork of a pool."""

    def __init__(self) -> None:
        self.stock: dict[UUID, Decimal] = {}
        self.stock_uom_ids: dict[UUID, UUID | None] = {}
        self.uoms: dict[UUID, UomDTO] | None = None


class StockPool:
    """Available stock per intermediate, spent as the explosion takes from it.

    *location_id* is the scope the availability check judges a run under — the
    run's own shelf under PER_LOCATION, the whole organisation under GLOBAL —
    so the pool and the draw that follows read the same stock.
    """

    def __init__(
        self,
        db: AsyncSession,
        organization_id: UUID,
        location_id: UUID | None,
        *,
        _loaded: _Loaded | None = None,
    ) -> None:
        self._db = db
        self._org = organization_id
        self._location_id = location_id
        self._loaded = _loaded if _loaded is not None else _Loaded()
        self._used: dict[UUID, Decimal] = {}

    @property
    def spent(self) -> bool:
        """Whether the explosion took anything from this pool."""
        return any(qty > 0 for qty in self._used.values())

    def fork(self) -> StockPool:
        """A pool with nothing spent yet, over the stock this one already read."""
        return StockPool(self._db, self._org, self._location_id, _loaded=self._loaded)

    async def ensure(self, template_ids: Iterable[UUID]) -> None:
        """Read the stock of the templates not read yet, in one round."""
        loaded = self._loaded
        missing = sorted(
            {tid for tid in template_ids if tid not in loaded.stock_uom_ids}
        )
        if not missing:
            return
        quants = await core_api.stock.list_quants_async(
            self._db,
            self._org,
            storage_location_id=self._location_id,
            product_template_ids=missing,
            drawable_only=True,
        )
        for quant in quants:
            if quant.available_quantity > 0:
                loaded.stock[quant.product_template_id] = (
                    loaded.stock.get(quant.product_template_id, Decimal('0'))
                    + quant.available_quantity
                )
        templates = await core_api.product_templates.get_many_async(
            self._db, self._org, missing
        )
        for tid in missing:
            template = templates.get(tid)
            loaded.stock_uom_ids[tid] = template.uom_id if template else None
        if loaded.uoms is None:
            loaded.uoms = {
                uom.id: uom
                for uom in await core_api.uoms.list_for_org_async(self._db, self._org)
            }

    def expect(self, template_id: UUID, qty: Decimal) -> None:
        """Count *qty* of *template_id* as on the shelf: a planned run will make it.

        Meant for a planning view, before the first explosion reads the pool:
        a sub-assembly that a draft run already makes is not made again by the
        run that needs it. The stock read by :meth:`ensure` is added to it.
        """
        loaded = self._loaded
        loaded.stock[template_id] = loaded.stock.get(template_id, Decimal('0')) + qty

    def on_hand(self, template_id: UUID) -> Decimal:
        """What the shelf holds of *template_id*, in its own stock unit."""
        return self._loaded.stock.get(template_id, Decimal('0'))

    def on_hand_in(self, template_id: UUID, line_uom_id: UUID | None) -> Decimal | None:
        """What the shelf holds of *template_id*, in the unit a line names.

        ``None`` when the line's unit has no bridge to the stock's: the same
        case in which :meth:`take` takes nothing.
        """
        qty = self.on_hand(template_id)
        stock_uom_id = self._loaded.stock_uom_ids.get(template_id)
        if line_uom_id is None or stock_uom_id is None or line_uom_id == stock_uom_id:
            return qty
        uoms = self._loaded.uoms or {}
        converted, ok = core_api.uoms.convert_quantity(
            qty, uoms.get(stock_uom_id), uoms.get(line_uom_id)
        )
        return converted if ok else None

    def take(
        self, template_id: UUID, qty: Decimal, line_uom_id: UUID | None
    ) -> Decimal:
        """Take up to *qty* (in the line's unit) from the shelf; return what was taken.

        The answer is in the line's unit too, so the caller subtracts it from
        what the line needs. A line whose unit has no bridge to the stock's
        takes nothing: the run then makes it, as it did before this rule.
        """
        if qty <= 0:
            return Decimal('0')
        loaded = self._loaded
        stock_uom_id = loaded.stock_uom_ids.get(template_id)
        need_in_stock_unit = qty
        if (
            line_uom_id is not None
            and stock_uom_id is not None
            and line_uom_id != stock_uom_id
        ):
            uoms = loaded.uoms or {}
            need_in_stock_unit, ok = core_api.uoms.convert_quantity(
                qty,
                uoms.get(line_uom_id),
                uoms.get(stock_uom_id),
            )
            if not ok:
                return Decimal('0')
        left = loaded.stock.get(template_id, Decimal('0')) - self._used.get(
            template_id, Decimal('0')
        )
        if left <= 0:
            return Decimal('0')
        if left >= need_in_stock_unit:
            self._used[template_id] = (
                self._used.get(template_id, Decimal('0')) + need_in_stock_unit
            )
            return qty
        self._used[template_id] = self._used.get(template_id, Decimal('0')) + left
        return qty * left / need_in_stock_unit
