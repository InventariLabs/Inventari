"""The per-file limit stops the copy instead of measuring its result.

``await image.read()`` brings the whole upload into memory before anything
looks at its length; the helper these routes use now stops at the limit, so
a 30 MB upload costs the limit in RAM rather than 30 MB. The import path has
had that helper since it was written; the three image paths counted
afterwards.

What it is *not* is admission control. By the time a route runs, Starlette
has parsed the body into a spooled temporary file and the bytes have been
received — the cut on the way in belongs to ``BodySizeLimitMiddleware``
(``tests/unit/test_body_size_limit_middleware.py``), which refuses a declared
oversize without reading a byte and cuts a chunked body while it arrives.
This file was called ``test_a_body_is_capped_while_it_is_read`` and asserted
a 413 with a monkeypatched limit, which is true of both stories and evidence
for neither.
"""

from __future__ import annotations

import pytest
from fastapi import status
from starlette.testclient import TestClient

JPEG_MAGIC = b'\xff\xd8\xff'


@pytest.mark.integration
class TestTheItemImageEndpoint:
    def test_an_oversized_image_is_refused(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.api import _items_images

        monkeypatch.setattr(_items_images, '_MAX_IMAGE_BYTES', 100)

        response = client.post(
            f'/api/v1/items/{test_item.id}/image',
            headers=auth_headers,
            files={'image': ('big.jpg', JPEG_MAGIC + b'x' * 500, 'image/jpeg')},
        )

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    def test_an_image_inside_the_limit_still_goes_through(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_item,
    ) -> None:
        response = client.post(
            f'/api/v1/items/{test_item.id}/image',
            headers=auth_headers,
            files={'image': ('ok.jpg', JPEG_MAGIC + b'x' * 64, 'image/jpeg')},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
