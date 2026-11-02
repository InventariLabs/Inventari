"""Unit tests for depreciation_service — pure computation logic."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.equipment.depreciation_service import (
    DEFAULT_USEFUL_LIFE_YEARS,
    ZERO,
    compute_book_value,
)


@pytest.mark.unit
class TestComputeBookValue:
    """Tests for compute_book_value() pure function."""

    def test_no_purchase_price_returns_not_depreciable(self) -> None:
        result = compute_book_value(None, date(2023, 1, 1), as_of=date(2026, 1, 1))
        assert result['is_depreciable'] is False
        assert result['book_value'] == ZERO
        assert result['depreciation_pct'] == ZERO

    def test_zero_purchase_price_returns_not_depreciable(self) -> None:
        result = compute_book_value(
            Decimal('0'), date(2023, 1, 1), as_of=date(2026, 1, 1)
        )
        assert result['is_depreciable'] is False

    def test_negative_purchase_price_returns_not_depreciable(self) -> None:
        result = compute_book_value(
            Decimal('-100'), date(2023, 1, 1), as_of=date(2026, 1, 1)
        )
        assert result['is_depreciable'] is False

    def test_no_purchase_date_returns_not_depreciable(self) -> None:
        result = compute_book_value(Decimal('1000'), None, as_of=date(2026, 1, 1))
        assert result['is_depreciable'] is False
        assert result['book_value'] == Decimal('1000')

    def test_empty_string_purchase_date_returns_not_depreciable(self) -> None:
        result = compute_book_value(Decimal('1000'), '', as_of=date(2026, 1, 1))
        assert result['is_depreciable'] is False

    def test_zero_useful_life_returns_not_depreciable(self) -> None:
        """Zero years is not a configuration, it is the absence of one.

        A purchase date with a zero life used to make the asset "fully
        depreciated" on day one — a book value of 0.00 and 100% depreciation
        inferred from a missing number.
        """
        result = compute_book_value(
            Decimal('5400'),
            date(2026, 1, 1),
            useful_life_years=0,
            as_of=date(2026, 10, 1),
        )
        assert result['is_depreciable'] is False
        assert result['book_value'] == Decimal('5400')
        assert result['depreciation_pct'] == ZERO

    def test_negative_useful_life_returns_not_depreciable(self) -> None:
        result = compute_book_value(
            Decimal('5400'),
            date(2026, 1, 1),
            useful_life_years=-3,
            as_of=date(2026, 10, 1),
        )
        assert result['is_depreciable'] is False
        assert result['book_value'] == Decimal('5400')

    def test_invalid_string_purchase_date_returns_not_depreciable(self) -> None:
        result = compute_book_value(
            Decimal('1000'), 'not-a-date', as_of=date(2026, 1, 1)
        )
        assert result['is_depreciable'] is False

    def test_fully_depreciated(self) -> None:
        purchase_date = date(2015, 1, 1)
        as_of = date(2030, 1, 1)
        result = compute_book_value(
            Decimal('1000'), purchase_date, useful_life_years=5, as_of=as_of
        )
        assert result['is_depreciable'] is True
        assert result['book_value'] == ZERO
        assert result['depreciation_pct'] == Decimal('100')
        assert result['purchase_price'] == Decimal('1000')

    def test_fresh_purchase_no_depreciation(self) -> None:
        purchase_date = date(2026, 5, 1)
        as_of = date(2026, 5, 18)
        result = compute_book_value(
            Decimal('1200'), purchase_date, useful_life_years=5, as_of=as_of
        )
        assert result['is_depreciable'] is True
        assert result['book_value'] == Decimal('1200')
        assert result['depreciation_pct'] == ZERO

    def test_partial_depreciation_half_life(self) -> None:
        purchase_date = date(2021, 1, 1)
        as_of = date(2023, 7, 1)
        result = compute_book_value(
            Decimal('10000'), purchase_date, useful_life_years=5, as_of=as_of
        )
        assert result['is_depreciable'] is True
        assert result['book_value'] == Decimal('5000.00')
        assert result['depreciation_pct'] == Decimal('50.0')

    def test_partial_depreciation_one_month(self) -> None:
        purchase_date = date(2026, 4, 1)
        as_of = date(2026, 5, 1)
        result = compute_book_value(
            Decimal('6000'), purchase_date, useful_life_years=5, as_of=as_of
        )
        assert result['is_depreciable'] is True
        expected_pct = Decimal('1') / Decimal('60') * Decimal('100')
        assert result['depreciation_pct'] == expected_pct.quantize(Decimal('0.1'))
        assert result['book_value'] >= Decimal('5900')

    def test_custom_useful_life_years(self) -> None:
        purchase_date = date(2024, 1, 1)
        as_of = date(2025, 1, 1)
        result = compute_book_value(
            Decimal('2000'), purchase_date, useful_life_years=2, as_of=as_of
        )
        assert result['useful_life_years'] == 2
        assert result['depreciation_pct'] == Decimal('50.0')
        assert result['book_value'] == Decimal('1000.00')

    def test_default_useful_life_is_5_years(self) -> None:
        result = compute_book_value(
            Decimal('100'), date(2026, 1, 1), as_of=date(2026, 6, 1)
        )
        assert result['useful_life_years'] == DEFAULT_USEFUL_LIFE_YEARS
        assert result['useful_life_years'] == 5

    def test_string_iso_purchase_date_works(self) -> None:
        purchase_date = '2023-06-15'
        as_of = date(2024, 6, 15)
        result = compute_book_value(
            Decimal('1200'), purchase_date, useful_life_years=5, as_of=as_of
        )
        assert result['is_depreciable'] is True
        assert result['depreciation_pct'] == Decimal('20.0')

    def test_purchase_date_in_future_no_depreciation(self) -> None:
        purchase_date = date(2027, 1, 1)
        as_of = date(2026, 5, 18)
        result = compute_book_value(
            Decimal('500'), purchase_date, useful_life_years=5, as_of=as_of
        )
        assert result['depreciation_pct'] == ZERO
        assert result['book_value'] == Decimal('500')

    def test_exactly_at_end_of_life(self) -> None:
        purchase_date = date(2021, 1, 1)
        as_of = date(2026, 1, 1)
        result = compute_book_value(
            Decimal('1000'), purchase_date, useful_life_years=5, as_of=as_of
        )
        assert result['book_value'] == ZERO
        assert result['depreciation_pct'] == Decimal('100')

    def test_one_month_past_end_of_life(self) -> None:
        purchase_date = date(2020, 12, 1)
        as_of = date(2025, 12, 1)
        result = compute_book_value(
            Decimal('1000'), purchase_date, useful_life_years=5, as_of=as_of
        )
        assert result['book_value'] == ZERO
        assert result['depreciation_pct'] == Decimal('100')

    def test_decimal_precision_book_value(self) -> None:
        purchase_date = date(2022, 6, 1)
        as_of = date(2024, 6, 1)
        result = compute_book_value(
            Decimal('999.99'), purchase_date, useful_life_years=5, as_of=as_of
        )
        assert result['book_value'] == Decimal('599.99')
        assert result['book_value'] % Decimal('0.01') == ZERO

    def test_returns_all_expected_keys(self) -> None:
        result = compute_book_value(
            Decimal('100'), date(2026, 1, 1), as_of=date(2026, 6, 1)
        )
        assert 'purchase_price' in result
        assert 'book_value' in result
        assert 'depreciation_pct' in result
        assert 'useful_life_years' in result
        assert 'is_depreciable' in result
