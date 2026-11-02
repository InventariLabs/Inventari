"""How full a shelf is — the one answer every reader of a shelf shares.

A limit is declared per product, in that product's own stock unit, so two
limits on one shelf never add up: 40 bags of rice and 50 kg of plums are
not 90 of anything. What does add up is each product's share of the room
it was given. 20 bags of rice is half of the rice room, 25 kg of plums half
of the plum room, and a shelf holding both is full: 0.5 + 0.5. The planner
used to ask one product at a time and kept sending goods to that shelf.

The putaway planner, the occupancy read and every screen that draws a fill
go through ``shelf_fill``; none of them computes a percentage of its own, so
no screen can call a shelf half empty that the planner calls full.

A product standing on the shelf with no limit of its own adds no share —
nobody said how much room it takes — and the fill says so through
``unmeasured`` rather than pretending the shelf is emptier than it looks.

The arithmetic is exact (``Fraction``): a limit of 3 split in thirds must
not round its way over 100%.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

#: From this share on a shelf reads "nearly full".
NEARLY_FULL = Fraction(85, 100)

STATUS_EMPTY = 'empty'
STATUS_NO_LIMIT = 'no_limit'
STATUS_OK = 'ok'
STATUS_NEARLY_FULL = 'nearly_full'
STATUS_OVER = 'over'


def _decimal(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


@dataclass(frozen=True)
class ProductShare:
    """One product on the shelf: its quantity, its limit, its share.

    ``share`` and ``max_quantity`` are None for a product without a limit
    on this shelf — unmeasured, not zero.
    """

    product_template_id: UUID
    quantity: Decimal
    max_quantity: Decimal | None
    share: Decimal | None


@dataclass(frozen=True)
class ShelfFill:
    shares: list[ProductShare]
    #: Sum of the shares, exact. None when no product has a limit here.
    exact: Fraction | None
    #: A product stands here without a limit of its own.
    unmeasured: bool
    status: str
    _limits: Mapping[UUID, Decimal]

    @property
    def fill(self) -> Decimal | None:
        return _decimal(self.exact) if self.exact is not None else None

    @property
    def percent(self) -> int | None:
        """The fill as a whole percentage, for a reader."""
        return round(self.exact * 100) if self.exact is not None else None

    def fits(self, product_template_id: UUID | None, quantity: Decimal) -> bool:
        """Whether ``quantity`` more of the product keeps the sum within 1.

        A product with no limit here takes no share and always fits."""
        limit = self._limits.get(product_template_id) if product_template_id else None
        if not limit:
            return True
        taken = self.exact or Fraction(0)
        return taken + Fraction(quantity) / Fraction(limit) <= 1


def shelf_fill(
    quantities: Mapping[UUID, Decimal],
    limits: Mapping[UUID, Decimal],
    *,
    unlisted: int = 0,
) -> ShelfFill:
    """The fill of one shelf from what stands on it and the limits set there.

    ``quantities`` is each product's stock on the shelf (plus whatever a
    caller has already planned to send there), ``limits`` the shelf's
    limit per product, both in the product's stock unit. A limited product
    with nothing on the shelf is listed with a zero share; an unlimited one
    is listed only while it stands there.

    ``unlisted`` counts the products standing on the shelf that
    ``quantities`` leaves out — a reader of a whole floor names the limited
    products and counts the rest. They have no limit here, by the caller's
    word, so they add no share; they still make the shelf not empty and its
    fill unmeasured.
    """
    stocked = {pid: qty for pid, qty in quantities.items() if qty and qty > 0}
    shares: list[ProductShare] = []
    exact: Fraction | None = None
    for pid, limit in limits.items():
        if not limit:
            continue
        quantity = quantities.get(pid) or Decimal('0')
        share = Fraction(quantity) / Fraction(limit)
        exact = (exact or Fraction(0)) + share
        shares.append(
            ProductShare(
                product_template_id=pid,
                quantity=quantity,
                max_quantity=limit,
                share=_decimal(share),
            )
        )
    unlimited = [pid for pid in stocked if not limits.get(pid)]
    shares.extend(
        ProductShare(
            product_template_id=pid,
            quantity=stocked[pid],
            max_quantity=None,
            share=None,
        )
        for pid in unlimited
    )

    if not stocked and not unlisted:
        status = STATUS_EMPTY
    elif exact is None:
        status = STATUS_NO_LIMIT
    elif exact > 1:
        status = STATUS_OVER
    elif exact >= NEARLY_FULL:
        status = STATUS_NEARLY_FULL
    else:
        status = STATUS_OK
    return ShelfFill(
        shares=shares,
        exact=exact,
        unmeasured=bool(unlimited) or unlisted > 0,
        status=status,
        _limits={pid: lim for pid, lim in limits.items() if lim},
    )
