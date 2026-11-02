"""Unit tests for the shared Pydantic validators."""

from decimal import Decimal

import pytest

from app.schemas.validators import quantize_quantity


class TestQuantizeQuantity:
    """quantize_quantity: the entry gate for the columns' 3-dp scale."""

    def test_fraction_beyond_column_scale_is_rounded_half_up(self) -> None:
        """1.0005 used to reach Postgres and round silently; now the schema
        says which number is stored."""
        assert quantize_quantity(Decimal('1.0005')) == Decimal('1.001')

    def test_string_input_is_quantized(self) -> None:
        assert quantize_quantity('2.00049') == Decimal('2.000')

    def test_none_passes_through(self) -> None:
        assert quantize_quantity(None) is None

    def test_exact_value_is_untouched(self) -> None:
        assert quantize_quantity(Decimal('3.142')) == Decimal('3.142')

    def test_non_numeric_input_raises(self) -> None:
        with pytest.raises((ValueError, ArithmeticError, TypeError)):
            quantize_quantity('not-a-number')
