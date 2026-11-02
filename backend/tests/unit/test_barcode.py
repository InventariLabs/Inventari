"""Tests for barcode normalization utility."""

import pytest

from app.core.barcode import (
    gtin_check_digit,
    is_restricted_circulation,
    normalize_barcode,
    validate_checksum,
)


class TestNormalizeBarcode:
    """Tests for normalize_barcode()."""

    def test_none_returns_none(self):
        assert normalize_barcode(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_barcode('') is None

    def test_whitespace_only_returns_none(self):
        assert normalize_barcode('   ') is None

    def test_ean13_passthrough(self):
        assert normalize_barcode('3228021170015') == '3228021170015'

    def test_ean8_padded_to_ean13(self):
        # B-6: EAN-8 (8 digits) is padded to EAN-13 so it collides with its
        # EAN-13 form (previously it passed through unchanged, letting the same
        # product be stored twice under two different canonical codes).
        assert normalize_barcode('96385074') == '0000096385074'

    def test_upc_a_to_ean13(self):
        # UPC-A 12 digits → EAN-13 with leading zero
        assert normalize_barcode('012345678901') == '0012345678901'

    def test_upc_a_real_product(self):
        # Real UPC-A: Coca-Cola 12oz can
        assert normalize_barcode('049000042511') == '0049000042511'

    def test_gtin14_passthrough(self):
        assert normalize_barcode('00012345678905') == '00012345678905'

    def test_strips_whitespace(self):
        assert normalize_barcode('  3228021170015  ') == '3228021170015'

    def test_strips_whitespace_upc(self):
        assert normalize_barcode(' 049000042511 ') == '0049000042511'

    def test_non_numeric_passthrough(self):
        # Internal codes like STM-XXXX should not be modified
        assert normalize_barcode('STM-1234') == 'STM-1234'

    def test_short_numeric_passthrough(self):
        # Numeric but too short (< 8 digits) — not a standard barcode
        assert normalize_barcode('12345') == '12345'

    def test_long_numeric_passthrough(self):
        # Numeric but too long (> 14 digits) — not a standard barcode
        assert normalize_barcode('123456789012345') == '123456789012345'


class TestValidateChecksum:
    """Tests for validate_checksum() — GTIN mod-10."""

    def test_valid_ean13_passes(self):
        # 4006381333931 is a valid EAN-13.
        assert validate_checksum('4006381333931') is True

    def test_invalid_ean13_fails(self):
        # Wrong check digit (last) — 2 instead of 1.
        assert validate_checksum('4006381333932') is False

    def test_valid_upc_a_passes(self):
        # 036000291452 is a valid UPC-A (matches its EAN-13 form 0036000291452).
        assert validate_checksum('036000291452') is True

    def test_valid_ean8_passes(self):
        # 73513537 is a valid EAN-8.
        assert validate_checksum('73513537') is True

    def test_invalid_ean8_fails(self):
        # Tampered check digit.
        assert validate_checksum('73513530') is False

    def test_internal_code_passes(self):
        # Non-numeric codes are not GTINs — left alone.
        assert validate_checksum('STM-1234') is True

    def test_none_passes(self):
        assert validate_checksum(None) is True

    def test_short_numeric_passes(self):
        # 5 digits — not a GTIN length.
        assert validate_checksum('12345') is True


class TestRestrictedCirculation:
    """GS1 restricted-circulation numbers: prefixes 02, 04, 20–29 and GTIN-8 0/2."""

    @pytest.mark.parametrize(
        'prefix', ['02', '04'] + [str(number) for number in range(20, 30)]
    )
    def test_the_restricted_prefixes_are_recognised(self, prefix: str) -> None:
        assert is_restricted_circulation(f'{prefix}00000000213') is True

    @pytest.mark.parametrize('code', ['20000004', '01234567'])
    def test_a_gtin8_beginning_with_0_or_2_is_restricted(self, code: str) -> None:
        # GS1 marks a GTIN-8 as company-internal by its first digit; the
        # two-digit prefixes are a GTIN-13 rule.
        assert is_restricted_circulation(code) is True

    @pytest.mark.parametrize('code', ['20000004', '01234567'])
    def test_a_gtin8_stays_restricted_in_the_padded_scan_form(self, code: str) -> None:
        # A scan reaches the catalogue in the canonical GTIN-13 form, where
        # the EAN-8's leading mark sits behind five zeroes.
        padded = normalize_barcode(code)
        assert padded is not None and padded != code
        assert is_restricted_circulation(padded) is True

    @pytest.mark.parametrize('code', ['96385074', '0000096385074'])
    def test_an_ordinary_gtin8_is_not_restricted(self, code: str) -> None:
        assert is_restricted_circulation(code) is False

    @pytest.mark.parametrize(
        'padded',
        [
            # A 13-digit restricted number in GTIN-14 trade-item form.
            '00200000000219',
            '00400000000213',
            '02900000000216',
            # The EAN-8 forms above, padded all the way to GTIN-14.
            '00000020000004',
            '00000001234567',
        ],
    )
    def test_a_restricted_number_stays_restricted_when_padded_to_gtin14(
        self, padded: str
    ) -> None:
        # A GTIN-14 carries an indicator digit in front of the GTIN-13 body
        # (zero when a shorter code is padded for trade-item data), so the
        # restricted mark sits one place to the right rather than gone.
        assert is_restricted_circulation(padded) is True

    @pytest.mark.parametrize(
        'code',
        [
            '5901234123457',
            '0049000042511',
            '0012345678905',
            # The same ordinary GTIN-13 in 14-digit zero-padded form.
            '00012345678905',
            '00000096385074',
            '12345678',
            'STM-1234',
            '',
            None,
        ],
    )
    def test_everything_else_is_not_restricted(self, code: str | None) -> None:
        assert is_restricted_circulation(code) is False


class TestBarcodeInSchemas:
    """Test that Pydantic schemas normalize barcodes on input."""

    def test_item_create_normalizes_upc(self):
        from uuid import uuid4

        from app.schemas.item import ItemCreate

        item = ItemCreate(
            name='Test Item',
            barcode='049000042511',
            location_id=uuid4(),
        )
        assert item.barcode == '0049000042511'

    def test_item_create_ean13_unchanged(self):
        from uuid import uuid4

        from app.schemas.item import ItemCreate

        item = ItemCreate(
            name='Test Item',
            barcode='3228021170015',
            location_id=uuid4(),
        )
        assert item.barcode == '3228021170015'

    def test_item_create_none_barcode(self):
        from uuid import uuid4

        from app.schemas.item import ItemCreate

        item = ItemCreate(
            name='Test Item',
            barcode=None,
            location_id=uuid4(),
        )
        assert item.barcode is None

    def test_item_update_normalizes_upc(self):
        from app.schemas.item import ItemUpdate

        item = ItemUpdate(barcode='049000042511')
        assert item.barcode == '0049000042511'

    def test_product_template_normalizes_upc(self):
        from app.schemas.product_template import ProductTemplateCreate

        tmpl = ProductTemplateCreate(
            name='Test Product',
            barcode='049000042511',
        )
        assert tmpl.barcode == '0049000042511'


class TestGtinCheckDigit:
    """Tests for gtin_check_digit()."""

    def test_completes_an_ean13(self):
        assert gtin_check_digit('400638133393') == '1'

    def test_completes_an_ean8(self):
        assert gtin_check_digit('9638507') == '4'

    def test_a_completed_code_passes_validation(self):
        body = '200000000042'
        assert validate_checksum(body + gtin_check_digit(body))
