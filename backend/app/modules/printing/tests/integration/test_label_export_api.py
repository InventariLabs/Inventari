"""Integration tests for the label-rendering path owned by ``printing``.

The module exposes no HTTP endpoints of its own (see ``printing/router.py``):
it registers PNG renderers in ``app.core.label_rendering`` and Core serves
them through ``/api/v1/labels/pool/export/png``. That registry hop is the
module's public surface, so this is where it gets covered — a green unit test
on ``generate_label_png`` says nothing about whether Core can reach it, whether
the export stays inside one tenant, or what a caller sees when no renderer is
registered at all.
"""

import io
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import create_access_token

_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _make_org(db: AsyncSession, name: str) -> Organization:
    org = Organization(
        name=name,
        enabled_modules=['core', 'items', 'locations', 'printing'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def _make_labels(
    db: AsyncSession, org: Organization, user: User, count: int, prefix: str
) -> list[LabelPool]:
    labels = [
        LabelPool(
            short_code=f'{prefix}-{index:04d}',
            organization_id=org.id,
            created_by=user.id,
        )
        for index in range(count)
    ]
    db.add_all(labels)
    await db.commit()
    for label in labels:
        await db.refresh(label)
    return labels


@pytest.fixture
async def print_org(real_async_db_session: AsyncSession) -> Organization:
    return await _make_org(real_async_db_session, 'Printing Test Org')


@pytest.fixture
async def print_user(
    real_async_db_session: AsyncSession, print_org: Organization
) -> User:
    user = await ModuleTestHelper.create_user_async(
        real_async_db_session, print_org, email=f'print_{uuid4().hex[:8]}@test.com'
    )
    await real_async_db_session.commit()
    return user


@pytest.mark.integration
@pytest.mark.asyncio
class TestLabelExportPng:
    """The Core export endpoint rendered through the printing module."""

    async def test_export_batch_returns_png_stream(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        print_org: Organization,
        print_user: User,
    ) -> None:
        await _make_labels(real_async_db_session, print_org, print_user, 3, 'BATCH')

        response = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            headers=_auth(print_user),
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.headers['content-type'] == 'image/png'
        assert response.content.startswith(_PNG_MAGIC)
        assert 'labels_3pcs.png' in response.headers['content-disposition']

    async def test_export_single_label_by_short_code(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        print_org: Organization,
        print_user: User,
    ) -> None:
        labels = await _make_labels(
            real_async_db_session, print_org, print_user, 1, 'SINGLE'
        )

        response = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            headers=_auth(print_user),
            params={'short_codes': [labels[0].short_code]},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.content.startswith(_PNG_MAGIC)
        assert 'labels_1pcs.png' in response.headers['content-disposition']

    async def test_export_marks_labels_as_printed(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        print_org: Organization,
        print_user: User,
    ) -> None:
        labels = await _make_labels(
            real_async_db_session, print_org, print_user, 2, 'PRINTED'
        )
        assert all(label.printed_at is None for label in labels)
        org_id = print_org.id

        response = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            headers=_auth(print_user),
        )
        assert response.status_code == status.HTTP_200_OK

        # The endpoint wrote through its own session; this one still holds the
        # pre-export rows in its identity map. Identifiers are read before the
        # expiry — afterwards every attribute access would need a lazy refresh.
        real_async_db_session.expire_all()
        rows = (
            (
                await real_async_db_session.execute(
                    select(LabelPool).where(LabelPool.organization_id == org_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert all(row.printed_at is not None for row in rows)

    async def test_a_preview_render_does_not_spend_the_pool(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        print_org: Organization,
        print_user: User,
    ) -> None:
        """The preview asks for the same file; looking is not printing."""
        await _make_labels(real_async_db_session, print_org, print_user, 2, 'PREVIEW')
        org_id = print_org.id

        response = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            params={'mark_printed': 'false'},
            headers=_auth(print_user),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.headers['content-type'] == 'image/png'

        real_async_db_session.expire_all()
        rows = (
            (
                await real_async_db_session.execute(
                    select(LabelPool).where(LabelPool.organization_id == org_id)
                )
            )
            .scalars()
            .all()
        )
        assert all(row.printed_at is None for row in rows)

    async def test_the_file_is_the_label_at_its_size(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        print_org: Organization,
        print_user: User,
    ) -> None:
        """50 x 24 mm is 591 x 283 px at 300 dpi, and the file says 300 dpi.

        A short code alone is not cropped to the square either: the file is
        the label, so the preview of it and the paper it comes out on agree.
        """
        await _make_labels(real_async_db_session, print_org, print_user, 1, 'SIZE')

        response = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            params={
                'width': 50,
                'height': 24,
                'qr_only': 'true',
                'show_code': 'true',
                'mark_printed': 'false',
            },
            headers=_auth(print_user),
        )

        assert response.status_code == status.HTTP_200_OK
        image = Image.open(io.BytesIO(response.content))
        assert image.size == (591, 283)
        assert image.info['dpi'] == pytest.approx((300, 300), abs=0.5)

    async def test_a_caller_still_naming_a_media_profile_gets_the_same_file(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        print_org: Organization,
        print_user: User,
    ) -> None:
        """An agent from before one-label-one-file still sends ``media``."""
        await _make_labels(real_async_db_session, print_org, print_user, 1, 'MEDIA')

        plain, named = [
            await real_async_client.get(
                '/api/v1/labels/pool/export/png',
                params={'mark_printed': 'false', **extra},
                headers=_auth(print_user),
            )
            for extra in ({}, {'media': 'brother_tape'})
        ]

        assert named.status_code == status.HTTP_200_OK
        assert named.content == plain.content

    async def test_export_second_call_finds_nothing_left_to_print(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        print_org: Organization,
        print_user: User,
    ) -> None:
        await _make_labels(real_async_db_session, print_org, print_user, 1, 'ONCE')

        first = await real_async_client.get(
            '/api/v1/labels/pool/export/png', headers=_auth(print_user)
        )
        assert first.status_code == status.HTTP_200_OK

        second = await real_async_client.get(
            '/api/v1/labels/pool/export/png', headers=_auth(print_user)
        )
        assert second.status_code == status.HTTP_400_BAD_REQUEST

    async def test_export_empty_pool_returns_400(
        self,
        real_async_client: AsyncClient,
        print_user: User,
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            headers=_auth(print_user),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # The print agent polls this endpoint and tells "nothing to print"
        # from a real refusal by this code alone; the message is translated.
        assert response.json()['detail']['code'] == 'NO_LABELS_AVAILABLE'

    async def test_export_ignores_another_organizations_labels(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        print_org: Organization,
        print_user: User,
    ) -> None:
        other_org = await _make_org(real_async_db_session, 'Printing Other Org')
        other_user = await ModuleTestHelper.create_user_async(
            real_async_db_session, other_org, email=f'other_{uuid4().hex[:8]}@test.com'
        )
        await real_async_db_session.commit()
        foreign = await _make_labels(
            real_async_db_session, other_org, other_user, 2, 'FOREIGN'
        )
        other_org_id = other_org.id

        response = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            headers=_auth(print_user),
            params={'label_ids': [str(label.id) for label in foreign]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        real_async_db_session.expire_all()
        still_unprinted = (
            (
                await real_async_db_session.execute(
                    select(LabelPool).where(LabelPool.organization_id == other_org_id)
                )
            )
            .scalars()
            .all()
        )
        assert all(row.printed_at is None for row in still_unprinted)

    async def test_export_without_renderer_returns_503(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        print_org: Organization,
        print_user: User,
    ) -> None:
        """Absence of the printing module is a 503, never a corrupt image."""
        from app.core import label_rendering

        await _make_labels(real_async_db_session, print_org, print_user, 1, 'NORENDER')

        saved = (label_rendering._single, label_rendering._batch)
        label_rendering.clear_label_renderers()
        try:
            response = await real_async_client.get(
                '/api/v1/labels/pool/export/png',
                headers=_auth(print_user),
            )
        finally:
            if saved[0] is not None and saved[1] is not None:
                label_rendering.register_label_renderers(
                    single=saved[0], batch=saved[1]
                )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
