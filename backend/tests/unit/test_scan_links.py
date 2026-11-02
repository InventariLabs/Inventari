"""The address a printed QR points at."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from app.core.scan_links import printable_scan_url, scan_code_in, scan_url
from app.core.scan_registry import extract_scan_code
from app.schemas.validators import ScannedCode


@pytest.mark.unit
class TestScanUrl:
    def test_the_printed_address_is_the_short_one(self) -> None:
        """Every byte of the payload is a module on the label: the part of
        the address the installation does not choose is one letter."""
        assert (
            scan_url('STM-K9XP', 'https://wh.example.test')
            == 'https://wh.example.test/s/STM-K9XP'
        )

    def test_a_document_number_keeps_its_slashes(self) -> None:
        assert (
            scan_url('IN/2026/0001', 'https://wh.example.test')
            == 'https://wh.example.test/s/IN/2026/0001'
        )

    def test_a_character_that_means_something_in_a_url_is_quoted(self) -> None:
        """Unquoted, ``#`` would end the path and the code with it."""
        url = scan_url('A B#1?', 'https://wh.example.test')
        assert url == 'https://wh.example.test/s/A%20B%231%3F'
        assert scan_code_in(url) == 'A B#1?'

    def test_trailing_slash_does_not_double(self) -> None:
        assert (
            scan_url('L-ABC', 'https://wh.example.test/')
            == 'https://wh.example.test/s/L-ABC'
        )


@pytest.mark.unit
class TestScanCodeIn:
    def test_reads_the_short_address_back(self) -> None:
        assert scan_code_in('https://wh.example.test/s/STM-K9XP') == 'STM-K9XP'

    def test_reads_a_document_number_back_whole(self) -> None:
        assert (
            scan_code_in(scan_url('IN/2026/0001', 'https://wh.example.test'))
            == 'IN/2026/0001'
        )

    def test_a_label_printed_before_the_short_address_still_reads(self) -> None:
        """Labels already on shelves carry ``/scan?code=``; nobody reprints
        them, so the old shape stays a scan address for good."""
        assert scan_code_in('https://wh.example.test/scan?code=STM-K9XP') == 'STM-K9XP'

    def test_a_sticker_that_opened_the_app_scan_page_still_reads(self) -> None:
        """The first QR stickers carried the app's own ``/labels/scan/`` page;
        a 2D hardware scanner types that whole address into a scan field."""
        assert (
            scan_code_in('https://wh.example.test/labels/scan/LOC-7KQ2') == 'LOC-7KQ2'
        )

    @pytest.mark.parametrize(
        'raw',
        [
            'STM-K9XP',
            '5901234123457',
            'https://elsewhere.example/docs/labels/scan/LOC-7KQ2',
            'https://elsewhere.example/docs/s/STM-K9XP',
            'https://wh.example.test/s/',
            'ftp://wh.example.test/s/STM-K9XP',
        ],
    )
    def test_anything_else_is_not_a_scan_address(self, raw: str) -> None:
        assert scan_code_in(raw) is None


@pytest.mark.unit
class TestExtractScanCode:
    """The registry resolves what a QR carries, whichever shape it was."""

    @pytest.mark.parametrize(
        'raw',
        [
            'https://wh.example.test/s/STM-K9XP',
            'https://wh.example.test/scan?code=STM-K9XP',
            'https://wh.example.test/labels/scan/STM-K9XP',
            'STM-K9XP',
        ],
    )
    def test_every_printed_shape_resolves_to_the_code(self, raw: str) -> None:
        assert extract_scan_code(raw) == 'STM-K9XP'

    def test_a_malformed_address_falls_through_as_typed(self) -> None:
        assert extract_scan_code('http://[wh/s/STM-K9XP') == 'http://[wh/s/STM-K9XP'


@pytest.mark.unit
class TestScannedCode:
    """A warehouse scan field matches the code, not the address around it."""

    @pytest.mark.parametrize(
        'raw',
        [
            'https://wh.example.test/labels/scan/A-02-01',
            'https://wh.example.test/s/A-02-01',
            'https://wh.example.test/scan?code=A-02-01',
            'A-02-01',
        ],
    )
    def test_every_printed_shape_names_the_shelf(self, raw: str) -> None:
        assert TypeAdapter(ScannedCode).validate_python(raw) == 'A-02-01'

    def test_a_product_barcode_is_left_as_read(self) -> None:
        """Unlike the scan registry, a scan field does not rewrite a
        barcode: the line matching compares barcodes itself."""
        assert TypeAdapter(ScannedCode).validate_python('012345678905') == (
            '012345678905'
        )


@pytest.mark.unit
class TestPrintableScanUrl:
    @pytest.mark.parametrize(
        'base',
        [
            'http://localhost:5173',
            'http://127.0.0.1:5173',
            'http://[::1]:5173',
            'http://0.0.0.0:5173',
            '',
        ],
    )
    def test_an_address_nobody_else_can_open_is_not_printed(
        self, monkeypatch: pytest.MonkeyPatch, base: str
    ) -> None:
        """A printout leaves the building. ``localhost`` on somebody else's
        phone resolves to their own device, so the QR falls back to the bare
        number instead of carrying a link that cannot work."""
        from app.config import settings

        monkeypatch.setattr(settings, 'FRONTEND_URL', base, raising=False)
        assert printable_scan_url('IN/2026/0001') is None

    def test_a_real_installation_address_is_printed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import settings

        monkeypatch.setattr(
            settings, 'FRONTEND_URL', 'https://wh.example.test', raising=False
        )
        assert (
            printable_scan_url('IN/2026/0001')
            == 'https://wh.example.test/s/IN/2026/0001'
        )
