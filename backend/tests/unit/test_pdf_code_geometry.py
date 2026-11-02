"""Printed code geometry — the numbers that decide whether a scan works.

The module width and the bar height are call parameters in millimetres.
They used to be a side effect of the ``height`` a template gave the ``<img>``:
the image was generated at 0.25 mm/module and scaled to 80 px, so one knob
moved both the bar height and the module width at once, and lowering the bar
to a sane 10-12 mm silently narrowed the modules back below the readable
threshold (the documented measurement).

The decode measurement itself lives in
``backend/tests/integration/test_printed_code_decodes.py`` — this file guards
the contract that makes such a measurement meaningful.
"""

from __future__ import annotations

import base64

import pytest

from app.services.pdf_utils import (
    CODE128_BAR_HEIGHT_MM,
    CODE128_MAX_WIDTH_MM,
    CODE128_MIN_MODULE_WIDTH_MM,
    CODE128_MODULE_WIDTH_MM,
    generate_code128,
    generate_qr,
)


def _svg_of(data_uri: str) -> str:
    assert data_uri.startswith('data:image/svg+xml;base64,')
    return base64.b64decode(data_uri.split(',', 1)[1]).decode('utf-8')


@pytest.mark.unit
class TestCode128Geometry:
    def test_defaults_meet_the_print_thresholds(self) -> None:
        """ISO/IEC 15417 wants >= 6.35 mm of bar; the module width is the one
        that decides readability, and 0.25 mm was never enough on paper."""
        assert CODE128_MODULE_WIDTH_MM >= 0.38
        assert 10.0 <= CODE128_BAR_HEIGHT_MM <= 12.0
        assert CODE128_MIN_MODULE_WIDTH_MM >= 0.25

    def test_geometry_is_a_call_parameter_not_a_scaling_side_effect(self) -> None:
        code = generate_code128(
            'IN/2026/0001',
            module_width_mm=0.5,
            bar_height_mm=10.0,
            max_width_mm=200.0,
        )
        svg = _svg_of(code.data_uri)
        # The bars carry the height they were asked for, in millimetres, and
        # the narrowest bar is exactly one module wide.
        assert 'height="10.000mm"' in svg
        assert 'width="0.500mm"' in svg
        assert code.module_width_mm == 0.5

    def test_the_two_knobs_move_independently(self) -> None:
        """The whole point: a lower bar does not narrow the modules."""
        tall = generate_code128('IN/2026/0001', bar_height_mm=20.0)
        short = generate_code128('IN/2026/0001', bar_height_mm=10.0)
        assert tall.width_mm == short.width_mm
        assert tall.module_width_mm == short.module_width_mm
        assert tall.height_mm > short.height_mm

    def test_reported_size_matches_the_svg_canvas(self) -> None:
        code = generate_code128('IN/2026/0001')
        svg = _svg_of(code.data_uri)
        assert f'width="{code.width_mm:.3f}mm"' in svg
        assert f'height="{code.height_mm:.3f}mm"' in svg

    def test_bar_height_is_independent_of_the_number_length(self) -> None:
        short = generate_code128('IN/2026/1')
        long = generate_code128('ADJUSTMENT/2026/000000025')
        assert short.height_mm == long.height_mm

    def test_a_long_number_shrinks_the_module_instead_of_overflowing(self) -> None:
        """A 24-character number must stay inside the header column."""
        code = generate_code128('CORRECTION/2026/00012345')
        assert code.width_mm <= CODE128_MAX_WIDTH_MM
        assert code.module_width_mm < CODE128_MODULE_WIDTH_MM
        assert code.module_width_mm >= CODE128_MIN_MODULE_WIDTH_MM

    def test_a_short_number_keeps_the_nominal_module_width(self) -> None:
        code = generate_code128('IN/2026/0001')
        assert code.module_width_mm == CODE128_MODULE_WIDTH_MM
        assert code.width_mm <= CODE128_MAX_WIDTH_MM

    def test_the_module_never_goes_below_the_floor(self) -> None:
        """An absurd number narrows the module to the floor and stops there —
        an unreadable symbol that fits is worse than one that overflows."""
        code = generate_code128('X' * 60)
        assert code.module_width_mm == CODE128_MIN_MODULE_WIDTH_MM


@pytest.mark.unit
class TestQrGeometry:
    def test_size_is_reported_in_millimetres(self) -> None:
        qr = generate_qr('https://example.test/scan?code=IN/2026/0001')
        assert qr.width_mm == qr.height_mm
        assert 14.0 <= qr.width_mm <= 24.0

    def test_a_longer_payload_grows_rather_than_losing_module_size(self) -> None:
        short = generate_qr('IN/2026/0001')
        long = generate_qr('https://warehouse.example.test/scan?code=' + 'A' * 60)
        assert long.width_mm >= short.width_mm
