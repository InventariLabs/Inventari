"""Unit tests for the core_api.pdf facade."""

import pytest

from app.core.public_api import core_api


@pytest.mark.unit
class TestCorePdfAPI:
    def test_sanitize_html_strips_script(self):
        assert '<script>' not in core_api.pdf.sanitize_html(
            '<p>ok</p><script>alert(1)</script>'
        )

    def test_render_html_simple(self):
        assert (
            core_api.pdf.render_html('<h1>{{ title }}</h1>', {'title': 'Hello'})
            == '<h1>Hello</h1>'
        )

    def test_render_html_none_returns_empty(self):
        assert core_api.pdf.render_html(None, {}) == ''

    def test_render_pdf_produces_pdf_bytes(self):
        pdf = core_api.pdf.render_pdf('<h1>Test</h1>')
        assert isinstance(pdf, bytes)
        assert pdf.startswith(b'%PDF')

    def test_code128_data_uri(self):
        # Vector, not raster: the bars land on device pixels at
        # whatever resolution the printer works in.
        assert core_api.pdf.generate_code128_base64('PO-1').startswith(
            'data:image/svg+xml;base64,'
        )

    def test_qr_data_uri(self):
        assert core_api.pdf.generate_qr_base64('PO-1').startswith(
            'data:image/png;base64,'
        )

    def test_printed_codes_carry_their_own_size(self):
        """A template renders these numbers, it does not invent them."""
        codes = core_api.pdf.printed_codes('IN/2026/0001')
        assert codes['code128_img'].startswith('data:image/svg+xml;base64,')
        assert codes['qr_img'].startswith('data:image/png;base64,')
        assert codes['code128_width_mm'] > 0
        assert 10.0 <= codes['code128_height_mm'] <= 14.0
        assert codes['qr_size_mm'] > 0

    def test_printed_codes_do_not_repeat_each_other(self, monkeypatch):
        """The Code128 carries the number for a 1D gun, the QR carries
        the address so a phone opens the record instead of showing a string."""
        import base64

        from app.config import settings

        monkeypatch.setattr(
            settings, 'FRONTEND_URL', 'https://wh.example.test', raising=False
        )
        codes = core_api.pdf.printed_codes('IN/2026/0001')
        svg = base64.b64decode(codes['code128_img'].split(',', 1)[1])
        assert b'IN/2026/0001' not in svg  # bars, not text — the number is the payload
        qr_payload = _decode_qr_payload(codes['qr_img'])
        assert qr_payload == 'https://wh.example.test/s/IN/2026/0001'

    def test_printed_qr_falls_back_to_the_number_without_a_reachable_address(
        self, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(
            settings, 'FRONTEND_URL', 'http://localhost:5173', raising=False
        )
        codes = core_api.pdf.printed_codes('IN/2026/0001')
        assert _decode_qr_payload(codes['qr_img']) == 'IN/2026/0001'

    def test_format_partner_address(self):
        address = {'street': 'Main 1', 'city': 'Springfield', 'postal_code': None}
        assert core_api.pdf.format_partner_address(address) == 'Main 1, Springfield'
        assert core_api.pdf.format_partner_address(None) is None
        assert core_api.pdf.format_partner_address({}) is None

    def test_format_partner_address_localizes_country(self):
        """the address prints the country name, not the raw code."""
        address = {
            'street': 'Main 1',
            'city': 'Warsaw',
            'postal_code': '00-001',
            'country': 'PL',
        }
        assert (
            core_api.pdf.format_partner_address(address, lang='en')
            == 'Main 1, Warsaw, 00-001, Poland'
        )
        assert (
            core_api.pdf.format_partner_address(address, lang='pl')
            == 'Main 1, Warsaw, 00-001, Polska'
        )
        # follow-up: names come from Babel's CLDR tables, so a real
        # code outside the old curated 40 (e.g. AE) prints a name in every
        # language instead of a bare code.
        ae = {**address, 'country': 'AE'}
        assert core_api.pdf.format_partner_address(ae, lang='pl').endswith(
            'Zjednoczone Emiraty Arabskie'
        )
        # A syntactically-valid unassigned code gets the locale's "unknown
        # region" label; legacy free text (not a code) prints as-is.
        unknown = {**address, 'country': 'ZZ'}
        assert core_api.pdf.format_partner_address(unknown, lang='pl').endswith(
            'Nieznany region'
        )
        legacy = {**address, 'country': 'Polska'}
        assert core_api.pdf.format_partner_address(legacy, lang='pl').endswith('Polska')

    def test_get_doc_status_map(self):
        # 5-language coverage moved here from the warehouse module's own
        # duplicate map (removed in the dedup pass).
        assert core_api.pdf.get_doc_status_map('en')['DRAFT'] == 'Draft'
        assert core_api.pdf.get_doc_status_map('pl')['DRAFT'] == 'Projekt'
        assert core_api.pdf.get_doc_status_map('de')['DRAFT'] == 'Entwurf'
        assert core_api.pdf.get_doc_status_map('fr')['DRAFT'] == 'Brouillon'
        assert core_api.pdf.get_doc_status_map('es')['DRAFT'] == 'Borrador'

    def test_common_labels_language_switch(self):
        assert core_api.pdf.common_labels('en')['name'] == 'Name'
        assert core_api.pdf.common_labels('pl')['name'] == 'Nazwa'
        # returns a copy — mutation must not leak into the shared constant
        labels = core_api.pdf.common_labels('en')
        labels['name'] = 'MUTATED'
        assert core_api.pdf.common_labels('en')['name'] == 'Name'


def _decode_qr_payload(data_uri: str) -> str:
    """Read the QR back out of the generated PNG, without a decoder library.

    The QR is generated from a known payload, so the check that matters is
    "which payload went in" — re-encoding the candidate and comparing the
    images answers that without adding a decode dependency to the test suite.
    """
    import base64

    from app.services.pdf_utils import generate_qr

    png = base64.b64decode(data_uri.split(',', 1)[1])
    candidates = [
        'https://wh.example.test/s/IN/2026/0001',
        'IN/2026/0001',
    ]
    for candidate in candidates:
        if base64.b64decode(generate_qr(candidate).data_uri.split(',', 1)[1]) == png:
            return candidate
    raise AssertionError(f'QR payload is none of {candidates}')
