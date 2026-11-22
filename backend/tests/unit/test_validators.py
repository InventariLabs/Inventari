"""Unit tests for the shared Pydantic validators."""

from decimal import Decimal

import pytest

from app.schemas.validators import normalize_barcode, normalize_sku, quantize_quantity


class TestQuantizeQuantity:
    """quantize_quantity: the entry gate for the columns' 3-dp scale."""

    def test_fraction_beyond_column_scale_is_rounded_half_up(self) -> None:
        """1.0005 is rounded half up before it reaches Postgres, so the schema says which
        number is stored."""
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

    def test_a_value_too_wide_to_quantize_is_left_for_the_ceiling(self) -> None:
        """A forty-digit quantity is past every column; it comes through as sent so the
        writer's ceiling refuses it, instead of ``InvalidOperation`` escaping as a 500."""
        wide = Decimal('1' * 40)
        assert quantize_quantity(wide) == wide


class TestNormalizersLeaveAWrongTypeToPydantic:
    """A before-validator that meets a non-string hands it back, so the field's own
    type check refuses it; ``.strip()`` on an int is a 500."""

    @pytest.mark.parametrize('wrong', [12345, 1.5, True, ['a'], {'a': 1}])
    def test_barcode(self, wrong: object) -> None:
        assert normalize_barcode(wrong) is wrong

    @pytest.mark.parametrize('wrong', [12345, 1.5, True, ['a'], {'a': 1}])
    def test_sku(self, wrong: object) -> None:
        assert normalize_sku(wrong) is wrong

    def test_strings_are_still_normalized(self) -> None:
        assert normalize_barcode(' 123456789012 ') == '0123456789012'
        assert normalize_sku(' ab-1 ') == 'AB-1'
        assert normalize_sku('  ') is None
