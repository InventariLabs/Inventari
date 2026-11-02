"""Import uploads are bounded before, not after, they are in memory.

Two separate holes: the size check ran on an already-buffered body, and a
ZIP-based import was accepted on its ``PK`` signature alone, so a few
hundred kilobytes could unpack into gigabytes inside pandas.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.core import upload_validation
from app.core.upload_validation import (
    _decompressed_size_exceeds,
    _read_capped,
    read_import_file,
)


class _CountingUpload:
    """UploadFile stand-in that records how much it actually handed over."""

    def __init__(self, data: bytes, filename: str = 'import.csv') -> None:
        self._buffer = io.BytesIO(data)
        self.filename = filename
        self.bytes_served = 0

    async def read(self, size: int = -1) -> bytes:
        chunk = self._buffer.read(size)
        self.bytes_served += len(chunk)
        return chunk


def _zip_containing(payload: bytes, name: str = 'xl/worksheets/sheet1.xml') -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, payload)
    return buffer.getvalue()


class TestCappedRead:
    @pytest.mark.asyncio
    async def test_stops_reading_once_over_the_limit(self):
        upload = _CountingUpload(b'x' * (3 * 1024 * 1024))

        with pytest.raises(ValueError, match='exceeds the maximum'):
            await _read_capped(upload, 1024 * 1024, 'en')

        # The copy stops at the cap: the spool is never pulled past it.
        # (The network receive is a different boundary entirely — the body
        # was already spooled by the framework before this ran; that side
        # belongs to BodySizeLimitMiddleware.)
        assert upload.bytes_served <= 1024 * 1024 + 64 * 1024

    @pytest.mark.asyncio
    async def test_file_at_the_limit_is_accepted(self):
        upload = _CountingUpload(b'x' * 1024)

        content = await _read_capped(upload, 1024, 'en')

        assert content == b'x' * 1024

    @pytest.mark.asyncio
    async def test_oversized_import_is_rejected(self, monkeypatch):
        monkeypatch.setattr(upload_validation, 'MAX_IMPORT_SIZE', 1024)
        upload = _CountingUpload(b'a,b,c\n' * 1000, filename='data.csv')

        with pytest.raises(ValueError, match='exceeds the maximum'):
            await read_import_file(upload, 'en')


class TestZipBombGuard:
    def test_detects_an_archive_that_expands_past_the_limit(self):
        bomb = _zip_containing(b'\0' * (2 * 1024 * 1024))

        # A ~2 KB file that unpacks to 2 MB — the shape of the attack, scaled
        # down so the test stays fast.
        assert len(bomb) < 64 * 1024
        assert _decompressed_size_exceeds(bomb, 1024 * 1024) is True

    def test_ordinary_archive_passes(self):
        ordinary = _zip_containing(b'<worksheet/>')

        assert _decompressed_size_exceeds(ordinary, 1024 * 1024) is False

    def test_non_archive_content_is_not_an_error(self):
        """The signature check already ran; a broken file is the parser's
        problem to report, not this guard's."""
        assert _decompressed_size_exceeds(b'PK\x03\x04 truncated', 1024) is False

    @pytest.mark.asyncio
    async def test_xlsx_bomb_is_rejected_before_parsing(self, monkeypatch):
        monkeypatch.setattr(
            upload_validation, 'MAX_DECOMPRESSED_IMPORT_SIZE', 1024 * 1024
        )
        bomb = _zip_containing(b'\0' * (2 * 1024 * 1024))
        upload = _CountingUpload(bomb, filename='books.xlsx')

        with pytest.raises(ValueError, match='exceeds the maximum'):
            await read_import_file(upload, 'en')

    @pytest.mark.asyncio
    async def test_ordinary_xlsx_still_goes_through(self):
        ordinary = _zip_containing(b'<worksheet/>')
        upload = _CountingUpload(ordinary, filename='books.xlsx')

        content = await read_import_file(upload, 'en')

        assert content == ordinary

    @pytest.mark.asyncio
    async def test_csv_skips_the_archive_check(self):
        """A CSV that happens to start with PK would otherwise be scanned."""
        upload = _CountingUpload(b'a,b\n1,2\n', filename='data.csv')

        assert await read_import_file(upload, 'en') == b'a,b\n1,2\n'
