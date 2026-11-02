"""UOM conversion helpers used by recipe availability checks.

Lives in its own module so tests can import the conversion helpers
directly without pulling in the full CRUD/availability machinery.

Both conversions here delegate to the core converter through the
public API (``core_api.uoms.convert_quantity``) — there is one conversion
mechanism, and its rule is that an impossible conversion is a refusal,
never the same number back. :func:`_convert_qty_to_uom` is the plain
factor ratio and says ``None`` when the measures don't meet.
:func:`convert_qty_for_template` answers the question the shelf cares
about and says ``None`` instead of guessing: a recipe asking for 400 g
and a shelf holding 7 pieces are not comparable until something says
what one piece weighs.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Protocol, cast
from uuid import UUID

from app.core.contracts import UomDTO


class UomLike(Protocol):
    """Structural type covering the UOM attributes read by conversion helpers.

    Accepts both the ORM ``Uom`` model and the ``UomDTO`` contract (used in
    unit tests), since only ``id``, ``category_id`` and ``factor`` are read.
    """

    @property
    def id(self) -> UUID: ...

    @property
    def category_id(self) -> UUID: ...

    @property
    def factor(self) -> Decimal: ...


class PackagedTemplate(Protocol):
    """The template fields that bridge a countable unit to a physical measure.

    ``weight_value`` / ``volume_value`` state what one stock unit of the
    template amounts to — the column comment says it outright, "1 Piece =
    500g" — which is the only thing that can put pieces and grams on the
    same scale.
    """

    @property
    def uom_id(self) -> UUID | None: ...

    @property
    def weight_value(self) -> Decimal | float | None: ...

    @property
    def weight_uom_id(self) -> UUID | None: ...

    @property
    def volume_value(self) -> Decimal | float | None: ...

    @property
    def volume_uom_id(self) -> UUID | None: ...


def _convert_qty_to_uom(
    qty: Decimal,
    source_uom: UomLike | None,
    target_uom: UomLike | None,
) -> Decimal | None:
    """Convert *qty* from *source_uom* to *target_uom* using factor ratio.

    Delegates to the core converter through the public API. Returns
    ``None`` when conversion is impossible (None UOM or cross-category
    mismatch or zero target factor) — a refusal, not the same number
    back.
    """
    from app.core.public_api import core_api

    converted, ok = core_api.uoms.convert_quantity(
        qty,
        cast('UomDTO | None', source_uom),
        cast('UomDTO | None', target_uom),
    )
    return converted if ok else None


def convert_qty_for_template(
    qty: Decimal,
    source_uom: UomLike | None,
    target_uom: UomLike | None,
    template: PackagedTemplate | None = None,
    uoms_by_id: Mapping[UUID, UomLike] | None = None,
) -> Decimal | None:
    """Convert *qty* into *target_uom*, or return None when the measures don't meet.

    ``None`` is the honest answer for "7 pieces against 400 g with nothing
    saying what a piece weighs". It is not the same answer as "there is
    none left", and callers must not collapse the two.
    """
    if source_uom is None and target_uom is None:
        return qty
    if source_uom is None or target_uom is None:
        return None
    if source_uom.id == target_uom.id:
        return qty
    if source_uom.category_id == target_uom.category_id:
        return _convert_qty_to_uom(qty, source_uom, target_uom)
    return _bridge_through_template(
        qty, source_uom, target_uom, template, uoms_by_id or {}
    )


def _bridge_through_template(
    qty: Decimal,
    source_uom: UomLike,
    target_uom: UomLike,
    template: PackagedTemplate | None,
    uoms_by_id: Mapping[UUID, UomLike],
) -> Decimal | None:
    """Cross the unit-category boundary using what one stock unit measures."""
    if template is None:
        return None
    stock_uom = _lookup(uoms_by_id, getattr(template, 'uom_id', None))
    for value, measure_uom_id in (
        (template.weight_value, template.weight_uom_id),
        (template.volume_value, template.volume_uom_id),
    ):
        measure_uom = _lookup(uoms_by_id, measure_uom_id)
        if not value or measure_uom is None:
            continue
        per_unit = Decimal(str(value))
        if per_unit == 0:
            continue
        if _same_category(target_uom, measure_uom) and not _same_category(
            source_uom, measure_uom
        ):
            # Counted stock asked about in a physical measure.
            if stock_uom is not None and not _same_category(source_uom, stock_uom):
                # e.g. an ingredient counted in packs against a product
                # stocked in pieces: nothing says how many pieces a pack
                # holds, so refuse rather than equate one pack with one pc.
                return None
            units = (
                qty
                if stock_uom is None
                else _convert_qty_to_uom(qty, source_uom, stock_uom)
            )
            if units is None:
                return None
            return _convert_qty_to_uom(units * per_unit, measure_uom, target_uom)
        if _same_category(source_uom, measure_uom) and not _same_category(
            target_uom, measure_uom
        ):
            # A physical measure asked about in counted stock.
            measured = _convert_qty_to_uom(qty, source_uom, measure_uom)
            if measured is None:
                return None
            units = measured / per_unit
            if stock_uom is None:
                # The template names no stock unit, so the bare quotient
                # already answers in the target's counted scale.
                return units
            if not _same_category(target_uom, stock_uom):
                return None
            return _convert_qty_to_uom(units, stock_uom, target_uom)
    return None


def _lookup(uoms_by_id: Mapping[UUID, UomLike], uom_id: UUID | None) -> UomLike | None:
    return uoms_by_id.get(uom_id) if uom_id is not None else None


def _same_category(left: UomLike, right: UomLike) -> bool:
    return left.category_id == right.category_id
