"""Integration tests for vision/OCR API endpoints.

Every case here has one expected status. The provider is replaced at the
client boundary (``_llm_double``), so "the extraction worked" and "the model
was unreachable" are separate tests with separate expectations — never one
assertion accepting both.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.modules.vision.tests.integration._llm_double import (
    answering,
    jpeg_bytes,
    patch_client,
    unreachable,
)

_JPEG_BYTES = jpeg_bytes()

# Two identical answers: the extraction retries once on an unusable reply, and
# a side_effect list that runs out raises StopIteration instead of failing the
# assertion under test.
_LABEL_ANSWER = (
    '{"name": "Milk 2%", "brand": "Farm", "weight": "1 l", "expiry_date": "2026-12-31"}'
)
_NUTRITION_ANSWER = '{"energy_kcal": 64, "proteins": 3.2, "fat": 1.5}'


@pytest.mark.integration
class TestVisionExtract:
    """Tests for the vision extraction endpoint."""

    def test_extract_returns_the_data_read_from_the_label(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(answering(_LABEL_ANSWER, _LABEL_ANSWER)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('test.jpg', _JPEG_BYTES, 'image/jpeg')},
            )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body['name'] == 'Milk 2%'
        assert body['expiry_date'] == '2026-12-31'

    def test_extract_from_multiple_images_returns_one_result(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Several photos of one product still describe one product."""
        with patch_client(answering(_LABEL_ANSWER, _LABEL_ANSWER)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files=[
                    ('images', ('t1.jpg', _JPEG_BYTES, 'image/jpeg')),
                    ('images', ('t2.jpg', _JPEG_BYTES, 'image/jpeg')),
                ],
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['name'] == 'Milk 2%'

    def test_extract_without_a_context_tag_reads_the_label_anyway(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """An untagged sticker is the ordinary case, not a client error."""
        with patch_client(answering(_LABEL_ANSWER, _LABEL_ANSWER)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('test.jpg', _JPEG_BYTES, 'image/jpeg')},
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['name'] == 'Milk 2%'

    def test_extract_unreachable_provider_is_500(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The counterpart of the success case, asserted separately."""
        with patch_client(unreachable()):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('test.jpg', _JPEG_BYTES, 'image/jpeg')},
            )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert 'connection reset' not in response.json()['detail']['message']

    def test_extract_without_any_file_is_422(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            '/api/v1/vision/extract',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_extract_rejects_a_non_image_upload(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A MIME type outside the whitelist never reaches the model."""
        response = client.post(
            '/api/v1/vision/extract',
            headers=auth_headers,
            files={'images': ('test.txt', b'not an image', 'text/plain')},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']
        assert detail['code'] == 'VISION_UNSUPPORTED_IMAGE_TYPE'
        assert 'text/plain' in detail['message']

    def test_extract_unauthorized(self, client: TestClient) -> None:
        response = client.post(
            '/api/v1/vision/extract',
            files={'images': ('test.jpg', _JPEG_BYTES, 'image/jpeg')},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestVisionExtractFileSize:
    """Tests for file size validation."""

    def test_extract_file_too_large(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.vision import router as vision_router

        monkeypatch.setattr(vision_router, '_MAX_IMAGE_BYTES', 100)

        response = client.post(
            '/api/v1/vision/extract',
            headers=auth_headers,
            files={'images': ('big.jpg', b'\xff\xd8\xff' + b'x' * 200, 'image/jpeg')},
        )

        # A file too large is 413 on every endpoint that takes one, and the
        # refusal names the ceiling it crossed.
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        detail = response.json()['detail']
        assert detail['code'] == 'FILE_TOO_LARGE'
        assert '100 B' in detail['message']


@pytest.mark.integration
class TestVisionExtractNutrition:
    """Tests for the /extract-nutrition endpoint."""

    def test_extract_nutrition_returns_the_table(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(answering(_NUTRITION_ANSWER, _NUTRITION_ANSWER)):
            response = client.post(
                '/api/v1/vision/extract-nutrition',
                headers=auth_headers,
                files={'file': ('table.jpg', _JPEG_BYTES, 'image/jpeg')},
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['energy_kcal'] == 64

    @pytest.mark.parametrize(
        ('permissions', 'expected'),
        [
            (['vision:extract'], status.HTTP_200_OK),
            (['items:read'], status.HTTP_403_FORBIDDEN),
        ],
        ids=['the photograph reader', 'without it'],
    )
    def test_extract_nutrition_is_behind_the_photograph_readers_permission(
        self,
        client: TestClient,
        db_session: Session,
        permissions: list[str],
        expected: int,
    ) -> None:
        """Reading a nutrition table is reading a photograph: ``vision:extract``."""
        h = ModuleTestHelper(db_session)
        org = h.create_org('Kitchen', ['vision', 'nutrition'])
        user = h.create_user(org, email='reader@example.com', role='user')
        h.grant_permissions(user, permissions)

        with patch_client(answering(_NUTRITION_ANSWER, _NUTRITION_ANSWER)):
            response = client.post(
                '/api/v1/vision/extract-nutrition',
                headers=h.get_auth_headers(user),
                files={'file': ('table.jpg', _JPEG_BYTES, 'image/jpeg')},
            )

        assert response.status_code == expected, response.text

    def test_extract_nutrition_no_file(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            '/api/v1/vision/extract-nutrition',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_extract_nutrition_invalid_file_type(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            '/api/v1/vision/extract-nutrition',
            headers=auth_headers,
            files={'file': ('data.txt', b'not an image', 'text/plain')},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_extract_nutrition_unauthorized(self, client: TestClient) -> None:
        response = client.post(
            '/api/v1/vision/extract-nutrition',
            files={'file': ('photo.jpg', _JPEG_BYTES, 'image/jpeg')},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_extract_nutrition_file_too_large(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.vision import router as vision_router

        monkeypatch.setattr(vision_router, '_MAX_IMAGE_BYTES', 100)

        response = client.post(
            '/api/v1/vision/extract-nutrition',
            headers=auth_headers,
            files={'file': ('big.jpg', b'\xff\xd8\xff' + b'x' * 200, 'image/jpeg')},
        )

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
