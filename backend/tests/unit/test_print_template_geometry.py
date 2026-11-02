"""No print template is allowed to resize a printed code.

This replaces the earlier guard, which pinned ``height: 80px`` in two of the
three families. That number was the right measurement expressed through the
wrong knob: the image was scaled proportionally, so the CSS height also set
the module width — the one dimension that decides whether a scanner reads the
paper — and the third family sat at 38 px, the size the same measurement had
rejected.

The geometry now comes from ``core_api.pdf.printed_codes`` in millimetres and
is applied in one place, the shared header partial. A family that grows its
own copy, in pixels or otherwise, silently takes the measurement back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_SHARED_HEADER = _BACKEND / 'app/core/print_templates/print_header.html'
_FAMILIES = {
    'standard': _BACKEND / 'app/modules/warehouse/templates/standard.html',
    'pl_pz': _BACKEND / 'app/modules/warehouse/templates/pl_pz.html',
    'po_standard': _BACKEND / 'app/modules/purchase_orders/templates/po_standard.html',
}

#: A code image given a size in anything but millimetres.
_NON_MM_SIZE_RE = re.compile(
    r'class="(?:code128|qr)"[^>]*?(?:width|height):\s*[\d.]+(px|pt|em|rem|%)'
    r'|img\.(?:code128|qr)\s*\{[^}]*?(?:width|height):\s*[\d.]+(px|pt|em|rem|%)',
    re.IGNORECASE | re.DOTALL,
)


@pytest.mark.unit
class TestPrintedCodeGeometryIsNotATemplateDecision:
    def test_the_shared_header_prints_the_generated_size(self) -> None:
        html = _SHARED_HEADER.read_text(encoding='utf-8')
        for placeholder in (
            '{{ code128_width_mm }}mm',
            '{{ code128_height_mm }}mm',
            '{{ qr_size_mm }}mm',
        ):
            assert placeholder in html, (
                f'the shared print header does not print the code at the '
                f'generated size ({placeholder} missing)'
            )

    @pytest.mark.parametrize('family', sorted(_FAMILIES))
    def test_no_family_sizes_a_code_itself(self, family: str) -> None:
        html = _FAMILIES[family].read_text(encoding='utf-8')
        match = _NON_MM_SIZE_RE.search(html)
        assert match is None, (
            f'{family}.html sizes a printed code itself — the module width '
            'and bar height are set in millimetres by '
            'core_api.pdf.printed_codes and applied in print_header.html; '
            'scaling the image moves both at once'
        )

    @pytest.mark.parametrize('family', sorted(_FAMILIES))
    def test_every_family_draws_the_shared_header(self, family: str) -> None:
        """One header, not three that drift apart."""
        html = _FAMILIES[family].read_text(encoding='utf-8')
        assert "{% include 'print_header.html' %}" in html
