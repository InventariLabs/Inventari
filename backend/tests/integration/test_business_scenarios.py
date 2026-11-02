"""
Business scenario integration tests.

Each test represents a realistic end-to-end business workflow executed through
the API.  The primary assertion is always **data consistency** — what the shelf
holds (the records' view) must match Item quantities, reconciliation must
report zero drift, and multi-step operations must leave the database in a
valid state.

These are NOT unit tests — they exercise the full stack: router -> service -> DB.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import post_on_shelf


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


def _shelf_sum(db: Session, org_id, template_id, location_id) -> Decimal:
    """What the shelf holds of the product, every batch together; none is 0."""
    rows = db.scalars(
        select(ShelfRow).where(
            ShelfRow.organization_id == org_id,
            ShelfRow.product_template_id == template_id,
            ShelfRow.storage_location_id == location_id,
        )
    ).all()
    return sum((row.quantity for row in rows), Decimal('0'))


def _item_qty_sum(db: Session, org_id, template_id, location_id) -> Decimal:
    rows = list(
        db.scalars(
            select(Item).where(
                Item.organization_id == org_id,
                Item.template_id == template_id,
                Item.storage_location_id == location_id,
            )
        ).all()
    )
    return sum((i.quantity for i in rows), Decimal('0'))


def _assert_consistency(db: Session, org_id, template_id, location_id):
    sq = _shelf_sum(db, org_id, template_id, location_id)
    iq = _item_qty_sum(db, org_id, template_id, location_id)
    assert sq == iq, (
        f'Shelf drift: shelf={sq}, Item sum={iq} '
        f'(template={template_id}, location={location_id})'
    )


@pytest.fixture
def org(db_session: Session) -> Organization:
    org = Organization(
        name='Scenario Test Org',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
            'purchase_orders',
            'stock_takes',
            'recipes',
            'nutrition',
            'stats',
        ],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def admin(db_session: Session, org: Organization) -> User:
    user = User(
        email='scenario@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Scenario Admin',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def headers(admin: User) -> dict:
    return _auth(admin)


@pytest.fixture
def wh_type(db_session: Session) -> StorageType:
    st = StorageType(name='Warehouse', type_code='WAREHOUSE', behavior_mode='NONE')
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)
    return st


@pytest.fixture
def loc_a(
    db_session: Session, org: Organization, wh_type: StorageType, admin: User
) -> StorageLocation:
    loc = StorageLocation(
        name='Warehouse A',
        organization_id=org.id,
        storage_type_id=wh_type.id,
        created_by=admin.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def loc_b(
    db_session: Session, org: Organization, wh_type: StorageType, admin: User
) -> StorageLocation:
    loc = StorageLocation(
        name='Warehouse B',
        organization_id=org.id,
        storage_type_id=wh_type.id,
        created_by=admin.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def tpl(db_session: Session, org: Organization) -> ProductTemplate:
    t = ProductTemplate(
        name='Widget',
        organization_id=org.id,
        barcode='WIDGET001',
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def seed_item(
    client,
    headers: dict,
    db_session: Session,
    loc_a: StorageLocation,
    tpl: ProductTemplate,
) -> Item:
    """A hundred widgets in location A, put there through POST /items."""
    record = post_on_shelf(client, headers, tpl, loc_a.id, 100)
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


def _create_partner(client, headers, name='Supplier Co', ptype='SUPPLIER'):
    resp = client.post(
        '/api/v1/partners',
        headers=headers,
        json={'name': name, 'type': ptype},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    return resp.json()['id']


def _create_and_complete_receipt(client, headers, loc_id, lines, partner_id=None):
    if partner_id is None:
        partner_id = _create_partner(client, headers)
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': partner_id,
            'target_location_id': str(loc_id),
            'lines': lines,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED
    doc_id = resp.json()['id']

    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK

    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert resp.status_code == status.HTTP_200_OK
    return doc_id


@pytest.mark.integration
@pytest.mark.slow
class TestScenario1ItemLifecycle:
    """
    Business scenario: consume some -> update qty -> discard some.
    Verify the shelf's consistency at every step.
    """

    def test_full_lifecycle(
        self, client, headers, db_session, org, loc_a, tpl, seed_item
    ):
        item_id = seed_item.id
        org_id = org.id
        tid = tpl.id

        _assert_consistency(db_session, org_id, tid, loc_a.id)
        assert _shelf_sum(db_session, org_id, tid, loc_a.id) == Decimal('100')

        # Step 1: consume 20
        resp = client.patch(
            f'/api/v1/items/{item_id}/consume',
            headers=headers,
            json={'quantity': 20},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.flush()
        db_session.expire_all()

        sq_a = _shelf_sum(db_session, org_id, tid, loc_a.id)
        assert sq_a == Decimal('80'), f'After consume: loc_a should be 80, got {sq_a}'

        # Step 2: update quantity to 100 (add 20 back)
        resp = client.patch(
            f'/api/v1/items/{item_id}/quantity',
            headers=headers,
            json={'quantity': 100},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.flush()
        db_session.expire_all()

        sq_a = _shelf_sum(db_session, org_id, tid, loc_a.id)
        assert sq_a == Decimal('100'), (
            f'After qty update: loc_a should be 100, got {sq_a}'
        )

        # Step 3: discard 30
        resp = client.patch(
            f'/api/v1/items/{item_id}/discard',
            headers=headers,
            json={'quantity': 30, 'reason': 'damaged'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.flush()
        db_session.expire_all()

        sq_a = _shelf_sum(db_session, org_id, tid, loc_a.id)
        assert sq_a == Decimal('70'), f'After discard: loc_a should be 70, got {sq_a}'

        _assert_consistency(db_session, org_id, tid, loc_a.id)


@pytest.mark.integration
@pytest.mark.slow
class TestScenario2PurchaseOrderFlow:
    """
    Business scenario: create PO -> confirm -> create receipt -> complete ->
    verify stock increased and PO tracking correct.
    """

    def test_po_to_receipt(self, client, headers, db_session, org, loc_a, tpl):
        partner_id = _create_partner(client, headers)

        # Step 1: Create PO
        resp = client.post(
            '/api/v1/purchase-orders',
            headers=headers,
            json={
                'partner_id': partner_id,
                'lines': [
                    {
                        'product_template_id': str(tpl.id),
                        'quantity_ordered': 50,
                        'unit_price': 10.00,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        po_id = resp.json()['id']
        assert resp.json()['status'] == 'DRAFT'

        # Step 2: Confirm PO
        resp = client.post(
            f'/api/v1/purchase-orders/{po_id}/confirm',
            headers=headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'CONFIRMED'

        # Step 3: Get PO lines to find po_line_id
        resp = client.get(
            f'/api/v1/purchase-orders/{po_id}',
            headers=headers,
        )
        po_lines = resp.json()['lines']
        po_line_id = po_lines[0]['id']

        # Step 4: Create receipt from PO
        resp = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=headers,
            json={
                'target_location_id': str(loc_a.id),
                'lines': [
                    {
                        'po_line_id': po_line_id,
                        'quantity': 50,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']

        # Step 5: Receipt from PO is already confirmed, just complete it
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK

        db_session.flush()
        db_session.expire_all()

        sq = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq == Decimal('50'), f'After receipt: the shelf should hold 50, got {sq}'

        iq = _item_qty_sum(db_session, org.id, tpl.id, loc_a.id)
        assert iq == Decimal('50'), f'After receipt: Item sum should be 50, got {iq}'

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)

        # Verify PO is COMPLETED
        resp = client.get(f'/api/v1/purchase-orders/{po_id}', headers=headers)
        assert resp.json()['status'] == 'COMPLETED'


@pytest.mark.integration
@pytest.mark.slow
class TestScenario3DispatchWithReservation:
    """
    Business scenario: have stock -> create OUT doc -> confirm (reserves stock)
    -> complete (dispatches) -> verify reservation released and stock correct.
    """

    def test_dispatch_reservation_lifecycle(
        self, client, headers, db_session, org, loc_a, tpl, seed_item
    ):
        partner_id = _create_partner(
            client, headers, name='Customer Inc', ptype='CUSTOMER'
        )

        sq = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq == Decimal('100')

        # Step 1: Create OUT document
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'OUT',
                'partner_id': partner_id,
                'source_location_id': str(loc_a.id),
                'lines': [
                    {
                        'item_id': str(seed_item.id),
                        'product_template_id': str(tpl.id),
                        'expected_quantity': 40,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']

        # Step 2: Confirm -> should reserve 40
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.flush()
        db_session.expire_all()

        sq_row = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == org.id,
                ShelfRow.product_template_id == tpl.id,
                ShelfRow.storage_location_id == loc_a.id,
            )
        ).first()
        assert sq_row.reserved_quantity == Decimal('40'), (
            f'After confirm: reserved should be 40, got {sq_row.reserved_quantity}'
        )
        assert sq_row.quantity == Decimal('100')

        # Step 3: Complete -> dispatch 40
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.flush()
        db_session.expire_all()

        sq_row = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == org.id,
                ShelfRow.product_template_id == tpl.id,
                ShelfRow.storage_location_id == loc_a.id,
            )
        ).first()
        assert sq_row.quantity == Decimal('60'), (
            f'After dispatch: qty should be 60, got {sq_row.quantity}'
        )
        assert sq_row.reserved_quantity == Decimal('0'), (
            f'After dispatch: reserved should be 0, got {sq_row.reserved_quantity}'
        )

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)


@pytest.mark.integration
@pytest.mark.slow
class TestScenario4TransferZeroSum:
    """
    Business scenario: stock in A -> transfer 25 to B via INT document
    -> verify zero-sum (total stock unchanged).
    """

    def test_transfer_conservation(
        self, client, headers, db_session, org, loc_a, loc_b, tpl, seed_item
    ):
        total_before = _shelf_sum(db_session, org.id, tpl.id, loc_a.id) + _shelf_sum(
            db_session, org.id, tpl.id, loc_b.id
        )
        assert total_before == Decimal('100')

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'INT',
                'source_location_id': str(loc_a.id),
                'target_location_id': str(loc_b.id),
                'lines': [
                    {
                        'item_id': str(seed_item.id),
                        'product_template_id': str(tpl.id),
                        'expected_quantity': 100,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        )
        assert resp.status_code == status.HTTP_200_OK

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK

        db_session.flush()
        db_session.expire_all()

        sq_a = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        sq_b = _shelf_sum(db_session, org.id, tpl.id, loc_b.id)

        assert sq_a == Decimal('0'), f'Source after transfer: expected 0, got {sq_a}'
        assert sq_b == Decimal('100'), (
            f'Target after transfer: expected 100, got {sq_b}'
        )

        total_after = sq_a + sq_b
        assert total_after == total_before, (
            f'Zero-sum violated: before={total_before}, after={total_after}'
        )

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)
        _assert_consistency(db_session, org.id, tpl.id, loc_b.id)


@pytest.mark.integration
@pytest.mark.slow
class TestScenario5StockTakeAdjustment:
    """
    Business scenario: item exists -> stock take finds discrepancy -> finalize
    with adjustment -> verify Item.quantity matches counted value and the shelf
    is consistent.
    """

    def test_stock_take_adjusts_quantities(
        self, client, headers, db_session, org, loc_a, tpl, seed_item
    ):
        # Baseline: 100 units of seed_item in loc_a
        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)

        # Create stock take
        resp = client.post(
            '/api/v1/stock-takes',
            headers=headers,
            json={
                'name': 'Annual Count',
                'location_id': str(loc_a.id),
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        st_id = resp.json()['id']

        # Get items in stock take
        resp = client.get(
            f'/api/v1/stock-takes/{st_id}/items',
            headers=headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        st_items = resp.json()['items']
        assert len(st_items) >= 1

        # Count with discrepancy: system=100, counted=95
        st_item = st_items[0]
        resp = client.patch(
            f'/api/v1/stock-takes/{st_id}/items/{st_item["id"]}/count',
            headers=headers,
            json={'counted_quantity': 95},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        # Finalize with adjustments
        resp = client.post(
            f'/api/v1/stock-takes/{st_id}/complete',
            headers=headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.flush()
        db_session.expire_all()

        db_session.refresh(seed_item)
        assert seed_item.quantity == Decimal('95'), (
            f'Item after adjustment: expected 95, got {seed_item.quantity}'
        )

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)


@pytest.mark.integration
@pytest.mark.slow
class TestScenario6MultiOperationReconciliation:
    """
    Business scenario: run multiple stock-changing operations, then verify
    the reconciliation endpoint reports zero drift and the shelf is consistent.
    """

    def test_reconciliation_after_mixed_ops(
        self, client, headers, db_session, org, loc_a, tpl, seed_item
    ):
        # Op 1: consume 10
        resp = client.patch(
            f'/api/v1/items/{seed_item.id}/consume',
            headers=headers,
            json={'quantity': 10},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        # Op 2: Receipt via document +30
        _create_and_complete_receipt(
            client,
            headers,
            loc_a.id,
            [{'product_template_id': str(tpl.id), 'expected_quantity': 30}],
        )

        # Op 3: Discard 5
        resp = client.patch(
            f'/api/v1/items/{seed_item.id}/discard',
            headers=headers,
            json={'quantity': 5, 'reason': 'damaged'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Expected: 100 - 10 + 30 - 5 = 115
        sq = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq == Decimal('115'), f'Expected 115, got {sq}'

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)

        # Check reconciliation endpoint
        resp = client.get('/api/v1/stats/reconciliation', headers=headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()

        # The pairs the report still measures: the shelf against the ledger,
        # and the cost layers against the shelf.
        assert data['quant_move_drift_count'] == 0, data
        assert data['layer_quant_drift_count'] == 0, data


@pytest.mark.integration
@pytest.mark.slow
class TestScenario7ReceiptThenCorrection:
    """
    Business scenario: receipt 50 units -> correct to 45 -> verify adjusted stock.
    """

    def test_receipt_then_correction(
        self, client, headers, db_session, org, loc_a, tpl
    ):
        # Step 1: Receipt 50 units
        doc_id = _create_and_complete_receipt(
            client,
            headers,
            loc_a.id,
            [{'product_template_id': str(tpl.id), 'expected_quantity': 50}],
        )

        db_session.flush()
        db_session.expire_all()
        assert _shelf_sum(db_session, org.id, tpl.id, loc_a.id) == Decimal('50')

        # Step 2: Create correction for -5
        resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=headers,
            json={
                'corrects_document_id': doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': 1,
                        'quantity_delta': -5,
                    }
                ],
                'notes': 'Scenario correction',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        correction_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/confirm', headers=headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        resp = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        sq = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq == Decimal('45'), f'After correction: expected 45, got {sq}'

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)


@pytest.mark.integration
@pytest.mark.slow
class TestScenario3bDispatchItemOnly:
    """
    Dispatch referencing only item_id (no product_template_id on the line).
    The stock must leave once: the dispatch used to risk a second, manual
    decrement beside the one the record's own card drives.

    In practice, the document_line_resolver populates product_template_id from
    the item, so this path is exercised but the executor still sees the field.
    """

    def test_dispatch_without_product_template_on_line(
        self, client, headers, db_session, org, loc_a, tpl, seed_item
    ):
        partner_id = _create_partner(
            client, headers, name='Customer B', ptype='CUSTOMER'
        )

        sq = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq == Decimal('100')

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'OUT',
                'partner_id': partner_id,
                'source_location_id': str(loc_a.id),
                'lines': [
                    {
                        'item_id': str(seed_item.id),
                        'expected_quantity': 30,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.flush()
        db_session.expire_all()

        sq_a = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq_a == Decimal('70'), f'After dispatch: loc_a should be 70, got {sq_a}'

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)


@pytest.mark.integration
@pytest.mark.slow
class TestScenario8ReceiptOnExistingItem:
    """
    Receipt that adds stock to an item already at the target location.
    Exercises the update_quantity_sync path in _receive_item — previously
    caused a double increment of the shelf.
    """

    def test_receipt_adds_to_existing_item(
        self, client, headers, db_session, org, loc_a, tpl, seed_item
    ):
        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)
        assert _shelf_sum(db_session, org.id, tpl.id, loc_a.id) == Decimal('100')

        partner_id = _create_partner(client, headers)

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'IN',
                'partner_id': partner_id,
                'target_location_id': str(loc_a.id),
                'lines': [
                    {
                        'item_id': str(seed_item.id),
                        'product_template_id': str(tpl.id),
                        'expected_quantity': 25,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        )
        assert resp.status_code == status.HTTP_200_OK

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK

        db_session.flush()
        db_session.expire_all()

        sq = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq == Decimal('125'), f'After receipt: expected 125, got {sq}'

        db_session.refresh(seed_item)
        assert seed_item.quantity == Decimal('125'), (
            f'Item quantity: expected 125, got {seed_item.quantity}'
        )

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)


@pytest.mark.integration
@pytest.mark.slow
class TestScenario7bPositiveCorrection:
    """
    Positive correction on an IN receipt: received 50 but actually it was 55.
    Exercises the delta > 0 branch in _execute_correction.
    """

    def test_positive_correction_on_receipt(
        self, client, headers, db_session, org, loc_a, tpl
    ):
        doc_id = _create_and_complete_receipt(
            client,
            headers,
            loc_a.id,
            [{'product_template_id': str(tpl.id), 'expected_quantity': 50}],
        )

        db_session.flush()
        db_session.expire_all()
        assert _shelf_sum(db_session, org.id, tpl.id, loc_a.id) == Decimal('50')

        resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=headers,
            json={
                'corrects_document_id': doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': 1,
                        'quantity_delta': 5,
                    }
                ],
                'notes': 'Scenario correction',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        correction_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/confirm', headers=headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        resp = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        sq = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq == Decimal('55'), f'After positive correction: expected 55, got {sq}'

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)


@pytest.mark.integration
@pytest.mark.slow
class TestScenario9CorrectionOnDispatch:
    """
    Correction on an OUT document: dispatched 40 but actually only 35 left.
    Negative delta reverses part of the dispatch — stock should increase by 5.
    """

    def test_correction_on_out_document(
        self, client, headers, db_session, org, loc_a, tpl, seed_item
    ):
        partner_id = _create_partner(
            client, headers, name='Customer C', ptype='CUSTOMER'
        )

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'OUT',
                'partner_id': partner_id,
                'source_location_id': str(loc_a.id),
                'lines': [
                    {
                        'item_id': str(seed_item.id),
                        'product_template_id': str(tpl.id),
                        'expected_quantity': 40,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        out_doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{out_doc_id}/confirm', headers=headers
        )
        assert resp.status_code == status.HTTP_200_OK

        resp = client.patch(
            f'/api/v1/warehouse/documents/{out_doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK
        db_session.flush()
        db_session.expire_all()

        sq = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq == Decimal('60'), f'After dispatch: expected 60, got {sq}'

        resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=headers,
            json={
                'corrects_document_id': out_doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': 1,
                        'quantity_delta': -5,
                    }
                ],
                'notes': 'Scenario correction',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        correction_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/confirm', headers=headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        resp = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        sq = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq == Decimal('65'), f'After dispatch correction: expected 65, got {sq}'

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)


@pytest.mark.integration
@pytest.mark.slow
class TestScenario10ScrapDocument:
    """
    SCRAP document: remove 15 units from stock.
    Exercises _scrap_item which previously had double decrement.
    """

    def test_scrap_removes_stock(
        self, client, headers, db_session, org, loc_a, tpl, seed_item
    ):
        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)
        assert _shelf_sum(db_session, org.id, tpl.id, loc_a.id) == Decimal('100')

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'source_location_id': str(loc_a.id),
                'lines': [
                    {
                        'item_id': str(seed_item.id),
                        'product_template_id': str(tpl.id),
                        'expected_quantity': 15,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        )
        assert resp.status_code == status.HTTP_200_OK

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK

        db_session.flush()
        db_session.expire_all()

        sq = _shelf_sum(db_session, org.id, tpl.id, loc_a.id)
        assert sq == Decimal('85'), f'After scrap: expected 85, got {sq}'

        db_session.refresh(seed_item)
        assert seed_item.quantity == Decimal('85'), (
            f'Item quantity: expected 85, got {seed_item.quantity}'
        )

        _assert_consistency(db_session, org.id, tpl.id, loc_a.id)
