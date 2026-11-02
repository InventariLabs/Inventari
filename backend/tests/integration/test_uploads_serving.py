"""Integration tests for the /uploads/{filepath} serving route.

Covers the global fix where files stored outside the core ``item_attachments``
table (item cover images, recipe cover images, equipment attachments) were
previously unservable (HTTP 404) despite existing on disk.
"""

from uuid import uuid4

import pytest
from fastapi import status


def _auth(client, user) -> dict:
    """Build an auth header carrying a real JWT for ``user``."""
    from app.services.token_service import create_access_token

    token = create_access_token(
        {'sub': str(user.id), 'org_id': str(user.organization_id), 'role': user.role}
    )
    return {'Authorization': f'Bearer {token}'}


def _png_bytes() -> bytes:
    # 1x1 transparent PNG.
    return (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
        b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )


@pytest.mark.integration
class TestItemCoverServing:
    """GET /uploads/<org_id>/items/{item_id}/cover.{ext} after a cover upload."""

    def test_uploaded_item_cover_is_served(self, client, test_item, test_user):
        """Regression: a freshly uploaded cover image must be served (was 404)."""
        headers = _auth(client, test_user)
        upload = client.post(
            f'/api/v1/items/{test_item.id}/image',
            headers=headers,
            files={'image': ('cover.png', _png_bytes(), 'image/png')},
        )
        assert upload.status_code == status.HTTP_200_OK, upload.text
        image_url = upload.json()['image_url']
        assert image_url.startswith(f'/uploads/{test_user.organization_id}/items/')

        served = client.get(image_url, headers=headers)
        assert served.status_code == status.HTTP_200_OK
        assert served.headers['content-type'] == 'image/png'
        assert len(served.content) > 0

    def test_archived_item_cover_is_still_served(self, client, test_item, test_user):
        """The archived card renders the cover it kept; the file must answer.

        Archiving is a soft delete: the record and its cover stay, and the
        card of an archived record is a page the app links to. Ownership read
        through the live-only lookup answered 404 there — a broken image on
        exactly the card a restore decision is made on.
        """
        headers = _auth(client, test_user)
        upload = client.post(
            f'/api/v1/items/{test_item.id}/image',
            headers=headers,
            files={'image': ('cover.png', _png_bytes(), 'image/png')},
        )
        assert upload.status_code == status.HTTP_200_OK, upload.text
        image_url = upload.json()['image_url']

        archived = client.delete(f'/api/v1/items/{test_item.id}', headers=headers)
        assert archived.status_code == status.HTTP_204_NO_CONTENT, archived.text

        served = client.get(image_url, headers=headers)
        assert served.status_code == status.HTTP_200_OK
        assert served.headers['content-type'] == 'image/png'

    async def test_resolver_denies_item_from_other_org(
        self, client, db_session, test_item, test_user, async_engine_fixture
    ):
        """The ItemCoverResolver returns None for a foreign organization.

        Ownership isolation is enforced inside the resolver via the org-scoped
        ``core_api.items.get_any_async``; this verifies it directly with an async
        session bound to the same test engine so the uploaded data is visible.
        """
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.core.uploads.resolvers import ItemCoverResolver

        owner_headers = _auth(client, test_user)
        upload = client.post(
            f'/api/v1/items/{test_item.id}/image',
            headers=owner_headers,
            files={'image': ('cover.png', _png_bytes(), 'image/png')},
        )
        assert upload.status_code == status.HTTP_200_OK, upload.text
        file_path = upload.json()['image_url'].removeprefix('/uploads/')

        factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        foreign_org = uuid4()
        async with factory() as async_db:
            meta = await ItemCoverResolver().resolve(async_db, file_path, foreign_org)
        assert meta is None, 'resolver must not resolve for a foreign organization'

    def test_nonexistent_file_404(self, client, test_user):
        headers = _auth(client, test_user)
        resp = client.get(
            f'/uploads/{test_user.organization_id}/items/{uuid4()}/cover.webp',
            headers=headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json()['detail']['code'] == 'NOT_FOUND'

    def test_unauthenticated_401(self, client, test_item, test_user):
        resp = client.get(
            f'/uploads/{test_user.organization_id}/items/{test_item.id}/cover.png'
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestAttachmentServingUnchanged:
    """The pre-existing attachments/{id}/... flow keeps working."""

    def test_attachment_without_row_404(self, client, test_user):
        """A path that no resolver owns returns 404, not 500."""
        headers = _auth(client, test_user)
        resp = client.get(
            f'/uploads/attachments/{uuid4()}/{uuid4().hex}.pdf',
            headers=headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestMediaCookieAuth:
    """Cookie-fallback auth for browser-native requests (``<img>``, downloads).

    Browser-native media requests cannot carry the ``Authorization: Bearer``
    header (the access token lives in JS memory). They do send the HttpOnly
    ``refresh_token`` cookie, which serve_upload accepts as a fallback.
    """

    def test_served_with_only_refresh_cookie(self, client, test_item, test_user):
        """An ``<img>``-style request (cookie, no Bearer) is authenticated."""
        from app.services.token_service import create_refresh_token

        # Upload a cover first (using the bearer path).
        headers = _auth(client, test_user)
        upload = client.post(
            f'/api/v1/items/{test_item.id}/image',
            headers=headers,
            files={'image': ('cover.png', _png_bytes(), 'image/png')},
        )
        assert upload.status_code == status.HTTP_200_OK
        image_url = upload.json()['image_url']

        # Request the file with ONLY the refresh cookie (no Authorization header).
        refresh = create_refresh_token({'sub': str(test_user.id), 'sid': 'media-test'})
        resp = client.get(
            image_url,
            cookies={'refresh_token': refresh},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.headers['content-type'] == 'image/png'

    def test_no_cookie_no_header_is_401(self, client, test_item, test_user):
        """A request with neither Bearer nor cookie is rejected."""
        resp = client.get(
            f'/uploads/{test_user.organization_id}/items/{test_item.id}/cover.png'
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_garbage_refresh_cookie_is_401(self, client, test_item, test_user):
        """A malformed refresh cookie is rejected, not treated as a valid user."""
        resp = client.get(
            f'/uploads/{test_user.organization_id}/items/{test_item.id}/cover.png',
            cookies={'refresh_token': 'not-a-real-token'},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert resp.json()['detail']['code'] == 'NOT_AUTHENTICATED'
        assert resp.headers['WWW-Authenticate'] == 'Bearer'

    # NOTE: A *revoked-but-well-formed* refresh cookie (e.g. after logout) is
    # verified by the token_blacklist unit tests — the blacklist is fail-open
    # in TESTING (no Redis), so revocation cannot be exercised here. The
    # serve_upload code path calls the same is_revoked()/is_user_revoked()
    # helpers used everywhere else, so revocation coverage is inherited.
