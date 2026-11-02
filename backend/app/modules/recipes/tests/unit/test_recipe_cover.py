"""What the app will and will not accept as a recipe's cover.

The rule these pin: an imported recipe ends up with a picture the app holds,
or with no picture. The address a source page advertised is never what a
reader's browser is sent to fetch.
"""

import io
from typing import Any

import httpx
import pytest
from PIL import Image

from app.modules.recipes._recipe_cover import (
    MAX_COVER_BYTES,
    _reencode,
    fetch_remote_cover,
)


@pytest.fixture(autouse=True)
def _no_real_dns(stub_dns: object) -> object:
    # The fetch resolves the host to vet it; keep that off the network.
    return stub_dns


def _png(width: int = 40, height: int = 30) -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), (200, 30, 30)).save(buffer, format='PNG')
    return buffer.getvalue()


def _responder(
    body: bytes, content_type: str = 'image/png', headers: dict[str, str] | None = None
) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={'content-type': content_type, **(headers or {})},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_a_picture_on_a_public_host_is_downloaded() -> None:
    body = _png()

    fetched = await fetch_remote_cover(
        'https://example.com/dish.png', _transport=_responder(body)
    )

    assert fetched == (body, 'image/png')


@pytest.mark.asyncio
async def test_an_address_inside_the_network_is_refused() -> None:
    # The URL comes from a page the server was told to read, so it points
    # wherever that page says — including at the server's own neighbours.
    fetched = await fetch_remote_cover(
        'http://192.168.1.10/admin.png', _transport=_responder(_png())
    )

    assert fetched is None


@pytest.mark.asyncio
async def test_a_response_that_is_not_an_image_is_refused() -> None:
    fetched = await fetch_remote_cover(
        'https://example.com/dish.png',
        _transport=_responder(b'<html>login</html>', 'text/html'),
    )

    assert fetched is None


@pytest.mark.asyncio
async def test_an_svg_is_refused_even_though_it_is_an_image() -> None:
    # SVG carries script; it is not on the list for that reason.
    fetched = await fetch_remote_cover(
        'https://example.com/dish.svg',
        _transport=_responder(
            b'<svg xmlns="http://www.w3.org/2000/svg"/>', 'image/svg+xml'
        ),
    )

    assert fetched is None


@pytest.mark.asyncio
async def test_more_bytes_than_the_cap_are_refused_however_they_were_announced() -> (
    None
):
    oversized = b'\x89PNG\r\n\x1a\n' + b'\x00' * (MAX_COVER_BYTES + 1)

    fetched = await fetch_remote_cover(
        'https://example.com/poster.png',
        # A truthful length would be caught by any check; this one lies, so
        # only counting what actually arrives stops it.
        _transport=_responder(oversized, 'image/png', {'content-length': '120'}),
    )

    assert fetched is None


@pytest.mark.asyncio
async def test_bytes_that_are_not_what_the_header_claimed_are_refused() -> None:
    fetched = await fetch_remote_cover(
        'https://example.com/dish.png',
        _transport=_responder(b'GIF89a not really', 'image/jpeg'),
    )

    assert fetched is None


@pytest.mark.asyncio
async def test_a_server_that_says_no_leaves_no_picture() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        # Sites that refuse requests which did not come from their own pages
        # are exactly why a link was never a picture.
        return httpx.Response(403)

    fetched = await fetch_remote_cover(
        'https://example.com/dish.png', _transport=httpx.MockTransport(handler)
    )

    assert fetched is None


@pytest.mark.asyncio
async def test_the_fetch_connects_to_the_address_validation_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rebinding answer changes nothing the connection acts on.

    The guard resolves the hostname and hands back the address it verified.
    Fetching by hostname would resolve a second time — a window in which a
    server that answered publicly at validation time answers privately at
    connection time. The request must go to the verified address.
    """
    import socket as socket_module

    def _resolve(host: str, port: int, *args: object) -> list[tuple[Any, ...]]:
        return [
            (
                socket_module.AF_INET,
                socket_module.SOCK_STREAM,
                6,
                '',
                ('93.184.216.34', port),
            )
        ]

    monkeypatch.setattr('app.core.ssrf_guard.socket.getaddrinfo', _resolve)

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen['url'] = str(request.url)
        seen['host'] = request.headers.get('host', '')
        return httpx.Response(
            200, content=_png(), headers={'content-type': 'image/png'}
        )

    fetched = await fetch_remote_cover(
        'https://example.com/dish.png', _transport=httpx.MockTransport(handler)
    )

    assert fetched == (_png(), 'image/png')
    # The connection went to the verified address, not the hostname a
    # re-resolution could have flipped.
    assert seen['url'].startswith('https://93.184.216.34/')
    # The page's own name still rides along for virtual-host routing.
    assert seen['host'] == 'example.com'


def test_a_wide_image_is_brought_down_to_the_stored_width() -> None:
    data, content_type = _reencode(_png(4000, 2000), 'image/jpeg')

    assert content_type == 'image/jpeg'
    assert Image.open(io.BytesIO(data)).size == (1600, 800)


def test_the_stored_file_carries_none_of_the_original_metadata() -> None:
    original = io.BytesIO()
    image = Image.new('RGB', (60, 40), (10, 120, 10))
    exif = image.getexif()
    exif[0x0110] = 'A Phone'  # Model
    image.save(original, format='JPEG', exif=exif)
    assert Image.open(io.BytesIO(original.getvalue())).getexif()

    data, _ = _reencode(original.getvalue(), 'image/jpeg')

    # Where a photograph was taken travels in the same block as which phone
    # took it, and neither belongs in a recipe.
    assert not Image.open(io.BytesIO(data)).getexif()


def test_an_image_that_is_not_wide_is_left_at_its_own_size() -> None:
    data, _ = _reencode(_png(300, 900), 'image/jpeg')

    assert Image.open(io.BytesIO(data)).size == (300, 900)


@pytest.mark.parametrize(('orientation', 'expected'), [(6, (30, 40)), (8, (30, 40))])
def test_a_phone_photo_stored_sideways_is_turned_upright(
    orientation: int, expected: tuple[int, int]
) -> None:
    # Phones save a portrait shot as landscape pixels plus an Orientation tag.
    # The re-encode drops the tag, so the pixels must be turned first.
    source = Image.new('RGB', (40, 30), (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = orientation
    buffer = io.BytesIO()
    source.save(buffer, format='JPEG', exif=exif)

    data, _ = _reencode(buffer.getvalue(), 'image/jpeg')

    assert Image.open(io.BytesIO(data)).size == expected
