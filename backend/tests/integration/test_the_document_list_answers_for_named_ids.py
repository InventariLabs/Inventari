"""The document list answers for a named hand of ids.

A trail of stock movements carries its sources as ``(document, id)`` pairs;
naming a source with its number means asking the register for exactly those
rows — one ask for the page, not a detail fetch per row. The list already
answers for filters; it now answers for ids.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import create_access_token


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def docs_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name=f'Doc Ids {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'warehouse'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def docs_user(
    real_async_db_session: AsyncSession, docs_org: Organization
) -> User:
    user = await ModuleTestHelper.create_user_async(
        real_async_db_session, docs_org, email=f'keeper_{uuid4().hex[:8]}@test.com'
    )
    await real_async_db_session.commit()
    return user


def _document(org_id, user_id, number: str):
    from app.modules.warehouse.models.document import Document

    return Document(
        organization_id=org_id,
        type='IN',
        number=number,
        status='COMPLETED',
        total_gross=Decimal('10.00'),
        currency='EUR',
        created_by=user_id,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


@pytest.mark.integration
class TestTheDocumentListAnswersForNamedIds:
    async def test_the_list_answers_for_exactly_the_ids_named(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        docs_org: Organization,
        docs_user: User,
    ) -> None:

        wanted, other, foreign_kind = (
            _document(docs_org.id, docs_user.id, 'PZ/2026/001'),
            _document(docs_org.id, docs_user.id, 'WZ/2026/002'),
            _document(docs_org.id, docs_user.id, 'PZ/2026/003'),
        )
        real_async_db_session.add_all([wanted, other, foreign_kind])
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/warehouse/documents',
            params={
                'ids': [str(wanted.id), str(other.id)],
                'limit': 100,
            },
            headers=_auth(docs_user),
        )

        assert response.status_code == status.HTTP_200_OK
        numbers = {row['number'] for row in response.json()['items']}
        assert numbers == {'PZ/2026/001', 'WZ/2026/002'}

    async def test_another_organizations_document_is_not_named(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        docs_org: Organization,
        docs_user: User,
    ) -> None:

        stranger_org = Organization(
            name=f'Doc Ids Stranger {uuid4().hex[:6]}',
            enabled_modules=['core', 'items', 'warehouse'],
        )
        real_async_db_session.add(stranger_org)
        await real_async_db_session.flush()
        theirs = _document(stranger_org.id, docs_user.id, 'PZ/2026/XYZ')
        real_async_db_session.add(theirs)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/warehouse/documents',
            params={'ids': [str(theirs.id)], 'limit': 100},
            headers=_auth(docs_user),
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    async def test_no_ids_names_nothing_special(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        docs_org: Organization,
        docs_user: User,
    ) -> None:
        real_async_db_session.add(_document(docs_org.id, docs_user.id, 'PZ/2026/009'))
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/warehouse/documents', headers=_auth(docs_user)
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['total'] == 1
