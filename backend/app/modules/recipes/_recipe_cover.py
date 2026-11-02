"""A recipe's cover image, held by the app rather than pointed at.

An import used to keep whatever address the source page advertised for its
picture. That address is not a picture: what the reader sees is whatever the
other server decides to serve today, every open of the recipe sends the
reader's address to a host they never chose, some sites refuse requests that
did not come from their own pages and leave an empty frame, and the app
cannot inspect an image it does not have.

So an imported cover is fetched once, at import, and kept — or the recipe has
no cover. A link to somebody else's server is never one of the outcomes.

The bytes are re-encoded on the way in. That normalises what the scrapers
find (a JPEG that is really a PNG, a progressive file some viewer chokes on)
and drops EXIF, which on a photograph taken with a phone carries the place it
was taken. The image is *not* cropped: the cover appears in the recipe
header, in meal-plan cards and in suggestion tiles, each at its own shape,
and a file cropped to one of them is wrong for the others.
"""

import io
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.file_signature import validate_signature
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.ssrf_guard import validate_webhook_url

log = get_logger(__name__)


class CoverUnreadableError(ValueError):
    """The bytes passed every check up to the point of being decoded.

    A declared type and a matching magic number are the first eight bytes of
    a file agreeing with its envelope; neither says the rest of it is there.
    """


# The stored extension comes from the validated MIME type, never from a
# filename or a URL path — both are attacker data on their way to a storage
# path (same rule as `api/_items_images.py`).
RECIPE_IMAGE_MIME_TO_EXT = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
    'image/gif': 'gif',
}
ALLOWED_RECIPE_IMAGE_MIMES = frozenset(RECIPE_IMAGE_MIME_TO_EXT)

#: Hand-synced with the frontend gate (see the unit test that pins the
#: number) and with the other interface-image limits. The width cap below
#: is what decides a file is a cover; this only bounds the copy in memory.
MAX_COVER_BYTES = 10 * 1024 * 1024
#: Anything larger is a poster, not a cover, and every surface that shows it
#: is narrower than this.
MAX_COVER_WIDTH = 1600
_FETCH_TIMEOUT = 15.0
_FETCH_HEADERS = {'Accept': 'image/*'}


def _reencode(content: bytes, content_type: str) -> tuple[bytes, str]:
    """The same picture, written by us, at most `MAX_COVER_WIDTH` wide.

    Raises :class:`CoverUnreadableError` when the bytes are not an image the
    library can read.
    """
    try:
        opened = Image.open(io.BytesIO(content))
        opened.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise CoverUnreadableError(str(exc)) from exc
    # The tag is dropped below, so turn the pixels it described first.
    image: Image.Image = ImageOps.exif_transpose(opened)
    if image.width > MAX_COVER_WIDTH:
        height = round(image.height * MAX_COVER_WIDTH / image.width)
        image = image.resize(
            (MAX_COVER_WIDTH, max(1, height)), Image.Resampling.LANCZOS
        )

    buffer = io.BytesIO()
    if content_type == 'image/png' or (
        content_type == 'image/webp' and image.mode in ('RGBA', 'LA', 'P')
    ):
        image.convert('RGBA').save(buffer, format='PNG', optimize=True)
        return buffer.getvalue(), 'image/png'
    # A GIF cover is a single frame either way — the header does not animate.
    image.convert('RGB').save(buffer, format='JPEG', quality=88, optimize=True)
    return buffer.getvalue(), 'image/jpeg'


async def store_cover(
    organization_id: UUID, recipe_id: object, content: bytes, content_type: str
) -> str:
    """Put *content* in the app's own storage and return its storage key.

    The org travels with the call: the storage keeps the file under
    ``<org>/recipes/<recipe_id>/cover.<ext>`` and the facade rebuilds that
    prefix on every call, so the recipe keeps only the key. The address a
    reader loads is built from it when the row is read
    (``Recipe.image_url``) — never stored.
    """
    data, stored_type = _reencode(content, content_type)
    path = f'{recipe_id}/cover.{RECIPE_IMAGE_MIME_TO_EXT[stored_type]}'
    return await core_api.file_storage.save_for_org_async(
        organization_id, 'recipes', path, data, stored_type
    )


async def fetch_remote_cover(
    url: str, *, _transport: httpx.AsyncBaseTransport | None = None
) -> tuple[bytes, str] | None:
    """Download the image at *url*, or return None and say why in the log.

    Every refusal is a shrug rather than an error: a recipe whose picture
    could not be fetched is still a recipe worth having.

    ``_transport`` is the tests' way in, as in the LLM clients.
    """
    try:
        # The guard resolves the name and hands back the address it
        # verified; the return value is the pin. Fetching by hostname
        # would resolve a second time — a window in which a server that
        # answered publicly at validation time answers privately at
        # connection time. The request goes to the verified address,
        # with the page's own name carried for SNI and virtual-host
        # routing (the webhook delivery pattern).
        pinned_ip = validate_webhook_url(url, allow_private=False)
    except ValueError as exc:
        log.warning('recipe cover: address rejected: %s', exc)
        return None

    parsed = urlparse(url)
    hostname = parsed.hostname or ''
    # A bare IPv6 literal is not a URL authority; it needs its brackets.
    host_part = f'[{pinned_ip}]' if ':' in pinned_ip else pinned_ip
    port_suffix = f':{parsed.port}' if parsed.port else ''
    target_url = f'{parsed.scheme}://{host_part}{port_suffix}{parsed.path}'
    if parsed.query:
        target_url += f'?{parsed.query}'

    chunks = bytearray()
    try:
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT, follow_redirects=False, transport=_transport
        ) as client:
            async with client.stream(
                'GET',
                target_url,
                headers={**_FETCH_HEADERS, 'Host': hostname},
                extensions={'sni_hostname': hostname, 'target_hostname': hostname},
            ) as response:
                response.raise_for_status()
                content_type = (
                    response.headers.get('content-type', '').split(';')[0].strip()
                )
                if content_type not in ALLOWED_RECIPE_IMAGE_MIMES:
                    log.info('recipe cover: %r is not an image we store', content_type)
                    return None
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    # Count what arrives, do not trust what was announced: a
                    # Content-Length can lie and a chunked response need not
                    # carry one at all.
                    if len(chunks) > MAX_COVER_BYTES:
                        log.info('recipe cover: larger than %d bytes', MAX_COVER_BYTES)
                        return None
    except httpx.HTTPError as exc:
        log.info('recipe cover: fetch failed for %r: %s', url, exc)
        return None

    content = bytes(chunks)
    try:
        # The declared type is the sender's word for it; the magic bytes are
        # the file's.
        validate_signature(content, content_type)
    except HTTPException as exc:
        log.warning('recipe cover: content does not match %r: %s', content_type, exc)
        return None
    return content, content_type


async def adopt_remote_cover(
    db: AsyncSession,
    recipe: Any,
    source: str | None,
    *,
    _transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Give *recipe* a cover of its own, fetched from *source*.

    The address is passed in rather than read off the recipe on purpose: with
    S3 storage the app's own covers also have ``https`` addresses, and a
    function that fetched whatever it found on the record would eventually be
    handed one of those.

    A recipe that arrived without a cover is left alone. One whose cover
    cannot be fetched ends up without it — an image the app does not have is
    not an image the app can show, and the alternative is a frame whose
    contents somebody else decides.
    """
    from .services import set_recipe_image_url

    if not source:
        return

    fetched = await fetch_remote_cover(source, _transport=_transport)
    if fetched is not None:
        content, content_type = fetched
        try:
            await set_recipe_image_url(
                db,
                recipe,
                await store_cover(
                    recipe.organization_id, recipe.id, content, content_type
                ),
            )
            return
        except CoverUnreadableError as exc:
            log.warning('recipe cover: %r could not be re-encoded: %s', source, exc)
        except AppException as exc:
            # A demo that is out of room refuses the write with a 413. The
            # recipe is already saved, so the refusal must not reach the
            # caller: a cover that cannot be kept is a recipe without one.
            code = exc.detail.get('code') if isinstance(exc.detail, dict) else None
            if exc.status_code != 413 or not str(code).startswith('DEMO_UPLOAD_'):
                raise
            log.warning('recipe cover: %r refused by the demo cap: %s', source, exc)

    await set_recipe_image_url(db, recipe, None)
