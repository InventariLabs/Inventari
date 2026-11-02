"""A backorder draft in To do says whether the stock it waits for has arrived.

The draft a short dispatch leaves behind is a decision, and until now the
person deciding had to open it and compare it with the shelves by hand. The
queue now reads the answer from the stock itself, at request time: how much
of the draft the pickable shelves cover — ``full``, ``partial`` or ``none``.

Nothing is stored, so the answer cannot lag behind the way stock rose; the
tests raise it by a receipt, a correction, a count and a transfer and look at
the same draft each time. Goods that cannot be issued — on the quarantine
shelf, in a receiving area, in a quarantined batch — are not stock a draft can
be filled from.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus
from tests.integration._shelf import (
    post_on_shelf,
    put_on_shelf,
    run_in_async_session,
    shelf_keeper,
)

_TODAY = date.today().isoformat()


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Backorder Cover Org',
        ['core', 'items', 'locations', 'categories', 'warehouse', 'stock_takes'],
    )


@pytest.fixture
def user(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='cover@example.com')


@pytest.fixture
def headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


@pytest.fixture
def storage_type(h: ModuleTestHelper, org: Organization) -> StorageType:
    return h.create_storage_type('Warehouse', 'WAREHOUSE', organization_id=org.id)


def _place(
    h: ModuleTestHelper,
    db_session: Session,
    org: Organization,
    storage_type: StorageType,
    user: User,
    name: str,
    parent: StorageLocation | None = None,
) -> StorageLocation:
    location = h.create_storage_location(org, storage_type, user, name=name)
    if parent is not None:
        location.parent_id = parent.id
        db_session.commit()
        db_session.refresh(location)
    return location


@pytest.fixture
def warehouse(
    h: ModuleTestHelper,
    db_session: Session,
    org: Organization,
    storage_type: StorageType,
    user: User,
) -> StorageLocation:
    return _place(h, db_session, org, storage_type, user, 'Main warehouse')


@pytest.fixture
def shelf(
    h: ModuleTestHelper,
    db_session: Session,
    org: Organization,
    storage_type: StorageType,
    user: User,
    warehouse: StorageLocation,
) -> StorageLocation:
    return _place(h, db_session, org, storage_type, user, 'Shelf A', warehouse)


@pytest.fixture
def other_site(
    h: ModuleTestHelper,
    db_session: Session,
    org: Organization,
    storage_type: StorageType,
    user: User,
) -> StorageLocation:
    return _place(h, db_session, org, storage_type, user, 'Other site')


@pytest.fixture
def template(h: ModuleTestHelper, org: Organization) -> ProductTemplate:
    return h.create_template(org, name='Cover Widget', barcode='5901234999991')


def _draft(
    db_session: Session,
    org: Organization,
    user: User,
    template: ProductTemplate,
    source: StorageLocation,
    *,
    doc_type: str = 'OUT',
    quantity: str = '8',
    record: UUID | None = None,
) -> UUID:
    """The draft a short ``doc_type`` completion leaves behind, owing *quantity*."""
    origin = Document(
        organization_id=org.id,
        type=doc_type,
        number=f'{doc_type}/1',
        status=DocumentStatus.COMPLETED.value,
        source_location_id=source.id,
        created_by=user.id,
    )
    db_session.add(origin)
    db_session.flush()
    draft = Document(
        organization_id=org.id,
        type=doc_type,
        number='DRAFT-cover',
        status=DocumentStatus.DRAFT.value,
        source_location_id=source.id,
        created_by=user.id,
        backorder_id=origin.id,
    )
    draft.lines.append(
        DocumentLine(
            line_number=1,
            item_id=record,
            product_template_id=None if record else template.id,
            name=template.name,
            quantity=Decimal(quantity),
            expected_quantity=Decimal(quantity),
            done_quantity=Decimal('0'),
        )
    )
    db_session.add(draft)
    db_session.commit()
    return draft.id


def _task(
    client: TestClient, headers: dict[str, str], draft_id: UUID
) -> dict[str, Any]:
    response = client.get(
        '/api/v1/warehouse/todo',
        headers=headers,
        params={'date_to': _TODAY, 'limit': 50},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    for item in response.json()['work_items']['items']:
        if item['key'] == f'document:{draft_id}:backorder':
            return cast(dict[str, Any], item)
    raise AssertionError(f'{draft_id} is not a task in To do: {response.json()}')


def _cover(client: TestClient, headers: dict[str, str], draft_id: UUID) -> Any:
    return _task(client, headers, draft_id)['stock_cover']


def _document(
    client: TestClient,
    headers: dict[str, str],
    doc_type: str,
    template: ProductTemplate,
    quantity: int,
    *,
    item_id: str | None = None,
    **places: StorageLocation,
) -> None:
    """Create, confirm and complete a document in full."""
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': doc_type,
            'scheduled_date': _TODAY,
            **{f'{name}_location_id': str(place.id) for name, place in places.items()},
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': quantity,
                    **({'item_id': item_id} if item_id else {}),
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    document = created.json()
    done = {
        'lines': [
            {'line_id': line['id'], 'done_quantity': quantity}
            for line in document['lines']
        ]
    }
    for step, body in (('confirm', None), ('complete', done)):
        response = client.patch(
            f'/api/v1/warehouse/documents/{document["id"]}/{step}',
            headers=headers,
            json=body,
        )
        assert response.status_code == status.HTTP_200_OK, response.text


def _receive(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    shelf: StorageLocation,
    other_site: StorageLocation,
    db_session: Session,
    user: User,
) -> None:
    _document(client, headers, 'IN', template, 5, target=shelf)


def _correct(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    shelf: StorageLocation,
    other_site: StorageLocation,
    db_session: Session,
    user: User,
) -> None:
    record = db_session.query(Item).filter(Item.template_id == template.id).one()
    response = client.patch(
        f'/api/v1/items/{record.id}/quantity', headers=headers, json={'quantity': 8}
    )
    assert response.status_code == status.HTTP_200_OK, response.text


def _count(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    shelf: StorageLocation,
    other_site: StorageLocation,
    db_session: Session,
    user: User,
) -> None:
    record = db_session.query(Item).filter(Item.template_id == template.id).one()
    take = StockTake(
        user_id=user.id,
        organization_id=user.organization_id,
        storage_location_id=shelf.id,
        name='Shelf A count',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(take)
    db_session.flush()
    db_session.add(
        StockTakeItem(
            stock_take_id=take.id,
            item_id=record.id,
            item_name=record.name,
            system_quantity=record.quantity,
            counted_quantity=Decimal('8'),
        )
    )
    db_session.commit()
    response = client.post(
        f'/api/v1/stock-takes/{take.id}/complete',
        headers=headers,
        json={'apply_adjustments': True},
    )
    assert response.status_code == status.HTTP_200_OK, response.text


def _transfer(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    shelf: StorageLocation,
    other_site: StorageLocation,
    db_session: Session,
    user: User,
) -> None:
    record = post_on_shelf(client, headers, template, other_site.id, 8)
    _document(
        client,
        headers,
        'INT',
        template,
        8,
        item_id=record['id'],
        source=other_site,
        target=shelf,
    )


@pytest.mark.integration
class TestABackorderKnowsItsStockArrived:
    def test_a_draft_with_nothing_on_the_shelves_is_not_covered(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        user: User,
        template: ProductTemplate,
        warehouse: StorageLocation,
        shelf: StorageLocation,
    ) -> None:
        draft = _draft(db_session, org, user, template, warehouse)

        assert _cover(client, headers, draft) == 'none'

    @pytest.mark.parametrize(
        'raise_stock',
        [_receive, _correct, _count, _transfer],
        ids=['receipt', 'correction', 'stock take', 'transfer'],
    )
    def test_the_state_follows_stock_however_it_rose(
        self,
        raise_stock: Any,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        user: User,
        template: ProductTemplate,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        other_site: StorageLocation,
    ) -> None:
        draft = _draft(db_session, org, user, template, warehouse)
        if raise_stock is not _transfer:
            post_on_shelf(client, headers, template, shelf.id, 3)
            assert _cover(client, headers, draft) == 'partial'
        else:
            assert _cover(client, headers, draft) == 'none'

        raise_stock(client, headers, template, shelf, other_site, db_session, user)

        assert _cover(client, headers, draft) == 'full'

    def test_a_line_that_names_only_a_record_is_read_through_its_product(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        user: User,
        template: ProductTemplate,
        warehouse: StorageLocation,
        shelf: StorageLocation,
    ) -> None:
        record = post_on_shelf(client, headers, template, shelf.id, 8)
        draft = _draft(
            db_session, org, user, template, warehouse, record=UUID(record['id'])
        )

        assert _cover(client, headers, draft) == 'full'

    def test_the_task_of_a_receipt_backorder_has_no_cover_to_report(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        user: User,
        template: ProductTemplate,
        warehouse: StorageLocation,
        shelf: StorageLocation,
    ) -> None:
        post_on_shelf(client, headers, template, shelf.id, 8)
        draft = _draft(db_session, org, user, template, warehouse, doc_type='IN')

        assert _cover(client, headers, draft) is None

    def test_quarantine_shelf_stock_does_not_make_a_draft_ready(
        self,
        client: TestClient,
        headers: dict[str, str],
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        storage_type: StorageType,
        user: User,
        template: ProductTemplate,
        warehouse: StorageLocation,
        shelf: StorageLocation,
    ) -> None:
        quarantine = _place(
            h, db_session, org, storage_type, user, 'Quarantine', warehouse
        )
        named = client.put(
            '/api/v1/warehouse/profile',
            headers=headers,
            json={'quarantine_location_id': str(quarantine.id)},
        )
        assert named.status_code == status.HTTP_200_OK, named.text
        draft = _draft(db_session, org, user, template, warehouse)

        post_on_shelf(client, headers, template, quarantine.id, 8)

        assert _cover(client, headers, draft) == 'none'

    def test_receiving_area_stock_does_not_make_a_draft_ready(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        user: User,
        template: ProductTemplate,
        warehouse: StorageLocation,
        shelf: StorageLocation,
    ) -> None:
        mode = client.put(
            f'/api/v1/warehouse/putaway/receiving-modes/{warehouse.id}',
            headers=headers,
            json={'two_step': True},
        )
        assert mode.status_code == status.HTTP_200_OK, mode.text
        area = UUID(mode.json()['receiving_location_id'])
        draft = _draft(db_session, org, user, template, warehouse)

        post_on_shelf(client, headers, template, area, 8)
        assert _cover(client, headers, draft) == 'none'

        # Put away onto a shelf, the same goods are stock again.
        post_on_shelf(client, headers, template, shelf.id, 8)
        assert _cover(client, headers, draft) == 'full'

    def test_a_quarantined_batch_does_not_make_a_draft_ready(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        org: Organization,
        user: User,
        template: ProductTemplate,
        warehouse: StorageLocation,
        shelf: StorageLocation,
    ) -> None:
        lot = StockLot(
            organization_id=org.id,
            product_template_id=template.id,
            name='LOT-HELD',
            status=LotStatus.QUARANTINED.value,
        )
        db_session.add(lot)
        db_session.commit()
        db_session.refresh(lot)
        draft = _draft(db_session, org, user, template, warehouse)

        async def _put(session: Any) -> None:
            keeper = await shelf_keeper(session, org.id)
            await put_on_shelf(
                session, keeper, template, shelf.id, Decimal('8'), lot_id=lot.id
            )

        run_in_async_session(async_engine_fixture, _put)
        db_session.expire_all()

        assert _cover(client, headers, draft) == 'none'
