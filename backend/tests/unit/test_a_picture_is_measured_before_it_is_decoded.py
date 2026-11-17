"""A picture's canvas is measured before a pixel of it is decoded.

The byte limit on an uploaded picture says nothing about what decoding it
costs: a PNG of a few hundred kilobytes can describe a canvas of 12000 x
12000, which Pillow holds in some 570 MB. Pillow's own guard refuses a canvas
only above twice its limit and merely warns in between, so that file was
accepted on the item cover — and on the recipe cover, which caught no part of
it, a canvas above twice the limit was a server error.
"""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image, ImageFile

from app.core import upload_validation
from app.core.upload_validation import ImageUnreadableError, decode_image


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data)
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', crc)


def _blank_png(width: int, height: int) -> bytes:
    """A real, decodable PNG whatever its canvas, in a few kilobytes.

    One bit per pixel and every row alike, so the compressed stream stays
    tiny however many pixels it describes. Built by hand because asking
    Pillow to write a canvas this size would first allocate it.
    """
    row = b'\x00' * (1 + (width + 7) // 8)  # the filter byte, then the row
    packer = zlib.compressobj(9)
    rows = b''.join(packer.compress(row) for _ in range(height)) + packer.flush()
    header = struct.pack('>IIBBBBB', width, height, 1, 0, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + _chunk(b'IHDR', header)
        + _chunk(b'IDAT', rows)
        + _chunk(b'IEND', b'')
    )


@pytest.mark.filterwarnings('ignore::PIL.Image.DecompressionBombWarning')
@pytest.mark.parametrize(
    ('width', 'height'),
    [
        # Just over the bound, and under Pillow's own limit: Pillow says
        # nothing about it at all.
        (10_000, 6_001),
        # The reported file: inside the band where Pillow only warns.
        (12_000, 12_000),
        # Over twice Pillow's limit: Pillow refuses it itself, with an error
        # class no caller here used to catch.
        (20_000, 10_000),
    ],
)
def test_a_small_file_with_a_huge_canvas_is_refused_unread(
    width: int, height: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _blank_png(width, height)
    assert len(content) < 1024 * 1024

    def decoded(_picture: object) -> None:
        raise AssertionError('the pixels were decoded before the canvas was measured')

    monkeypatch.setattr(ImageFile.ImageFile, 'load', decoded)

    with pytest.raises(ImageUnreadableError):
        decode_image(content)


def test_a_canvas_at_the_bound_is_decoded_and_one_past_it_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upload_validation, 'MAX_UPLOAD_IMAGE_PIXELS', 12)

    assert decode_image(_blank_png(4, 3)).size == (4, 3)
    with pytest.raises(ImageUnreadableError):
        decode_image(_blank_png(13, 1))


def _noise_png() -> bytes:
    buffer = io.BytesIO()
    Image.effect_noise((64, 64), 64).save(buffer, format='PNG')
    return buffer.getvalue()


def _with_its_pixels_split_and_the_second_half_mislabelled(content: bytes) -> bytes:
    """The header reads; the decoder meets a chunk whose kind is not a word."""
    at = content.index(b'IDAT') - 4
    (length,) = struct.unpack('>I', content[at : at + 4])
    pixels = content[at + 8 : at + 8 + length]
    first, second = pixels[: length // 2], pixels[length // 2 :]
    return (
        content[:at]
        + _chunk(b'IDAT', first)
        + struct.pack('>I', len(second))
        + b'\x00\x01\x02\x03'
        + second
        + bytes(4)
        + _chunk(b'IEND', b'')
    )


@pytest.mark.parametrize(
    'content',
    [
        # Refused when opened: nothing after the signature reads as a header.
        pytest.param(b'\x89PNG\r\n\x1a\n and then plain text', id='no-header'),
        # Opened, then cut off half-way through its pixels.
        pytest.param(_noise_png()[:2048], id='cut-short'),
        # Opened, then a broken chunk on the way through the pixels — Pillow
        # says that one with a SyntaxError, which the recipe cover let through
        # as a server error.
        pytest.param(
            _with_its_pixels_split_and_the_second_half_mislabelled(_noise_png()),
            id='broken-chunk',
        ),
    ],
)
def test_a_file_that_is_no_picture_is_refused_the_same_way(
    content: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pillow says so in more than one class; every caller is given one."""
    # Pillow's default. Importing WeasyPrint turns it on for the whole
    # process, and with it on the last two files decode with their missing
    # pixels filled in, so the outcome would depend on what was imported first.
    monkeypatch.setattr(ImageFile, 'LOAD_TRUNCATED_IMAGES', False)

    with pytest.raises(ImageUnreadableError):
        decode_image(content)
