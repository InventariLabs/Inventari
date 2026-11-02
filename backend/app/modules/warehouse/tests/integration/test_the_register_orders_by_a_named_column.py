"""The register's ORDER BY is chosen from a table, not from the argument.

The route validates ``sort_by`` against a regex, and the service used to hand
whatever arrived to ``getattr(Document, sort_by, ...)``. That made the route
the only thing standing between a caller and an arbitrary attribute of the
model — and a service does not get to assume its caller is a route. These
tests call the service with no route in front of it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.warehouse.document_query_service import list_documents
from app.modules.warehouse.document_todo_service import completed_documents_async
from app.modules.warehouse.models import Document, DocumentStatus

pytestmark = pytest.mark.integration


@pytest.fixture
async def org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name=f'Sort Org {uuid.uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'warehouse'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def user(real_async_db_session: AsyncSession, org: Organization) -> User:
    user = User(
        email=f'sort-{uuid.uuid4().hex[:8]}@test.example',
        hashed_password='x',
        full_name='Sort User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def two_documents(
    real_async_db_session: AsyncSession, org: Organization, user: User
) -> tuple[Document, Document]:
    """An older document numbered above a newer one.

    The two orders disagree on purpose: whichever column the query ends up
    ordering by, the answer says which one it was.
    """
    now = datetime.now(UTC)
    older = Document(
        organization_id=org.id,
        type='IN',
        number='2026/0002',
        status=DocumentStatus.DRAFT.value,
        created_by=user.id,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )
    newer = Document(
        organization_id=org.id,
        type='IN',
        number='2026/0001',
        status=DocumentStatus.DRAFT.value,
        created_by=user.id,
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
    )
    real_async_db_session.add_all([older, newer])
    await real_async_db_session.flush()
    return older, newer


class TestTheRegisterOrdersByANamedColumn:
    async def test_an_unknown_key_falls_back_instead_of_reaching_an_attribute(
        self,
        real_async_db_session: AsyncSession,
        org: Organization,
        two_documents: tuple[Document, Document],
    ) -> None:
        older, newer = two_documents

        documents, total = await list_documents(
            real_async_db_session, org.id, sort_by='__class__'
        )

        assert total == 2
        assert [d.id for d in documents] == [newer.id, older.id]

    @pytest.mark.parametrize(
        'key', ['lines', 'metadata', 'number;drop', 'organization']
    )
    async def test_no_other_attribute_of_the_model_can_be_ordered_by(
        self,
        real_async_db_session: AsyncSession,
        org: Organization,
        two_documents: tuple[Document, Document],
        key: str,
    ) -> None:
        older, newer = two_documents

        documents, _ = await list_documents(real_async_db_session, org.id, sort_by=key)

        assert [d.id for d in documents] == [newer.id, older.id]

    async def test_a_named_column_still_orders_by_itself(
        self,
        real_async_db_session: AsyncSession,
        org: Organization,
        two_documents: tuple[Document, Document],
    ) -> None:
        older, newer = two_documents

        documents, _ = await list_documents(
            real_async_db_session, org.id, sort_by='number', sort_order='asc'
        )

        assert [d.number for d in documents] == [newer.number, older.number]


class TestWhatWasDoneIsOrderedByWhenItWasDone:
    async def test_the_done_list_is_cut_by_the_time_it_prints(
        self,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        # The To do board says when each posted document was posted. A short
        # list cut by when the documents were typed in left out the order
        # written days ago and dispatched a minute ago.
        now = datetime.now(UTC)
        written_long_ago = Document(
            organization_id=org.id,
            type='OUT',
            number='OUT/2026/0002',
            status=DocumentStatus.COMPLETED.value,
            created_by=user.id,
            created_at=now - timedelta(days=3),
            updated_at=now - timedelta(minutes=5),
            completed_at=now - timedelta(minutes=5),
        )
        written_today = Document(
            organization_id=org.id,
            type='IN',
            number='IN/2026/0003',
            status=DocumentStatus.COMPLETED.value,
            created_by=user.id,
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(minutes=50),
            completed_at=now - timedelta(minutes=50),
        )
        real_async_db_session.add_all([written_long_ago, written_today])
        await real_async_db_session.flush()

        documents, total = await completed_documents_async(
            real_async_db_session, org.id, since=now - timedelta(hours=2), limit=1
        )

        assert total == 2
        assert [d.id for d in documents] == [written_long_ago.id]
