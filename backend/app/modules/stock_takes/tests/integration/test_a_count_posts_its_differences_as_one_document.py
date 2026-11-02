"""A count that changes the stock leaves one adjustment in the register.

Closing a count corrected each record straight away and left nothing in the
documents register: the office saw stock change with no document behind it,
while every receipt, issue and move had one. The differences now go there as
one stock adjustment — numbered, completed, its lines the signed differences —
written in the same transaction as the stock it describes. The count has
already moved the goods, so the document moves nothing: the stock changes
once, by the count.

A count that changed nothing leaves no document (the report says so), and
with the warehouse module off the count closes exactly as it always did.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus
from app.modules.warehouse.models import Document
from tests.integration._shelf import post_on_shelf

_WITH_DOCUMENTS = [
    'core',
    'items',
    'locations',
    'categories',
    'stock_takes',
    'warehouse',
]


def _org(db_session: Session, modules: list[str]) -> tuple[Organization, User]:
    helper = ModuleTestHelper(db_session)
    org = helper.create_org('Counted Shop', modules)
    return org, helper.create_user(org, email='counter@example.com')


def _shelf(db_session: Session, org: Organization, user: User) -> StorageLocation:
    helper = ModuleTestHelper(db_session)
    storage_type = helper.create_storage_type('Shelf', 'SHELF', organization_id=org.id)
    return helper.create_storage_location(org, storage_type, user, name='Shelf A')


def _record(
    client: TestClient,
    headers: dict[str, str],
    db_session: Session,
    template: ProductTemplate,
    shelf: StorageLocation,
    quantity: int,
) -> Item:
    record = post_on_shelf(client, headers, template, shelf.id, quantity)
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


def _count(
    db_session: Session,
    org: Organization,
    user: User,
    shelf: StorageLocation,
    rows: list[tuple[Item, int, int]],
) -> UUID:
    """A count of the shelf with each record held and counted as given."""
    stock_take = StockTake(
        user_id=user.id,
        organization_id=org.id,
        storage_location_id=shelf.id,
        name='Shelf A, Monday',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(stock_take)
    db_session.flush()
    for item, held, counted in rows:
        db_session.add(
            StockTakeItem(
                stock_take_id=stock_take.id,
                item_id=item.id,
                item_name=item.name,
                uom_id=item.uom_id,
                system_quantity=Decimal(held),
                counted_quantity=Decimal(counted),
                storage_location_id=shelf.id,
            )
        )
    db_session.commit()
    return stock_take.id


def _close(
    client: TestClient, headers: dict[str, str], take_id: UUID
) -> dict[str, Any]:
    response = client.post(
        f'/api/v1/stock-takes/{take_id}/complete',
        headers=headers,
        json={'apply_adjustments': True, 'force_over_tolerance': True},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(dict[str, Any], response.json())


def _held(db_session: Session, item: Item) -> Decimal:
    record = db_session.get(Item, item.id)
    assert record is not None
    return Decimal(record.quantity)


def _documents(db_session: Session, org: Organization) -> list[Document]:
    db_session.expire_all()
    return list(
        db_session.execute(select(Document).where(Document.organization_id == org.id))
        .scalars()
        .all()
    )


@pytest.mark.integration
class TestACountPostsItsDifferencesAsOneDocument:
    def test_the_differences_become_one_completed_adjustment(
        self, client: TestClient, db_session: Session
    ) -> None:
        org, user = _org(db_session, _WITH_DOCUMENTS)
        headers = ModuleTestHelper(db_session).get_auth_headers(user)
        shelf = _shelf(db_session, org, user)
        helper = ModuleTestHelper(db_session)
        rice = _record(
            client,
            headers,
            db_session,
            helper.create_template(org, name='Rice'),
            shelf,
            10,
        )
        oil = _record(
            client,
            headers,
            db_session,
            helper.create_template(org, name='Oil'),
            shelf,
            4,
        )
        salt = _record(
            client,
            headers,
            db_session,
            helper.create_template(org, name='Salt'),
            shelf,
            5,
        )
        take_id = _count(
            db_session, org, user, shelf, [(rice, 10, 8), (oil, 4, 6), (salt, 5, 5)]
        )

        report = _close(client, headers, take_id)

        documents = _documents(db_session, org)
        assert len(documents) == 1
        document = documents[0]
        assert document.type == 'ADJUSTMENT'
        assert document.status == 'COMPLETED'
        assert document.stock_already_applied is True
        assert document.target_location_id == shelf.id
        assert not document.number.startswith('DRAFT')
        assert sorted((line.name, line.done_quantity) for line in document.lines) == [
            ('Oil', Decimal('2')),
            ('Rice', Decimal('-2')),
        ]
        assert report['adjustment_document_id'] == str(document.id)
        assert report['adjustment_document_number'] == document.number

        # The report read later names the same document.
        again = client.get(f'/api/v1/stock-takes/{take_id}/report', headers=headers)
        assert again.status_code == status.HTTP_200_OK, again.text
        assert again.json()['adjustment_document_number'] == document.number

        # The stock moved once — by the count, not again by the document —
        # and its movements name the document, which can show them.
        assert _held(db_session, rice) == Decimal('8')
        assert _held(db_session, oil) == Decimal('6')
        corrections = (
            db_session.execute(
                select(StockMove).where(
                    StockMove.reference_type == 'document',
                    StockMove.reference_id == document.id,
                )
            )
            .scalars()
            .all()
        )
        assert len(corrections) == 2

    def test_a_count_that_changed_nothing_leaves_no_document(
        self, client: TestClient, db_session: Session
    ) -> None:
        org, user = _org(db_session, _WITH_DOCUMENTS)
        headers = ModuleTestHelper(db_session).get_auth_headers(user)
        shelf = _shelf(db_session, org, user)
        rice = _record(
            client,
            headers,
            db_session,
            ModuleTestHelper(db_session).create_template(org, name='Rice'),
            shelf,
            10,
        )
        take_id = _count(db_session, org, user, shelf, [(rice, 10, 10)])

        report = _close(client, headers, take_id)

        assert _documents(db_session, org) == []
        assert report['adjustment_document_id'] is None
        assert report['discrepancies'] == 0
        assert report['status'] == 'completed'

    def test_without_the_documents_module_the_count_closes_as_before(
        self, client: TestClient, db_session: Session
    ) -> None:
        org, user = _org(
            db_session, ['core', 'items', 'locations', 'categories', 'stock_takes']
        )
        headers = ModuleTestHelper(db_session).get_auth_headers(user)
        shelf = _shelf(db_session, org, user)
        rice = _record(
            client,
            headers,
            db_session,
            ModuleTestHelper(db_session).create_template(org, name='Rice'),
            shelf,
            10,
        )
        take_id = _count(db_session, org, user, shelf, [(rice, 10, 7)])

        report = _close(client, headers, take_id)

        assert _documents(db_session, org) == []
        assert report['adjustment_document_id'] is None
        assert _held(db_session, rice) == Decimal('7')
        # With no document, the movement names the count, as it always did.
        db_session.expire_all()
        references = {
            (move.reference_type, move.reference_id)
            for move in db_session.execute(select(StockMove)).scalars()
            if move.reference_type != 'item'
        }
        assert references == {('adjustment', take_id)}

    def test_a_line_carries_what_the_counter_wrote_not_the_reason_code(
        self, client: TestClient, db_session: Session
    ) -> None:
        # The document page prints a line's note as it stands, so a reason
        # code there reads "SYSTEM_ERROR"; the reason stays on the count's
        # report, which speaks the reader's language.
        org, user = _org(db_session, _WITH_DOCUMENTS)
        headers = ModuleTestHelper(db_session).get_auth_headers(user)
        shelf = _shelf(db_session, org, user)
        helper = ModuleTestHelper(db_session)
        rice = _record(
            client,
            headers,
            db_session,
            helper.create_template(org, name='Rice'),
            shelf,
            10,
        )
        oil = _record(
            client,
            headers,
            db_session,
            helper.create_template(org, name='Oil'),
            shelf,
            4,
        )
        take_id = _count(db_session, org, user, shelf, [(rice, 10, 8), (oil, 4, 6)])
        for row in db_session.execute(
            select(StockTakeItem).where(StockTakeItem.stock_take_id == take_id)
        ).scalars():
            row.discrepancy_reason_code = 'SYSTEM_ERROR'
            if row.item_id == oil.id:
                row.discrepancy_reason = 'Two boxes behind the bin'
        db_session.commit()

        _close(client, headers, take_id)

        (document,) = _documents(db_session, org)
        assert sorted((line.name, line.notes) for line in document.lines) == [
            ('Oil', 'Two boxes behind the bin'),
            ('Rice', None),
        ]

    def test_a_line_names_the_location_the_difference_was_counted_on(
        self, client: TestClient, db_session: Session
    ) -> None:
        # A count covers its location and everything below it. The line has to
        # say where the stock it corrects stands — the shelf below, not the
        # rack the count was opened on — or the document's location and its
        # movements tell two stories.
        org, user = _org(db_session, _WITH_DOCUMENTS)
        headers = ModuleTestHelper(db_session).get_auth_headers(user)
        rack = _shelf(db_session, org, user)
        helper = ModuleTestHelper(db_session)
        storage_type = helper.create_storage_type('Bin', 'BIN', organization_id=org.id)
        below = helper.create_storage_location(org, storage_type, user, name='Bin 1')
        below.parent_id = rack.id
        db_session.commit()
        rice = _record(
            client,
            headers,
            db_session,
            helper.create_template(org, name='Rice'),
            below,
            10,
        )
        take_id = _count(db_session, org, user, rack, [(rice, 10, 8)])
        db_session.execute(
            update(StockTakeItem)
            .where(StockTakeItem.stock_take_id == take_id)
            .values(storage_location_id=below.id)
        )
        db_session.commit()

        _close(client, headers, take_id)

        (document,) = _documents(db_session, org)
        assert document.target_location_id == rack.id
        assert [line.target_location_id for line in document.lines] == [below.id]
