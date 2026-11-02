"""Unit tests for the canonical money helpers (app.core.money)."""

from decimal import Decimal

import pytest

from app.core.money import (
    RateAmounts,
    amounts_by_rate,
    line_amounts,
    quantise,
    quantise_or_none,
)


class TestQuantise:
    def test_rounds_half_away_from_zero(self) -> None:
        """Not banker's rounding: 0.005 on an invoice is a cent, not nothing."""
        assert quantise(Decimal('0.005')) == Decimal('0.01')
        assert quantise(Decimal('0.015')) == Decimal('0.02')

    def test_keeps_two_places_by_default(self) -> None:
        assert quantise(Decimal('12')) == Decimal('12.00')
        assert quantise(Decimal('12.3456')) == Decimal('12.35')

    def test_honours_an_explicit_precision(self) -> None:
        assert quantise(Decimal('12.34567'), 4) == Decimal('12.3457')

    def test_none_passes_through(self) -> None:
        assert quantise_or_none(None) is None
        assert quantise_or_none(Decimal('1.005')) == Decimal('1.01')


class TestLineAmounts:
    def test_net_tax_and_gross(self) -> None:
        amounts = line_amounts(Decimal('3'), Decimal('10.00'), Decimal('23'))
        assert amounts.net == Decimal('30.00')
        assert amounts.tax == Decimal('6.90')
        assert amounts.gross == Decimal('36.90')

    def test_gross_is_the_sum_of_what_gets_printed(self) -> None:
        """Rounded net + rounded tax — a receipt that does not add up is a bug."""
        amounts = line_amounts(Decimal('1'), Decimal('0.015'), Decimal('7.5'))
        assert amounts.gross == amounts.net + amounts.tax

    def test_missing_price_or_rate_counts_as_zero(self) -> None:
        assert line_amounts(Decimal('5'), None, Decimal('23')).net == Decimal('0.00')
        no_tax = line_amounts(Decimal('2'), Decimal('4.00'), None)
        assert no_tax.tax == Decimal('0.00')
        assert no_tax.gross == Decimal('8.00')

    def test_unrounded_mode_keeps_full_precision(self) -> None:
        """Callers that total many lines round once, at the end."""
        amounts = line_amounts(
            Decimal('3'), Decimal('0.333'), Decimal('23'), places=None
        )
        assert amounts.net == Decimal('0.999')
        assert amounts.tax == Decimal('0.22977')

    @pytest.mark.parametrize(
        ('quantity', 'unit_price', 'tax_rate', 'expected_gross'),
        [
            (Decimal('2.5'), Decimal('4.80'), Decimal('5'), Decimal('12.60')),
            (Decimal('1'), Decimal('1299.00'), Decimal('23'), Decimal('1597.77')),
            (Decimal('120'), Decimal('0.75'), Decimal('8'), Decimal('97.20')),
        ],
    )
    def test_the_same_arithmetic_serves_every_vertical(
        self,
        quantity: Decimal,
        unit_price: Decimal,
        tax_rate: Decimal,
        expected_gross: Decimal,
    ) -> None:
        """2.5 kg of produce, one laptop, 120 cartons — one helper (AGENTS.md §4)."""
        assert line_amounts(quantity, unit_price, tax_rate).gross == expected_gross


@pytest.mark.unit
class TestAmountsByRate:
    def test_two_rates_are_summed_apart_highest_first(self) -> None:
        rows = [
            (Decimal('7'), Decimal('10.00'), Decimal('0.70')),
            (Decimal('19.00'), Decimal('100.00'), Decimal('19.00')),
            (Decimal('7.00'), Decimal('5.00'), Decimal('0.35')),
        ]
        assert amounts_by_rate(rows) == [
            RateAmounts(
                rate=Decimal('19.00'),
                net=Decimal('100.00'),
                tax=Decimal('19.00'),
                gross=Decimal('119.00'),
            ),
            RateAmounts(
                rate=Decimal('7.00'),
                net=Decimal('15.00'),
                tax=Decimal('1.05'),
                gross=Decimal('16.05'),
            ),
        ]

    def test_untaxed_and_unpriced_rows_belong_to_no_rate(self) -> None:
        rows = [
            (None, Decimal('10.00'), None),
            (Decimal('7'), None, None),
        ]
        assert amounts_by_rate(rows) == []

    def test_a_zero_rate_is_a_rate(self) -> None:
        assert amounts_by_rate([(Decimal('0'), Decimal('4.20'), Decimal('0'))]) == [
            RateAmounts(
                rate=Decimal('0.00'),
                net=Decimal('4.20'),
                tax=Decimal('0.00'),
                gross=Decimal('4.20'),
            )
        ]

    def test_unrounded_parts_are_rounded_once_per_rate(self) -> None:
        rows = [(Decimal('5'), Decimal('0.333'), Decimal('0.01665'))] * 3
        [row] = amounts_by_rate(rows)
        assert (row.net, row.tax, row.gross) == (
            Decimal('1.00'),
            Decimal('0.05'),
            Decimal('1.05'),
        )
