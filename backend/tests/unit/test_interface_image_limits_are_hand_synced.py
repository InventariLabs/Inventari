"""The interface-image limit is a hand-synced agreement, not a derivation.

There is no API that would hand the browser its upload limits — the owner
settled that deliberately (the same call was made for vision): each side
names the number in a constant, and this test is what keeps the backend
side of that agreement honest. The number is ten megabytes because phones
take bigger photos than five, and a refusal that only arrives after the
bytes have crossed the network is a refusal the user paid for.

The frontend side of the agreement lives in
``frontend/src/utils/fileValidation.ts`` — review reads both; neither can
read the other.
"""

from __future__ import annotations

import pytest

from app.api._items_images import _MAX_IMAGE_BYTES as ITEM_IMAGE_LIMIT
from app.api.organizations import _MAX_LOGO_BYTES as LOGO_LIMIT
from app.modules.recipes._recipe_cover import MAX_COVER_BYTES as RECIPE_COVER_LIMIT

pytestmark = pytest.mark.unit

TEN_MEGABYTES = 10 * 1024 * 1024


@pytest.mark.parametrize(
    ('name', 'limit'),
    [
        ('item image', ITEM_IMAGE_LIMIT),
        ('organization logo', LOGO_LIMIT),
        ('recipe cover', RECIPE_COVER_LIMIT),
    ],
)
def test_an_interface_image_limit_is_the_agreed_ten_megabytes(
    name: str, limit: int
) -> None:
    assert limit == TEN_MEGABYTES, (
        f'The {name} limit moved to {limit} B. That is a product decision '
        'with a frontend twin — change both sides in one review or change '
        'neither.'
    )
