"""A per-file limit at the request ceiling is a branch nobody can reach.

Two limits act on the same upload and only one is admission control.
``MAX_REQUEST_BODY_SIZE`` refuses the request — a declared oversize without
reading a byte, a chunked one while it arrives. The per-file limits at the
routes bound the copy that reaches memory, and they only ever run on a body
the ceiling already let through.

The ceiling is set for the largest thing the product accepts, a 50 MB
spreadsheet, plus multipart framing. An image route that asked for the same
50 MB therefore had no limit of its own: a body big enough to trip it was
within the framing of being refused outright, and the branch under it could
not fire. That is what the vision endpoint did.
"""

from __future__ import annotations

import pytest

from app.api._items_images import _MAX_IMAGE_BYTES as ITEM_IMAGE_LIMIT
from app.api.organizations import _MAX_LOGO_BYTES as LOGO_LIMIT
from app.config import settings
from app.core.upload_validation import MAX_IMPORT_SIZE
from app.modules.recipes._recipe_cover import MAX_COVER_BYTES as RECIPE_COVER_LIMIT
from app.modules.vision.router import _MAX_IMAGE_BYTES as VISION_IMAGE_LIMIT

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ('name', 'limit'),
    [
        ('item image', ITEM_IMAGE_LIMIT),
        ('organization logo', LOGO_LIMIT),
        ('recipe cover', RECIPE_COVER_LIMIT),
        ('vision image', VISION_IMAGE_LIMIT),
    ],
)
def test_an_image_limit_fires_well_before_the_request_ceiling(
    name: str, limit: int
) -> None:
    """A quarter of the ceiling, so the route's own refusal is the one seen.

    Not an arbitrary ratio: it is the difference between "this file is bigger
    than this endpoint accepts", which names the file and the endpoint, and
    "Request body too large", which names neither and arrives the same way
    for every route in the application.
    """
    ceiling = settings.MAX_REQUEST_BODY_SIZE

    assert limit * 4 <= ceiling, (
        f'The {name} limit ({limit} B) sits against the request ceiling '
        f'({ceiling} B), so a body big enough to trip it is refused by the '
        'middleware first and the endpoint has no working limit of its own.'
    )


def test_the_ceiling_leaves_room_for_the_largest_import_plus_its_framing() -> None:
    """The one limit the ceiling was sized for, stated as a relationship.

    A spreadsheet exactly at ``MAX_IMPORT_SIZE`` still travels inside a
    multipart body, so the ceiling has to be the payload plus framing —
    lower it to the payload and the import limit becomes unreachable in the
    same way the vision one was.
    """
    assert settings.MAX_REQUEST_BODY_SIZE > MAX_IMPORT_SIZE
