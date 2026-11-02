"""A code read off a photograph is looked up in the reader's own catalogue.

Vision had no cross-organization test. Its two routes take no id from the
caller -- only an image -- so the usual shape of a leak, a stranger's id in
the URL, does not apply here. The identifier arrives a different way: the
model reads a barcode off the picture, and the service hands it to the same
resolver chain a scanner feeds.

That is the surface. A barcode is not secret, it is printed on the package,
and anyone can photograph one. If the lookup were not tenant-scoped, holding
up a competitor's product would answer with the competitor's product card --
their name for it, their supplier, their price.

The provider is replaced at the client boundary, so the model "reads" exactly
the barcode the test wants it to.
"""

from __future__ import annotations

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.modules.vision.tests.integration._llm_double import (
    answering,
    jpeg_bytes,
    patch_client,
)

_JPEG_BYTES = jpeg_bytes()
_THEIR_BARCODE = '5901234123457'
_THEIR_PRODUCT = 'Competitor Reserve Blend'

# The extraction retries once on an unusable reply, so the double answers
# twice with the same content.
_ANSWER = f'{{"name": "Unlabelled jar", "brand": null, "barcode": "{_THEIR_BARCODE}"}}'


@pytest.fixture
def helper(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def stranger_org(helper: ModuleTestHelper) -> Organization:
    return helper.create_org(
        'Strangers Roastery', ['core', 'items', 'locations', 'vision']
    )


@pytest.fixture
def stranger_user(helper: ModuleTestHelper, stranger_org: Organization) -> User:
    return helper.create_user(stranger_org, email='roaster@strangers.example')


@pytest.fixture
def their_product(
    helper: ModuleTestHelper, stranger_org: Organization, stranger_user: User
) -> ProductTemplate:
    """A product card that exists, under a barcode anyone can photograph."""
    return helper.create_template(
        stranger_org, name=_THEIR_PRODUCT, barcode=_THEIR_BARCODE
    )


@pytest.mark.integration
class TestReadingABarcodeThatBelongsToSomebodyElse:
    def test_the_reading_carries_none_of_their_product_card(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        their_product: ProductTemplate,
    ) -> None:
        with patch_client(answering(_ANSWER, _ANSWER)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('jar.jpg', _JPEG_BYTES, 'image/jpeg')},
            )

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['barcode'] == _THEIR_BARCODE
        assert body.get('resolved') is None
        assert _THEIR_PRODUCT not in response.text

    def test_the_same_barcode_does_resolve_for_its_owner(
        self,
        client: TestClient,
        helper: ModuleTestHelper,
        stranger_user: User,
        their_product: ProductTemplate,
    ) -> None:
        """The other half: the lookup works, it is only scoped.

        Without this, the test above would pass just as well against a
        resolver that had quietly stopped resolving anything at all.
        """
        with patch_client(answering(_ANSWER, _ANSWER)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=helper.get_auth_headers(stranger_user),
                files={'images': ('jar.jpg', _JPEG_BYTES, 'image/jpeg')},
            )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert _THEIR_PRODUCT in response.text
