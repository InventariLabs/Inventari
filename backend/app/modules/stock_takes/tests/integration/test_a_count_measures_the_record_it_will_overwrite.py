"""A count is taken against the number the posting will overwrite.

The snapshot reads ``Item.quantity`` — the record's own number. Follow the
count all the way through and it is the only source that fits: the staleness
guard re-reads ``Item.quantity`` and refuses the finalization when it has
moved, and the posting writes ``Item.quantity`` — the number the variance is
stated against, so a snapshot taken anywhere else would ask a counter to
explain a gap the correction does not close.

What the count settles was looked at twice. A group of stock is shared by
every item row of the product standing on the shelf, so writing the counted
figure straight onto the group would wipe what the rows nobody counted
contribute.

So the count measures on the records — the state — and settles them: every
row it covered lands on what the counter saw, a row nobody counted keeps its
own, and the difference those rows made is posted as a movement naming the
count, under the stock lock. The count never reads the movement ledger: a gap
the ledger was already carrying travels with it, and the reconciliation
report measures it.

These tests hold the source, the settlement, and the report afterwards.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records, post_on_shelf


@pytest.fixture
def drift_org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Drift Count Org',
        ['core', 'items', 'locations', 'categories', 'stock_takes', 'stats'],
    )


@pytest.fixture
def drift_user(db_session: Session, drift_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        drift_org, email='drift-counter@example.com'
    )


@pytest.fixture
def drift_headers(db_session: Session, drift_user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(drift_user)


@pytest.fixture
def drift_location(
    db_session: Session, drift_org: Organization, drift_user: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Drift Warehouse', 'DRIFT_WAREHOUSE', organization_id=drift_org.id
    )
    return h.create_storage_location(
        drift_org, storage_type, drift_user, name='Drifted Warehouse'
    )


@pytest.fixture
def drift_template(db_session: Session, drift_org: Organization) -> ProductTemplate:
    return ModuleTestHelper(db_session).create_template(drift_org, name='Drifted Goods')


@pytest.fixture
def drift_elsewhere(
    db_session: Session, drift_org: Organization, drift_user: User
) -> StorageLocation:
    """A shelf outside the counted tree, for stock that walks away mid-count."""
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Another Warehouse', 'ANOTHER_WAREHOUSE', organization_id=drift_org.id
    )
    return h.create_storage_location(
        drift_org, storage_type, drift_user, name='Another Warehouse'
    )


def _a_row(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    location_id: UUID,
    *,
    quantity: Decimal,
    name: str,
) -> Item:
    """One record of the product, standing on the shelf."""
    item = Item(
        name=name,
        organization_id=org_id,
        template_id=template_id,
        storage_location_id=location_id,
        quantity=quantity,
    )
    db_session.add(item)
    anchor_pending_records(db_session)
    db_session.flush()
    db_session.refresh(item)
    return item


def _the_shelf_on(
    db_session: Session, template_id: UUID, location_id: UUID
) -> ShelfRow:
    return db_session.scalars(
        select(ShelfRow).where(
            ShelfRow.product_template_id == template_id,
            ShelfRow.storage_location_id == location_id,
        )
    ).one()


def _on_hand_on(db_session: Session, template_id: UUID, location_id: UUID) -> Decimal:
    """What the records say stands on the shelf — the number readers ask for."""
    rows = db_session.execute(
        select(stock_quants_from_records.c.quantity).where(
            stock_quants_from_records.c.product_template_id == template_id,
            stock_quants_from_records.c.storage_location_id == location_id,
        )
    ).all()
    return sum((Decimal(str(row[0])) for row in rows), Decimal('0'))


def _open_a_count(
    client: TestClient,
    headers: dict[str, str],
    location_id: UUID,
    *,
    name: str,
    require_full_count: bool = True,
) -> dict[str, Any]:
    created = client.post(
        '/api/v1/stock-takes',
        headers=headers,
        json={
            'name': name,
            'location_id': str(location_id),
            'require_full_count': require_full_count,
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    payload: dict[str, Any] = created.json()
    return payload


def _count_row(
    client: TestClient,
    headers: dict[str, str],
    take_id: str,
    row_id: str,
    counted: str,
) -> None:
    response = client.patch(
        f'/api/v1/stock-takes/{take_id}/items/{row_id}/count',
        headers=headers,
        json={'counted_quantity': counted},
    )
    assert response.status_code == status.HTTP_200_OK, response.text


def _finalize(client: TestClient, headers: dict[str, str], take_id: str) -> None:
    done = client.post(
        f'/api/v1/stock-takes/{take_id}/complete',
        headers=headers,
        json={'apply_adjustments': True},
    )
    assert done.status_code == status.HTTP_200_OK, done.text


@pytest.mark.integration
class TestTheSnapshotSourceIsTheOneThePostingWrites:
    def test_the_snapshot_reads_the_record(
        self,
        client: TestClient,
        db_session: Session,
        drift_org: Organization,
        drift_user: User,
        drift_headers: dict[str, str],
        drift_location: StorageLocation,
        drift_template: ProductTemplate,
    ) -> None:
        _a_row(
            db_session,
            drift_org.id,
            drift_template.id,
            drift_location.id,
            quantity=Decimal('7'),
            name='Drifted Goods',
        )
        db_session.commit()

        created = client.post(
            '/api/v1/stock-takes',
            headers=drift_headers,
            json={
                'name': 'Count over a drifted shelf',
                'location_id': str(drift_location.id),
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        rows = client.get(
            f'/api/v1/stock-takes/{created.json()["id"]}/items',
            headers=drift_headers,
        )
        assert rows.status_code == status.HTTP_200_OK, rows.text
        [row] = rows.json()['items']
        # Seven, from the record — the number the finalization overwrites and
        # the number the staleness guard re-reads.
        assert Decimal(str(row['system_quantity'])) == Decimal('7')

    def test_a_count_settles_the_shelf_on_what_was_counted(
        self,
        client: TestClient,
        db_session: Session,
        drift_org: Organization,
        drift_user: User,
        drift_headers: dict[str, str],
        drift_location: StorageLocation,
        drift_template: ProductTemplate,
    ) -> None:
        """The record and the shelf end on the same number: five.

        A shelf whose record said seven, counted at five. The count measures
        on the records and writes the record; the bridge writes the same two
        as the movement beside it.
        """
        item = _a_row(
            db_session,
            drift_org.id,
            drift_template.id,
            drift_location.id,
            quantity=Decimal('7'),
            name='Drifted Goods',
        )
        db_session.commit()
        item_id = item.id

        take = _open_a_count(
            client,
            drift_headers,
            drift_location.id,
            name='Count that settles the shelf',
        )
        rows = client.get(
            f'/api/v1/stock-takes/{take["id"]}/items', headers=drift_headers
        )
        _count_row(
            client, drift_headers, take['id'], rows.json()['items'][0]['id'], '5'
        )
        _finalize(client, drift_headers, take['id'])

        db_session.expire_all()
        record = db_session.get(Item, item_id)
        assert record is not None

        # What the counter saw is what the record now says, and the shelf
        # with it.
        assert record.quantity == Decimal('5.000')
        assert _on_hand_on(db_session, drift_template.id, drift_location.id) == Decimal(
            '5.000'
        )
        # The two the record was over are posted as one movement naming the
        # count — the ledger says where they went.
        movements = db_session.scalars(
            select(StockMove).where(StockMove.organization_id == drift_org.id)
        ).all()
        assert len(movements) == 1
        assert movements[0].reference_type == 'adjustment'
        assert movements[0].quantity == Decimal('2')


@pytest.mark.integration
class TestTheShelfIsSettledOnTheCountedNumber:
    def test_a_row_nobody_counted_keeps_its_stock(
        self,
        client: TestClient,
        db_session: Session,
        drift_org: Organization,
        drift_user: User,
        drift_headers: dict[str, str],
        drift_location: StorageLocation,
        drift_template: ProductTemplate,
    ) -> None:
        """Two records in one group, one of them counted.

        The records say seven and four. The counter counts the first row at
        five and never looks at the second, which is an ordinary partial
        count.

        The shelf's number is then the five that were counted plus the four
        the other row's record still claims — nine, which is also what the
        records now add up to. Nobody's row is wiped.
        """
        first = _a_row(
            db_session,
            drift_org.id,
            drift_template.id,
            drift_location.id,
            quantity=Decimal('7'),
            name='Counted row',
        )
        second = _a_row(
            db_session,
            drift_org.id,
            drift_template.id,
            drift_location.id,
            quantity=Decimal('4'),
            name='Row nobody looked at',
        )
        db_session.commit()

        take = _open_a_count(
            client,
            drift_headers,
            drift_location.id,
            name='A partial count of a short shelf',
            require_full_count=False,
        )
        rows = client.get(
            f'/api/v1/stock-takes/{take["id"]}/items', headers=drift_headers
        )
        by_item = {row['item_id']: row for row in rows.json()['items']}
        _count_row(client, drift_headers, take['id'], by_item[str(first.id)]['id'], '5')
        _finalize(client, drift_headers, take['id'])

        db_session.expire_all()
        counted = db_session.get(Item, first.id)
        untouched = db_session.get(Item, second.id)
        assert counted is not None and untouched is not None
        on_hand = _on_hand_on(db_session, drift_template.id, drift_location.id)

        assert counted.quantity == Decimal('5.000')
        # The row nobody counted was not written to and not wiped.
        assert untouched.quantity == Decimal('4.000')
        # Counted five, plus the four the other record claims: the shelf's
        # number is what the records give, which is the side the count is on.
        assert on_hand == Decimal('9.000')
        assert on_hand == counted.quantity + untouched.quantity

    def test_the_count_leaves_a_mismatch_it_never_read(
        self,
        client: TestClient,
        db_session: Session,
        drift_org: Organization,
        drift_user: User,
        drift_headers: dict[str, str],
        drift_location: StorageLocation,
        drift_template: ProductTemplate,
    ) -> None:
        """The ledger pair still reports what the count was never allowed to see.

        The shelf starts seven apart from its movement ledger — a record of
        seven with no movement behind it — and the report says so before
        anybody counts. The count is taken at five: the record lands there,
        the ledger takes the same two as a movement, and the pair still
        reports seven, because a count that settles on the records reads no
        ledger to cure one with. The gap is there to be seen, not papered
        over by the next operation that passes.
        """
        _a_row(
            db_session,
            drift_org.id,
            drift_template.id,
            drift_location.id,
            quantity=Decimal('7'),
            name='Drifted Goods',
        )
        db_session.commit()

        before = client.get('/api/v1/stats/reconciliation', headers=drift_headers)
        assert before.status_code == status.HTTP_200_OK, before.text
        assert before.json()['quant_move_drift_count'] == 1
        assert Decimal(str(before.json()['quant_move_drift_total'])) == Decimal('7')

        take = _open_a_count(
            client,
            drift_headers,
            drift_location.id,
            name='Count over a drifted shelf',
        )
        rows = client.get(
            f'/api/v1/stock-takes/{take["id"]}/items', headers=drift_headers
        )
        _count_row(
            client, drift_headers, take['id'], rows.json()['items'][0]['id'], '5'
        )
        _finalize(client, drift_headers, take['id'])

        after = client.get('/api/v1/stats/reconciliation', headers=drift_headers)
        assert after.status_code == status.HTTP_200_OK, after.text
        # The same seven, unchanged: both sides moved together and the count
        # left a mismatch it could not read exactly where it was.
        assert after.json()['quant_move_drift_count'] == 1
        assert Decimal(str(after.json()['quant_move_drift_total'])) == Decimal('7')

    def test_a_row_whose_item_left_the_shelf_is_posted_where_it_went(
        self,
        client: TestClient,
        db_session: Session,
        drift_org: Organization,
        drift_user: User,
        drift_headers: dict[str, str],
        drift_location: StorageLocation,
        drift_template: ProductTemplate,
        drift_elsewhere: StorageLocation,
    ) -> None:
        """A shelf settles the rows standing on it, and only those.

        One record stands on the counted shelf, is counted, and is moved to
        another shelf before anybody finalizes. Its quantity never changed,
        so the staleness guard lets it through — the count is still a
        statement about goods that are somewhere.

        That row is not the counted shelf's to settle any more. Its
        difference belongs wherever the item stands now, so it keeps the
        per-item path: the counted shelf is left where the move put it, and
        the record and the shelf at the far end end on the counted number
        together.
        """
        record = post_on_shelf(
            client, drift_headers, drift_template, drift_location.id, 7
        )
        item_id = UUID(record['id'])

        take = _open_a_count(
            client, drift_headers, drift_location.id, name='Count of a shelf'
        )
        rows = client.get(
            f'/api/v1/stock-takes/{take["id"]}/items', headers=drift_headers
        )
        _count_row(
            client, drift_headers, take['id'], rows.json()['items'][0]['id'], '5'
        )

        moved = client.patch(
            f'/api/v1/items/{item_id}/move',
            headers=drift_headers,
            json={'to_location_id': str(drift_elsewhere.id)},
        )
        assert moved.status_code == status.HTTP_200_OK, moved.text

        _finalize(client, drift_headers, take['id'])

        db_session.expire_all()
        moved_record = db_session.get(Item, item_id)
        assert moved_record is not None
        assert moved_record.storage_location_id == drift_elsewhere.id
        # The record and the shelf it stands on now both hold the counted
        # number: the difference was posted where the item went.
        assert moved_record.quantity == Decimal('5.000')
        assert _the_shelf_on(
            db_session, drift_template.id, drift_elsewhere.id
        ).quantity == Decimal('5.000')
