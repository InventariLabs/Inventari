"""The same press made twice leaves one stock effect and tells the loser why.

A double press, the same document open in two tabs, a retry after a slow
answer: each sends the one-step post (or the undo) a second time. Whatever
the order the two arrive in, the shelf must show one movement, not two, and
the one that lost must be handed a sentence it can show a reader — not a
database error, not a second posting.

Concurrent cases run two doors on two connections of their own, the way
``test_confirm_and_cancel_at_once_on_one_document`` does; the sequential
cases go through the HTTP door so the sentence is the one the screen shows.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse import _document_workflow_transitions as transitions
from app.modules.warehouse.document_correction_service import undo_document
from app.modules.warehouse.document_profile_service import get_or_create_profile
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus
from app.modules.warehouse.schemas import DocumentCreate
from tests.integration._shelf import put_on_shelf

_ON_SHELF = Decimal('10')
_TAKEN = Decimal('1')


class _Shelf:
    """One shelf holding ten of one product."""

    org_id: uuid.UUID
    user_id: uuid.UUID
    shelf_id: uuid.UUID
    template_id: uuid.UUID
    record_id: uuid.UUID


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


async def _shelf_with_one_product(db: AsyncSession) -> _Shelf:
    shelf = _Shelf()
    org = Organization(
        name=f'Twice {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'twice_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    location = StorageLocation(
        organization_id=org.id, created_by=user.id, name='Dry store'
    )
    db.add(location)
    await db.flush()
    template = ProductTemplate(
        organization_id=org.id, name='Rice', sku=f'Rice-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    await db.flush()
    record = await put_on_shelf(
        db, user, template, location.id, _ON_SHELF, purchase_price=Decimal('2')
    )
    # Made here so the two doors below do not race on creating the profile.
    await get_or_create_profile(db, org.id)
    await db.commit()
    shelf.org_id = org.id
    shelf.user_id = user.id
    shelf.shelf_id = location.id
    shelf.template_id = template.id
    shelf.record_id = record.id
    return shelf


async def _draft_issue(db: AsyncSession, shelf: _Shelf) -> uuid.UUID:
    doc = Document(
        organization_id=shelf.org_id,
        type='OUT',
        number=f'OUT/T/{uuid.uuid4().hex[:6]}',
        status=DocumentStatus.DRAFT.value,
        source_location_id=shelf.shelf_id,
        created_by=shelf.user_id,
    )
    db.add(doc)
    await db.flush()
    db.add(
        DocumentLine(
            document_id=doc.id,
            line_number=1,
            name='Rice',
            product_template_id=shelf.template_id,
            item_id=shelf.record_id,
            quantity=_TAKEN,
            expected_quantity=_TAKEN,
            done_quantity=Decimal('0'),
        )
    )
    await db.commit()
    return doc.id


async def _run_two(first: Any, second: Any) -> tuple[Any, ...]:
    """Run two doors at once, each on a connection of its own and its own
    transaction: committed when the door went through, rolled back when it
    was refused, as the request would do."""
    engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def on_its_own_connection(work: Any) -> Any:
        async with factory() as session:
            try:
                result = await work(session)
                await session.commit()
                return result
            except BaseException:
                await session.rollback()
                raise

    try:
        return tuple(
            await asyncio.gather(
                on_its_own_connection(first),
                on_its_own_connection(second),
                return_exceptions=True,
            )
        )
    finally:
        await engine.dispose()


def _one_wins_one_is_refused(outcomes: tuple[Any, ...]) -> ValueError:
    """Exactly one door went through; the other was handed a stated refusal.

    A refusal is a ``ValueError`` (the services' own no). A deadlock, a
    unique violation or anything else the database said is not one.
    """
    refused = [o for o in outcomes if isinstance(o, BaseException)]
    went_through = [o for o in outcomes if not isinstance(o, BaseException)]
    assert len(went_through) == 1, outcomes
    assert len(refused) == 1, outcomes
    assert isinstance(refused[0], ValueError), outcomes
    assert str(refused[0]).strip(), 'the refusal carries no sentence'
    return refused[0]


async def _on_hand(db: AsyncSession, shelf: _Shelf) -> Decimal:
    group = await db.scalar(
        select(ShelfRow)
        .where(ShelfRow.product_template_id == shelf.template_id)
        .execution_options(populate_existing=True)
    )
    assert group is not None, 'the records of the shelf are gone'
    return cast(Decimal, group.quantity)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_posts_of_one_draft_at_once_issue_it_once(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    shelf = await _shelf_with_one_product(db)
    doc_id = await _draft_issue(db, shelf)

    async def press(session: AsyncSession) -> Document:
        return await transitions.post_document_now(
            session, shelf.org_id, doc_id, shelf.user_id
        )

    outcomes = await _run_two(press, press)

    loser = _one_wins_one_is_refused(outcomes)
    assert 'already been posted' in str(loser)
    assert await _on_hand(db, shelf) == _ON_SHELF - _TAKEN
    status_now = await db.scalar(
        select(Document.status)
        .where(Document.id == doc_id)
        .execution_options(populate_existing=True)
    )
    assert status_now == DocumentStatus.COMPLETED.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_undos_of_one_document_at_once_put_the_stock_back_once(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    shelf = await _shelf_with_one_product(db)
    doc_id = await _draft_issue(db, shelf)
    await transitions.post_document_now(db, shelf.org_id, doc_id, shelf.user_id)
    await db.commit()
    assert await _on_hand(db, shelf) == _ON_SHELF - _TAKEN

    async def undo(session: AsyncSession) -> Document:
        return await undo_document(session, shelf.org_id, doc_id, shelf.user_id)

    outcomes = await _run_two(undo, undo)

    _one_wins_one_is_refused(outcomes)
    assert await _on_hand(db, shelf) == _ON_SHELF


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_presses_with_one_key_at_once_post_one_document(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    shelf = await _shelf_with_one_product(db)
    key = uuid.uuid4().hex

    async def press(session: AsyncSession) -> Document:
        return await transitions.post_new_document(
            session,
            shelf.org_id,
            DocumentCreate.model_validate(
                {
                    'type': 'OUT',
                    'source_location_id': str(shelf.shelf_id),
                    'lines': [
                        {
                            'item_id': str(shelf.record_id),
                            'product_template_id': str(shelf.template_id),
                            'expected_quantity': '1',
                            'unit_price': '10.00',
                        }
                    ],
                }
            ),
            shelf.user_id,
            post_key=key,
        )

    outcomes = await _run_two(press, press)

    assert not any(isinstance(o, BaseException) for o in outcomes), outcomes
    assert outcomes[0].id == outcomes[1].id
    assert await _on_hand(db, shelf) == _ON_SHELF - _TAKEN
    made = await db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.organization_id == shelf.org_id, Document.post_key == key)
    )
    assert made == 1


def _post(
    client: TestClient, headers: dict[str, str], payload: dict[str, Any]
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents/post', headers=headers, json=payload
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


def _a_receipt(
    partner: Partner, target: StorageLocation, template: ProductTemplate
) -> dict[str, Any]:
    return {
        'type': 'IN',
        'partner_id': str(partner.id),
        'target_location_id': str(target.id),
        'lines': [{'product_template_id': str(template.id), 'expected_quantity': '10'}],
    }


@pytest.mark.integration
class TestAPressRepeatedAfterTheFirstLanded:
    def test_posting_a_posted_document_again_is_refused_and_posts_nothing(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        posted = _post(
            client,
            doc_auth_headers,
            _a_receipt(doc_partner, doc_target_location, doc_template),
        )
        record_id = posted['lines'][0]['item_id']

        again = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/post', headers=doc_auth_headers
        )

        assert again.status_code == status.HTTP_400_BAD_REQUEST, again.text
        db_session.expire_all()
        record = db_session.get(Item, record_id)
        assert record is not None
        assert record.quantity == Decimal('10')
        sentence = again.text.lower()
        assert 'already' in sentence or 'posted' in sentence, again.text

    def test_undoing_an_undone_document_is_refused_and_restores_nothing_more(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        posted = _post(
            client,
            doc_auth_headers,
            _a_receipt(doc_partner, doc_target_location, doc_template),
        )
        record_id = posted['lines'][0]['item_id']
        first = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert first.status_code == status.HTTP_200_OK, first.text

        second = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )

        assert second.status_code == status.HTTP_400_BAD_REQUEST, second.text
        assert 'already been reversed' in second.text, second.text
        db_session.expire_all()
        record = db_session.get(Item, record_id)
        assert record is not None
        assert record.quantity == Decimal('0')

    def test_a_repeated_press_with_the_same_key_is_answered_with_the_first_document(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        payload = _a_receipt(doc_partner, doc_target_location, doc_template)
        headers = {**doc_auth_headers, 'Idempotency-Key': uuid.uuid4().hex}

        first = client.post(
            '/api/v1/warehouse/documents/post', headers=headers, json=payload
        )
        again = client.post(
            '/api/v1/warehouse/documents/post', headers=headers, json=payload
        )

        assert first.status_code == status.HTTP_201_CREATED, first.text
        assert again.status_code == status.HTTP_201_CREATED, again.text
        assert again.json()['id'] == first.json()['id']
        assert again.json()['number'] == first.json()['number']
        db_session.expire_all()
        record = db_session.get(Item, first.json()['lines'][0]['item_id'])
        assert record is not None
        assert record.quantity == Decimal('10')
        in_the_register = db_session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.id == first.json()['id'])
        )
        assert in_the_register == 1

    def test_a_press_with_a_new_key_posts_a_new_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        payload = _a_receipt(doc_partner, doc_target_location, doc_template)

        first = client.post(
            '/api/v1/warehouse/documents/post',
            headers={**doc_auth_headers, 'Idempotency-Key': uuid.uuid4().hex},
            json=payload,
        )
        second = client.post(
            '/api/v1/warehouse/documents/post',
            headers={**doc_auth_headers, 'Idempotency-Key': uuid.uuid4().hex},
            json=payload,
        )

        assert second.json()['id'] != first.json()['id']
