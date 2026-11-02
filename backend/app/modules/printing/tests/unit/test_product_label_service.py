"""A product label carries the product's own code, in bars a scanner reads.

The checks read the bars back off the PNG, so they hold the drawing to the
code rather than to the function that chose it.
"""

import io
from datetime import date

import pytest
from PIL import Image

from app.core.exceptions import ValidationException
from app.modules.printing.services.print_queue_service import _details_line
from app.modules.printing.services.product_label_service import (
    ProductLabel,
    barcode_modules,
    generate_product_label_batch_png,
    generate_product_label_png,
    require_fits,
    symbology,
)
from app.modules.printing.tests.bars import read_bars


class TestSymbology:
    def test_a_valid_ean13_is_drawn_as_ean13(self) -> None:
        assert symbology('2000000000015') == 'ean13'

    def test_thirteen_digits_with_a_wrong_check_digit_are_code128(self) -> None:
        """Drawn as EAN-13 the library would print a corrected, other code."""
        assert symbology('2000000000010') == 'code128'

    def test_a_sku_is_code128(self) -> None:
        assert symbology('WH-00001') == 'code128'

    def test_a_code_no_barcode_carries_is_refused(self) -> None:
        assert symbology('Żółw-1') is None
        assert barcode_modules('Żółw-1') is None


class TestProductLabelPng:
    def test_the_bars_carry_the_ean13(self) -> None:
        png = generate_product_label_png(
            ProductLabel('Plum butter 300 g', '2000000000015')
        )

        assert read_bars(png) == barcode_modules('2000000000015')

    def test_the_bars_carry_a_sku_as_code128(self) -> None:
        png = generate_product_label_png(ProductLabel('Crate', 'WH-00001'))

        assert read_bars(png) == barcode_modules('WH-00001')

    def test_the_bars_survive_the_lot_line_and_a_long_name(self) -> None:
        png = generate_product_label_png(
            ProductLabel(
                'Plum butter with cinnamon from the autumn harvest, glass jar',
                '2000000000015',
                'Lot L-0042 · Exp. 31.12.2027',
            )
        )

        assert read_bars(png) == barcode_modules('2000000000015')

    def test_a_label_is_drawn_at_its_size(self) -> None:
        png = generate_product_label_png(
            ProductLabel('Crate', '2000000000015'), 50.0, 24.0, dpi=300
        )

        img = Image.open(io.BytesIO(png))
        assert img.size == (591, 283)

    def test_a_batch_lays_the_labels_side_by_side(self) -> None:
        one = Image.open(
            io.BytesIO(generate_product_label_png(ProductLabel('A', 'WH-1')))
        )
        sheet = Image.open(
            io.BytesIO(
                generate_product_label_batch_png(
                    [ProductLabel('A', 'WH-1'), ProductLabel('B', 'WH-2')]
                )
            )
        )

        assert sheet.height == one.height
        assert sheet.width == 2 * one.width + 10


#: Fifty characters of Code 128: 585 modules, 605 with the quiet zones, more
#: than the 555 pixels a 50 mm label has for bars at 300 dpi.
_LONG_CODE = 'ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWX'


class TestABarcodeThatDoesNotFit:
    def test_a_code_wider_than_the_label_is_refused_not_clipped(self) -> None:
        with pytest.raises(ValidationException) as refused:
            generate_product_label_png(ProductLabel('Crate', _LONG_CODE), 50.0, 24.0)

        assert '55 mm' in str(refused.value.detail)

    def test_at_the_width_it_names_the_whole_symbol_prints(self) -> None:
        png = generate_product_label_png(ProductLabel('Crate', _LONG_CODE), 55.0, 24.0)

        assert read_bars(png) == barcode_modules(_LONG_CODE)

    def test_a_coarser_printer_raster_is_refused_too(self) -> None:
        """The agent draws the queued label at its own dots, fewer at 203 dpi."""
        with pytest.raises(ValidationException):
            generate_product_label_png(
                ProductLabel('Crate', _LONG_CODE), 62.0, 24.0, dpi=203
            )


class TestABarcodeThatHasNoRoomToStand:
    """Name and text take their lines first; the bars get what is left."""

    def test_a_label_too_short_for_its_bars_is_refused_not_squashed(self) -> None:
        with pytest.raises(ValidationException) as refused:
            generate_product_label_png(
                ProductLabel('Crate', '2000000000022', 'Lot L-1 · Exp. 2027-12-31'),
                50.0,
                5.0,
            )

        assert '2000000000022' in str(refused.value.detail)

    def test_the_standard_label_keeps_a_long_name_and_details(self) -> None:
        png = generate_product_label_png(
            ProductLabel(
                'Plum butter with cinnamon from the autumn harvest, glass jar',
                '2000000000022',
                'Lot L-0042 · Exp. 31.12.2027',
            ),
            50.0,
            24.0,
        )

        assert read_bars(png) == barcode_modules('2000000000022')

    def test_require_fits_draws_nothing_but_refuses_the_same(self) -> None:
        with pytest.raises(ValidationException):
            require_fits(ProductLabel('Crate', '2000000000022'), 50.0, 5.0)


class TestDetailsLine:
    def test_the_lot_and_expiry_read_in_the_reader_language(self) -> None:
        assert (
            _details_line('L-0042', date(2027, 12, 31), 'pl')
            == 'Partia L-0042 · Termin 31.12.2027'
        )

    def test_a_record_without_either_has_no_line(self) -> None:
        assert _details_line(None, None, 'en') is None
