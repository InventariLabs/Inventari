"""Which price list entry prices an order of a given size.

An entry is a candidate only when the quantity reaches it (no minimum, or a
minimum the quantity has met), and entries in different currencies are never
ordered by their bare numbers.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.modules.purchase_orders.pricelist_service import pick_offer


def _entry(price: str, *, minimum: str | None = None, currency: str = 'PLN') -> Any:
    return SimpleNamespace(
        id=uuid4(),
        unit_price=Decimal(price),
        min_quantity=Decimal(minimum) if minimum is not None else None,
        currency=currency,
    )


def test_a_tier_the_quantity_does_not_reach_is_not_a_price() -> None:
    base = _entry('3.00')
    bulk = _entry('2.00', minimum='1000')
    assert pick_offer([bulk, base], Decimal('29'), 'PLN') is base


def test_nothing_is_reached_means_no_offer() -> None:
    bulk = _entry('2.00', minimum='1000')
    assert pick_offer([bulk], Decimal('29'), 'PLN') is None


def test_a_cheaper_entry_with_no_minimum_beats_a_dearer_reached_tier() -> None:
    cheap = _entry('1.00')
    tier = _entry('2.00', minimum='10')
    assert pick_offer([cheap, tier], Decimal('50'), 'PLN') is cheap


def test_a_reached_tier_beats_the_base_price_when_cheaper() -> None:
    base = _entry('3.00')
    tier = _entry('2.00', minimum='100')
    assert pick_offer([tier, base], Decimal('100'), 'PLN') is tier


def test_no_quantity_asked_considers_every_entry() -> None:
    base = _entry('3.00')
    bulk = _entry('2.00', minimum='1000')
    assert pick_offer([base, bulk], None, 'PLN') is bulk


def test_the_house_currency_wins_over_a_smaller_number_in_another() -> None:
    euro = _entry('4.00', currency='EUR')
    zloty = _entry('5.00', currency='PLN')
    assert pick_offer([euro, zloty], Decimal('1'), 'PLN') is zloty


def test_without_a_house_currency_offer_one_foreign_currency_is_chosen() -> None:
    dear_usd = _entry('9.00', currency='USD')
    cheap_usd = _entry('7.00', currency='USD')
    euro = _entry('1.00', currency='EUR')
    # EUR sorts first, so it is chosen whole; never a mix of currencies.
    assert pick_offer([dear_usd, cheap_usd, euro], Decimal('1'), 'PLN') is euro
    assert pick_offer([dear_usd, cheap_usd], Decimal('1'), 'PLN') is cheap_usd
