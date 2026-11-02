"""Canonical money arithmetic — rounding and net/tax/gross, in one place.

Five modules were computing the same three numbers from a quantity, a unit
price and a percentage tax rate, and two more carried their own rounding
helper (``_q2``, ``_quantise``). Same arithmetic, five chances to drift.

Two decisions this module makes on everyone's behalf:

* **Rounding is HALF_UP.** Python's default for ``Decimal.quantize`` is
  banker's rounding, which turns 0.005 into 0.00 — correct for statistics,
  surprising on an invoice.
* **Rounding is optional.** A document line stores rounded amounts because
  the sum has to match what the tax summary shows; a PDF render context and
  a list envelope total the raw values and round once at the end. Pass
  ``places=None`` to keep full precision.

Domain-neutral by construction: quantity × price + percentage tax is the
same operation for food, equipment and warehouse stock.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal('0')


def quantise(value: Decimal, places: int = 2) -> Decimal:
    """Round *value* to *places* decimals, half away from zero."""
    return value.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)


def quantise_or_none(value: Decimal | None, places: int = 2) -> Decimal | None:
    """``quantise`` that passes ``None`` through — the usual case for a nullable price."""
    return None if value is None else quantise(value, places)


@dataclass(frozen=True)
class LineAmounts:
    """What one priced line is worth: before tax, the tax, and together."""

    net: Decimal
    tax: Decimal
    gross: Decimal


def line_amounts(
    quantity: Decimal,
    unit_price: Decimal | None,
    tax_rate_pct: Decimal | None,
    *,
    places: int | None = 2,
) -> LineAmounts:
    """Net, tax and gross for *quantity* at *unit_price* with a percentage rate.

    A missing price or rate counts as zero — a line without a price is worth
    nothing, not an error. ``places=None`` skips rounding for callers that
    accumulate first and round the total.
    """
    net = Decimal(quantity) * Decimal(unit_price if unit_price is not None else ZERO)
    rate = Decimal(tax_rate_pct if tax_rate_pct is not None else ZERO)
    tax = net * rate / Decimal('100')
    gross = net + tax
    if places is None:
        return LineAmounts(net=net, tax=tax, gross=gross)
    # Gross is the sum of the rounded parts, not the rounded sum: the printed
    # net and tax have to add up to the printed gross.
    net = quantise(net, places)
    tax = quantise(tax, places)
    return LineAmounts(net=net, tax=tax, gross=net + tax)


@dataclass(frozen=True)
class RateAmounts:
    """What the lines taxed at one rate add up to."""

    rate: Decimal
    net: Decimal
    tax: Decimal
    gross: Decimal


def amounts_by_rate(
    rows: Iterable[tuple[Decimal | None, Decimal | None, Decimal | None]],
) -> list[RateAmounts]:
    """Net and tax summed per tax rate, highest rate first.

    *rows* are ``(rate, net, tax)``, rounded or not; each sum is rounded
    once, and the gross is the sum of the rounded parts, so a printed row
    adds up. A row without a rate or a net is untaxed or unpriced and
    belongs to no rate. One document carrying food at a reduced rate and
    other goods at the standard one is the case this answers: the law asks
    for the amounts per rate, not only the total.
    """
    sums: dict[Decimal, tuple[Decimal, Decimal]] = {}
    for rate, net, tax in rows:
        if rate is None or net is None:
            continue
        key = quantise(Decimal(rate))
        prior_net, prior_tax = sums.get(key, (ZERO, ZERO))
        sums[key] = (prior_net + Decimal(net), prior_tax + Decimal(tax or ZERO))
    result = []
    for rate in sorted(sums, reverse=True):
        net, tax = (quantise(value) for value in sums[rate])
        result.append(RateAmounts(rate=rate, net=net, tax=tax, gross=net + tax))
    return result
