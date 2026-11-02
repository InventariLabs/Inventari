"""A number search answers the number it names, not every number containing it.

``OUT/2026/001`` and ``INTERNAL_OUT/2026/001`` are two documents of two
different types, and one search used to find both: the one number contains
the other, and plain substring matching cannot tell them apart. New numbers
no longer spell their type that way — ``{TYPE}`` writes a short code — but a
register that has been running still holds numbers written before, and a
search must be able to name one of them without the other answering.

These documents are inserted with the numbers written out because that is
the state the tests are about: numbers already issued, which no code change
rewrites.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.warehouse.document_query_service import list_documents
from app.modules.warehouse.models import Document, DocumentStatus

pytestmark = pytest.mark.integration


@pytest.fixture
async def org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name=f'Number search org {uuid.uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'warehouse'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def user(real_async_db_session: AsyncSession, org: Organization) -> User:
    user = User(
        email=f'number-search-{uuid.uuid4().hex[:8]}@test.example',
        hashed_password='x',
        full_name='Number Search User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def numbered_documents(
    real_async_db_session: AsyncSession, org: Organization, user: User
) -> dict[str, Document]:
    """An external dispatch and an internal issue whose numbers overlap."""
    documents = {
        'out': Document(
            organization_id=org.id,
            type='OUT',
            number='OUT/2026/001',
            status=DocumentStatus.DRAFT.value,
            created_by=user.id,
        ),
        'internal_out': Document(
            organization_id=org.id,
            type='INTERNAL_OUT',
            number='INTERNAL_OUT/2026/001',
            status=DocumentStatus.DRAFT.value,
            created_by=user.id,
        ),
        'transfer': Document(
            organization_id=org.id,
            type='INT',
            number='INT/2026/001',
            status=DocumentStatus.DRAFT.value,
            created_by=user.id,
        ),
    }
    real_async_db_session.add_all(documents.values())
    await real_async_db_session.flush()
    return documents


class TestANumberSearchStopsAtItsOwnType:
    async def test_a_full_number_does_not_answer_for_a_number_containing_it(
        self,
        real_async_db_session: AsyncSession,
        org: Organization,
        numbered_documents: dict[str, Document],
    ) -> None:
        documents, total = await list_documents(
            real_async_db_session, org.id, search='OUT/2026/001'
        )

        assert total == 1
        assert [doc.number for doc in documents] == ['OUT/2026/001']

    async def test_the_containing_document_still_answers_its_own_number(
        self,
        real_async_db_session: AsyncSession,
        org: Organization,
        numbered_documents: dict[str, Document],
    ) -> None:
        documents, total = await list_documents(
            real_async_db_session, org.id, search='INTERNAL_OUT/2026/001'
        )

        assert total == 1
        assert [doc.number for doc in documents] == ['INTERNAL_OUT/2026/001']

    @pytest.mark.parametrize('term', ['2026/001', '001', '1', '01', '/001', '26/001'])
    async def test_a_partial_number_still_finds_every_number_it_sits_in(
        self,
        real_async_db_session: AsyncSession,
        org: Organization,
        numbered_documents: dict[str, Document],
        term: str,
    ) -> None:
        documents, total = await list_documents(
            real_async_db_session, org.id, search=term
        )

        assert total == len(numbered_documents)
