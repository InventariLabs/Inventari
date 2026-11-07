"""To do shows what waits on a person, not only what waits on the floor.

Three kinds of work are nobody's next action until somebody decides: the
backorder draft a short completion leaves behind, a document parked for
approval, and goods held in quarantine. All three existed and all three were
reachable from elsewhere, so the person who opens To do to see the day's work
never learned they were there.

The block is read-only: it names each decision and where it is taken. Nothing
is confirmed, approved or released by reading the queue — the tests here also
watch that the draft, the request and the batch are still waiting afterwards.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.approvals.models import ApprovalWorkflow
from tests.integration._shelf import put_on_shelf, run_in_async_session, shelf_keeper

_TODAY = date.today().isoformat()


@pytest.fixture
def doc_quarantine_location(
    h: ModuleTestHelper,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        doc_org, doc_storage_type, doc_user, name='Quarantine shelf'
    )


def _todo(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get(
        '/api/v1/warehouse/todo',
        headers=headers,
        params={'date_to': _TODAY, 'limit': 50},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(dict[str, Any], response.json())


def _decisions(todo: dict[str, Any], kind: str) -> dict[str, Any]:
    return cast(dict[str, Any], todo['decisions'][kind])


def _decision(todo: dict[str, Any], kind: str, item_id: str) -> dict[str, Any]:
    for item in _decisions(todo, kind)['items']:
        identifier = item.get('id') or item.get('lot_id')
        if identifier == item_id:
            return cast(dict[str, Any], item)
    raise AssertionError(f'{item_id} is not under decisions.{kind}: {todo}')


def _receipt_hold(todo: dict[str, Any], document_id: str) -> dict[str, Any]:
    for item in _decisions(todo, 'quarantine')['items']:
        if item.get('document_id') == document_id:
            return cast(dict[str, Any], item)
    raise AssertionError(f'{document_id} is not under decisions.quarantine: {todo}')


def _name_quarantine_shelf(
    client: TestClient, headers: dict[str, str], shelf: StorageLocation
) -> None:
    response = client.put(
        '/api/v1/warehouse/profile',
        headers=headers,
        json={'quarantine_location_id': str(shelf.id)},
    )
    assert response.status_code == status.HTTP_200_OK, response.text


def _stock_rows(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    location: StorageLocation,
) -> list[dict[str, Any]]:
    response = client.get(
        '/api/v1/stock-quants',
        headers=headers,
        params={
            'product_template_id': str(template.id),
            'location_id': str(location.id),
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(list[dict[str, Any]], response.json()['items'])


def _create_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    doc_type: str,
    partner_id: str,
    target_location_id: str,
    template_id: str,
    quantity: str,
    unit_price: str | None = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    line: dict[str, Any] = {
        'product_template_id': template_id,
        'expected_quantity': quantity,
    }
    if item_id is not None:
        line['item_id'] = item_id
    if unit_price is not None:
        line['unit_price'] = unit_price
    response = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': doc_type,
            'partner_id': partner_id,
            'target_location_id': target_location_id,
            'scheduled_date': _TODAY,
            'lines': [line],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return cast(dict[str, Any], response.json())


def _complete_short(
    client: TestClient, headers: dict[str, str], document: dict[str, Any]
) -> None:
    doc_id = document['id']
    line = document['lines'][0]
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    completed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={
            'lines': [
                {
                    'line_id': line['id'],
                    'done_quantity': 1,
                    'discrepancy_code': 'SHORTAGE',
                    'discrepancy_reason': 'Two boxes stayed on the truck',
                }
            ]
        },
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text


def _backorder_for(
    client: TestClient, headers: dict[str, str], origin_id: str
) -> dict[str, Any]:
    listed = client.get('/api/v1/warehouse/documents', headers=headers)
    assert listed.status_code == status.HTTP_200_OK, listed.text
    matches = [
        doc for doc in listed.json()['items'] if doc.get('backorder_id') == origin_id
    ]
    assert len(matches) == 1, matches
    return cast(dict[str, Any], matches[0])


def _set_threshold(client: TestClient, headers: dict[str, str], threshold: str) -> None:
    profile = client.get('/api/v1/warehouse/profile', headers=headers)
    assert profile.status_code == status.HTTP_200_OK, profile.text
    stored = profile.json()
    response = client.put(
        '/api/v1/warehouse/profile',
        headers=headers,
        json={
            **{
                key: value
                for key, value in stored.items()
                if key not in ('id', 'organization_id', 'created_at', 'updated_at')
            },
            'approval_threshold': threshold,
            'approval_required_for_types': [],
            'value_tracking_enabled': True,
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text


@pytest.mark.integration
class TestTheTodoQueueAsksForDecisions:
    def test_a_short_completion_leaves_a_draft_to_confirm_or_cancel(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        origin = _create_document(
            client,
            doc_auth_headers,
            doc_type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            template_id=str(doc_template.id),
            item_id=str(doc_stock_item.id),
            quantity='3',
        )
        _complete_short(client, doc_auth_headers, origin)
        draft = _backorder_for(client, doc_auth_headers, origin['id'])
        completed_origin = client.get(
            f'/api/v1/warehouse/documents/{origin["id"]}', headers=doc_auth_headers
        ).json()

        todo = _todo(client, doc_auth_headers)

        item = _decision(todo, 'backorders', draft['id'])
        assert item['number'].startswith('DRAFT-')
        assert item['status'] == 'DRAFT'
        # The draft names the receipt it continues, by number, and the two
        # units still owed.
        assert item['backorder_id'] == origin['id']
        assert item['backorder_of_number'] == completed_origin['number']
        assert Decimal(item['lines'][0]['expected_quantity']) == Decimal('2')
        assert _decisions(todo, 'backorders')['total'] == 1
        assert todo['inbound']['total'] == 0
        assert todo['outbound']['total'] == 0

        # Reading the queue is not a decision.
        still_draft = client.get(
            f'/api/v1/warehouse/documents/{draft["id"]}', headers=doc_auth_headers
        )
        assert still_draft.status_code == status.HTTP_200_OK
        assert still_draft.json()['status'] == 'DRAFT'

        # Both decisions the block points at are the document's own:
        # confirming it takes it out of the block, and cancelling another one
        # does the same.
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{draft["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        assert _decisions(_todo(client, doc_auth_headers), 'backorders')['total'] == 0

    def test_a_document_waiting_for_approval_is_a_decision(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        _set_threshold(client, doc_auth_headers, '100.00')
        document = _create_document(
            client,
            doc_auth_headers,
            doc_type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            template_id=str(doc_template.id),
            item_id=str(doc_stock_item.id),
            quantity='5',
            unit_price='50.00',
        )
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{document["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        assert confirmed.json()['status'] == 'PENDING_APPROVAL'

        todo = _todo(client, doc_auth_headers)

        item = _decision(todo, 'approvals', document['id'])
        assert item['status'] == 'PENDING_APPROVAL'
        assert _decisions(todo, 'approvals')['total'] == 1

        # Reading the queue approved nothing.
        still_waiting = client.get(
            f'/api/v1/warehouse/documents/{document["id"]}', headers=doc_auth_headers
        )
        assert still_waiting.json()['status'] == 'PENDING_APPROVAL'

        approved = client.post(
            f'/api/v1/approvals/documents/{document["id"]}/approve',
            headers=doc_auth_headers,
        )
        assert approved.status_code == status.HTTP_200_OK, approved.text
        assert _decisions(_todo(client, doc_auth_headers), 'approvals')['total'] == 0

    def test_an_organization_with_no_modules_listed_still_has_its_approvals(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        """An empty module list reads as every default module, here as well.

        The To do used to test the list itself, so an organization that kept
        the defaults had its approvals module on for every other screen and
        off for the decisions block.
        """
        _set_threshold(client, doc_auth_headers, '100.00')
        document = _create_document(
            client,
            doc_auth_headers,
            doc_type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            template_id=str(doc_template.id),
            item_id=str(doc_stock_item.id),
            quantity='5',
            unit_price='50.00',
        )
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{document["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.json()['status'] == 'PENDING_APPROVAL', confirmed.text

        from app.database import SessionLocal

        original = list(doc_org.enabled_modules or [])
        with SessionLocal() as other:
            synced = other.get(Organization, doc_org.id)
            assert synced is not None
            synced.enabled_modules = []
            other.commit()
        try:
            todo = _todo(client, doc_auth_headers)
            _decision(todo, 'approvals', document['id'])
            assert _decisions(todo, 'approvals')['total'] == 1
        finally:
            with SessionLocal() as other:
                synced = other.get(Organization, doc_org.id)
                if synced is not None:
                    synced.enabled_modules = original
                    other.commit()

    def test_a_quarantined_batch_is_a_decision(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
    ) -> None:
        lot = StockLot(
            organization_id=doc_org.id,
            product_template_id=doc_template.id,
            name='LOT-41/26',
            status=LotStatus.QUARANTINED.value,
            meta_data={
                'status_history': [
                    {
                        'status': LotStatus.QUARANTINED.value,
                        'reason': 'Supplier notice 41/26',
                    }
                ]
            },
        )
        db_session.add(lot)
        db_session.commit()
        db_session.refresh(lot)

        async def _put(session: Any) -> None:
            keeper = await shelf_keeper(session, doc_org.id)
            await put_on_shelf(
                session,
                keeper,
                doc_template,
                doc_source_location.id,
                Decimal('8'),
                lot_id=lot.id,
            )

        run_in_async_session(async_engine_fixture, _put)
        db_session.expire_all()

        todo = _todo(client, doc_auth_headers)

        item = _decision(todo, 'quarantine', str(lot.id))
        assert item['name'] == 'LOT-41/26'
        assert item['product_name'] == doc_template.name
        assert Decimal(item['quantity']) == Decimal('8')
        assert item['reason'] == 'Supplier notice 41/26'
        assert _decisions(todo, 'quarantine')['total'] == 1

        # Reading the queue released nothing.
        held = db_session.get(StockLot, lot.id)
        assert held is not None
        assert held.status == LotStatus.QUARANTINED.value

    def test_a_batchless_receipt_hold_is_a_decision(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        _name_quarantine_shelf(client, doc_auth_headers, doc_quarantine_location)
        document = _create_document(
            client,
            doc_auth_headers,
            doc_type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            template_id=str(doc_template.id),
            quantity='10',
        )
        line_id = document['lines'][0]['id']
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{document["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        completed = client.patch(
            f'/api/v1/warehouse/documents/{document["id"]}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 7,
                        'discrepancy_code': 'DAMAGE',
                        'discrepancy_reason': 'Supplier notice 41/26',
                        'held_quantity': 3,
                    }
                ]
            },
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text
        completed_document = completed.json()

        todo = _todo(client, doc_auth_headers)

        hold = _receipt_hold(todo, document['id'])
        # The receipt names itself and the goods it still holds, not a batch
        # it never had.
        assert hold['lot_id'] is None
        assert hold['document_id'] == document['id']
        assert hold['document_number'] == completed_document['number']
        assert hold['product_name'] == doc_template.name
        assert hold['item_id'] is not None
        assert Decimal(hold['quantity']) == Decimal('3')
        assert hold['reason'] == 'Supplier notice 41/26'
        assert hold['location_id'] == str(doc_quarantine_location.id)
        assert hold['location_name'] == 'Quarantine shelf'
        assert _decisions(todo, 'quarantine')['total'] == 1

        # Reading the queue released nothing: the goods are still reserved on
        # the quarantine shelf and available to no draw.
        rows = _stock_rows(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        )
        assert sum(
            (Decimal(row['reserved_quantity']) for row in rows), Decimal('0')
        ) == Decimal('3')
        assert sum(
            (Decimal(row['available_quantity']) for row in rows), Decimal('0')
        ) == Decimal('0')
