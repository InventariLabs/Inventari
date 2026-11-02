"""
The shelf confirmed by scan, before the product, in picking and receiving.

With the profile setting off nothing here applies (the picking and receiving
suites pin that). With it on, a session expects the shelf's label first:
a product scanned before it, or after another shelf's, is refused with the
shelf the line is waiting at, and the right shelf then the product records
the pick or the receipt against the stock standing on that shelf.
"""

import uuid
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.warehouse.tests.integration._records import (
    shelf_quant as _shelf_quant,
)
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)
from app.modules.warehouse.tests.integration.test_wms_picking import (
    _confirm_document,
    _create_out_document,
)
from app.modules.warehouse.tests.integration.test_wms_receiving import (
    _create_in_document,
)


@pytest.fixture
def shelf_a(
    db_session: Session, doc_source_location: StorageLocation
) -> StorageLocation:
    doc_source_location.short_code = 'SHF-A1'
    db_session.commit()
    return doc_source_location


@pytest.fixture
def shelf_b(
    h: ModuleTestHelper,
    db_session: Session,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
) -> StorageLocation:
    other = h.create_storage_location(
        doc_org, doc_storage_type, doc_user, name='Other Shelf'
    )
    other.short_code = 'SHF-B2'
    db_session.commit()
    return other


def _turn_on(client: TestClient, headers: dict[str, str]) -> None:
    resp = client.put(
        '/api/v1/warehouse/profile',
        headers=headers,
        json={'confirm_shelf_by_scan': True},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert resp.json()['confirm_shelf_by_scan'] is True


def _scan(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    kind: str,
    session_id: str,
    barcode: str | None,
    quantity: int = 1,
) -> dict[str, Any]:
    resp = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/{kind}/{session_id}/scan',
        headers=headers,
        json={'barcode': barcode, 'quantity': quantity},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


@pytest.mark.integration
class TestPickingConfirmsTheShelf:
    def _start(
        self,
        client: TestClient,
        headers: dict[str, str],
        shelf_a: StorageLocation,
        target: StorageLocation,
        partner: Partner,
        item: Item,
        template: ProductTemplate,
    ) -> tuple[str, str]:
        doc_id = _create_out_document(
            client,
            headers,
            shelf_a.id,
            target.id,
            partner.id,
            item.template_id or template.id,
            item.id,
        )
        _confirm_document(client, headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start', headers=headers
        )
        assert start.status_code == status.HTTP_201_CREATED, start.text
        return doc_id, cast(str, start.json()['id'])

    def test_the_product_before_the_shelf_is_refused_naming_the_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client,
            doc_auth_headers,
            shelf_a,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
        )

        answer = _scan(
            client,
            doc_auth_headers,
            doc_id,
            'picking',
            session_id,
            doc_template.barcode,
        )

        assert answer['status'] == 'shelf_required'
        assert 'SHF-A1' in answer['shelf']
        assert answer['picked_quantity'] == 0
        session = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking', headers=doc_auth_headers
        ).json()['items'][0]
        assert session['lines'][0]['status'] == 'pending'
        assert session['shelf_scan_required'] is True
        assert session['confirmed_shelf_id'] is None

    def test_another_shelf_is_refused_and_leaves_the_product_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client,
            doc_auth_headers,
            shelf_a,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
        )

        wrong = _scan(client, doc_auth_headers, doc_id, 'picking', session_id, 'SHF-B2')
        assert wrong['status'] == 'wrong_shelf'
        assert 'SHF-A1' in wrong['shelf']

        product = _scan(
            client,
            doc_auth_headers,
            doc_id,
            'picking',
            session_id,
            doc_template.barcode,
        )
        assert product['status'] == 'shelf_required'

    def test_a_wrong_shelf_after_the_right_one_withdraws_the_confirmation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client,
            doc_auth_headers,
            shelf_a,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
        )
        right = _scan(client, doc_auth_headers, doc_id, 'picking', session_id, 'SHF-A1')
        assert right['status'] == 'shelf_confirmed'

        wrong = _scan(client, doc_auth_headers, doc_id, 'picking', session_id, 'SHF-B2')
        assert wrong['status'] == 'wrong_shelf'

        session = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking', headers=doc_auth_headers
        ).json()['items'][0]
        assert session['confirmed_shelf_id'] is None
        product = _scan(
            client,
            doc_auth_headers,
            doc_id,
            'picking',
            session_id,
            doc_template.barcode,
        )
        assert product['status'] == 'shelf_required'
        short = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/short-pick',
            headers=doc_auth_headers,
            json={
                'line_id': session['lines'][0]['id'],
                'picked_quantity': 2,
                'discrepancy_code': 'SHORTAGE',
            },
        )
        assert short.json()['status'] == 'shelf_required'

    def test_the_right_shelf_then_the_product_charges_the_record_on_that_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        template_id = doc_item.template_id or doc_template.id
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_b.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client,
            doc_auth_headers,
            shelf_a,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
        )

        shelf = _scan(client, doc_auth_headers, doc_id, 'picking', session_id, 'SHF-A1')
        assert shelf['status'] == 'shelf_confirmed'
        picked = _scan(
            client,
            doc_auth_headers,
            doc_id,
            'picking',
            session_id,
            doc_template.barcode,
            quantity=5,
        )
        assert picked['status'] == 'picked'
        assert picked['session_complete'] is True

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/complete',
            headers=doc_auth_headers,
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )
        assert done.status_code == status.HTTP_200_OK, done.text
        on_a = _shelf_quant(db_session, doc_org.id, template_id, shelf_a.id)
        on_b = _shelf_quant(db_session, doc_org.id, template_id, shelf_b.id)
        assert float(on_a.quantity) == 15.0
        assert float(on_b.quantity) == 20.0

    def test_a_location_label_from_the_pool_confirms_the_shelf_too(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        db_session.add(
            LabelPool(
                short_code='STM-LOC1',
                organization_id=doc_org.id,
                created_by=doc_user.id,
                label_type='STORAGE',
                is_assigned=True,
                target_storage_location_id=shelf_a.id,
            )
        )
        db_session.commit()
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client,
            doc_auth_headers,
            shelf_a,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
        )

        shelf = _scan(
            client, doc_auth_headers, doc_id, 'picking', session_id, 'STM-LOC1'
        )

        assert shelf['status'] == 'shelf_confirmed'
        session = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking', headers=doc_auth_headers
        ).json()['items'][0]
        assert session['confirmed_shelf_id'] == str(shelf_a.id)
        assert session['lines'][0]['location_id'] == str(shelf_a.id)

    def test_with_the_setting_off_a_shelf_code_is_just_an_unknown_product(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        doc_id, session_id = self._start(
            client,
            doc_auth_headers,
            shelf_a,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
        )

        shelf = _scan(client, doc_auth_headers, doc_id, 'picking', session_id, 'SHF-A1')
        assert shelf['status'] == 'not_found'
        picked = _scan(
            client,
            doc_auth_headers,
            doc_id,
            'picking',
            session_id,
            doc_template.barcode,
            quantity=5,
        )
        assert picked['status'] == 'picked'

    def test_a_shelf_without_a_code_is_picked_without_a_label_to_scan(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        # The organization's own main warehouse is seeded without a code, so
        # no label for it can be printed: the session must not demand one.
        shelf_a.short_code = None
        db_session.commit()
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client,
            doc_auth_headers,
            shelf_a,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
        )

        picked = _scan(
            client,
            doc_auth_headers,
            doc_id,
            'picking',
            session_id,
            doc_template.barcode,
            quantity=2,
        )
        assert picked['status'] == 'picked'
        session = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking', headers=doc_auth_headers
        ).json()['items'][0]
        short = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/short-pick',
            headers=doc_auth_headers,
            json={
                'line_id': session['lines'][0]['id'],
                'picked_quantity': 3,
                'discrepancy_code': 'SHORTAGE',
            },
        )
        assert short.json()['status'] == 'short_pick_confirmed'

    def test_a_place_with_only_a_pool_label_is_still_asked_for(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        # No code of its own, but a label printed from the pool is aimed at
        # it and scans as the place: the shelf is asked for, and the line
        # carries the label's code so the chip agrees with the rule.
        shelf_a.short_code = None
        db_session.add(
            LabelPool(
                short_code='STM-LOC9',
                organization_id=doc_org.id,
                created_by=doc_user.id,
                label_type='STORAGE',
                is_assigned=True,
                target_storage_location_id=shelf_a.id,
            )
        )
        db_session.commit()
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client,
            doc_auth_headers,
            shelf_a,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
        )
        session = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking', headers=doc_auth_headers
        ).json()['items'][0]
        assert session['lines'][0]['location_code'] == 'STM-LOC9'

        refused = _scan(
            client,
            doc_auth_headers,
            doc_id,
            'picking',
            session_id,
            doc_template.barcode,
        )

        assert refused['status'] == 'shelf_required'
        shelf = _scan(
            client, doc_auth_headers, doc_id, 'picking', session_id, 'STM-LOC9'
        )
        assert shelf['status'] == 'shelf_confirmed'

    def test_the_short_pick_button_answers_to_the_same_rule(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client,
            doc_auth_headers,
            shelf_a,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
        )
        session = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking', headers=doc_auth_headers
        ).json()['items'][0]
        line_id = session['lines'][0]['id']
        short = f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/short-pick'

        refused = client.post(
            short,
            headers=doc_auth_headers,
            json={
                'line_id': line_id,
                'picked_quantity': 2,
                'discrepancy_code': 'SHORTAGE',
            },
        )
        assert refused.status_code == status.HTTP_200_OK, refused.text
        assert refused.json()['status'] == 'shelf_required'
        assert 'SHF-A1' in refused.json()['shelf']
        after = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking', headers=doc_auth_headers
        ).json()['items'][0]
        assert after['lines'][0]['status'] == 'pending'
        assert after['lines'][0]['picked_quantity'] == 0

        _scan(client, doc_auth_headers, doc_id, 'picking', session_id, 'SHF-A1')
        accepted = client.post(
            short,
            headers=doc_auth_headers,
            json={
                'line_id': line_id,
                'picked_quantity': 2,
                'discrepancy_code': 'SHORTAGE',
            },
        )
        assert accepted.json()['status'] == 'short_pick_confirmed'
        assert accepted.json()['picked_quantity'] == 2


@pytest.fixture
def destination(
    doc_target_location: StorageLocation, db_session: Session
) -> StorageLocation:
    doc_target_location.short_code = 'DST-C3'
    db_session.commit()
    return doc_target_location


@pytest.mark.integration
class TestTransferConfirmsItsDestination:
    """After the last line, a transfer asks for the destination's label."""

    def _start(
        self,
        client: TestClient,
        headers: dict[str, str],
        source: StorageLocation,
        target: StorageLocation,
        item: Item,
        template: ProductTemplate,
    ) -> tuple[str, str]:
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'INT',
                'source_location_id': str(source.id),
                'target_location_id': str(target.id),
                'lines': [
                    {
                        'item_id': str(item.id),
                        'product_template_id': str(item.template_id or template.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = cast(str, created.json()['id'])
        _confirm_document(client, headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start', headers=headers
        )
        assert start.status_code == status.HTTP_201_CREATED, start.text
        return doc_id, cast(str, start.json()['id'])

    def _pick_everything(
        self,
        client: TestClient,
        headers: dict[str, str],
        doc_id: str,
        session_id: str,
        template: ProductTemplate,
    ) -> dict[str, Any]:
        _scan(client, headers, doc_id, 'picking', session_id, 'SHF-A1')
        return _scan(
            client, headers, doc_id, 'picking', session_id, template.barcode, 5
        )

    def _session(
        self, client: TestClient, headers: dict[str, str], doc_id: str
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            client.get(
                f'/api/v1/warehouse/documents/{doc_id}/picking', headers=headers
            ).json()['items'][0],
        )

    def test_the_session_stays_open_until_the_destination_label_is_scanned(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        destination: StorageLocation,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        template_id = doc_template.id
        record = _sow(
            db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20'
        )
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, destination, record, doc_template
        )

        picked = self._pick_everything(
            client, doc_auth_headers, doc_id, session_id, doc_template
        )
        assert picked['status'] == 'picked'
        assert picked['session_complete'] is False
        waiting = self._session(client, doc_auth_headers, doc_id)
        assert waiting['status'] == 'active'
        assert waiting['destination_shelf_id'] == str(destination.id)
        assert 'DST-C3' in waiting['destination_shelf']

        wrong = _scan(client, doc_auth_headers, doc_id, 'picking', session_id, 'SHF-B2')
        assert wrong['status'] == 'wrong_shelf'
        assert 'DST-C3' in wrong['shelf']
        assert wrong['session_complete'] is False
        assert self._session(client, doc_auth_headers, doc_id)['status'] == 'active'

        right = _scan(client, doc_auth_headers, doc_id, 'picking', session_id, 'DST-C3')
        assert right['status'] == 'shelf_confirmed'
        assert right['session_complete'] is True
        closed = self._session(client, doc_auth_headers, doc_id)
        assert closed['status'] == 'completed'
        assert closed['destination_shelf_id'] is None

        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )
        assert done.status_code == status.HTTP_200_OK, done.text
        on_destination = _shelf_quant(
            db_session, doc_org.id, template_id, destination.id
        )
        assert float(on_destination.quantity) == 5.0

    def test_the_complete_door_does_not_skip_the_destination_scan(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        destination: StorageLocation,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, destination, doc_item, doc_template
        )
        self._pick_everything(
            client, doc_auth_headers, doc_id, session_id, doc_template
        )

        refused = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/complete',
            headers=doc_auth_headers,
        )

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert self._session(client, doc_auth_headers, doc_id)['status'] == 'active'

    def test_document_completion_does_not_skip_the_destination_scan(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        destination: StorageLocation,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, destination, doc_item, doc_template
        )
        self._pick_everything(
            client, doc_auth_headers, doc_id, session_id, doc_template
        )

        refused = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        assert refused.json()['detail']['code'] == 'WMS_SESSION_ACTIVE'
        document = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()
        assert document['status'] == 'CONFIRMED'

    def test_a_short_pick_of_the_last_line_asks_for_the_destination_too(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        destination: StorageLocation,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, destination, doc_item, doc_template
        )
        _scan(client, doc_auth_headers, doc_id, 'picking', session_id, 'SHF-A1')
        line_id = self._session(client, doc_auth_headers, doc_id)['lines'][0]['id']

        short = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/short-pick',
            headers=doc_auth_headers,
            json={
                'line_id': line_id,
                'picked_quantity': 2,
                'discrepancy_code': 'SHORTAGE',
            },
        )

        assert short.json()['status'] == 'short_pick_confirmed'
        assert short.json()['session_complete'] is False
        assert self._session(client, doc_auth_headers, doc_id)['status'] == 'active'

    def test_nothing_picked_means_no_destination_to_confirm(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        destination: StorageLocation,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, destination, doc_item, doc_template
        )
        line_id = self._session(client, doc_auth_headers, doc_id)['lines'][0]['id']

        skipped = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/skip',
            headers=doc_auth_headers,
            params={'line_id': line_id},
        )

        assert skipped.status_code == status.HTTP_200_OK, skipped.text
        closed = self._session(client, doc_auth_headers, doc_id)
        assert closed['status'] == 'completed'
        assert closed['destination_shelf_id'] is None

    def test_with_the_setting_off_the_last_pick_ends_the_session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        destination: StorageLocation,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '20')
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, destination, doc_item, doc_template
        )

        picked = _scan(
            client, doc_auth_headers, doc_id, 'picking', session_id,
            doc_template.barcode, 5,
        )  # fmt: skip

        assert picked['status'] == 'picked'
        assert picked['session_complete'] is True
        closed = self._session(client, doc_auth_headers, doc_id)
        assert closed['status'] == 'completed'
        assert closed['destination_shelf_id'] is None


@pytest.mark.integration
class TestReceivingConfirmsTheShelf:
    def _start(
        self,
        client: TestClient,
        headers: dict[str, str],
        shelf: StorageLocation,
        partner: Partner,
        template: ProductTemplate,
    ) -> tuple[str, str]:
        doc_id = _create_in_document(
            client, headers, shelf.id, partner.id, template.id, quantity=10
        )
        _confirm_document(client, headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
        )
        assert start.status_code == status.HTTP_201_CREATED, start.text
        return doc_id, cast(str, start.json()['id'])

    def test_the_product_before_the_shelf_is_refused_naming_the_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, doc_partner, doc_template
        )

        answer = _scan(
            client,
            doc_auth_headers,
            doc_id,
            'receiving',
            session_id,
            doc_template.barcode,
        )

        assert answer['status'] == 'shelf_required'
        assert 'SHF-A1' in answer['shelf']
        assert answer['received_quantity'] == 0

    def test_another_shelf_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, doc_partner, doc_template
        )

        wrong = _scan(
            client, doc_auth_headers, doc_id, 'receiving', session_id, 'SHF-B2'
        )

        assert wrong['status'] == 'wrong_shelf'
        assert 'SHF-A1' in wrong['shelf']

    def test_the_line_names_the_code_to_scan_only_where_there_is_one(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
    ) -> None:
        _turn_on(client, doc_auth_headers)
        doc_id, _ = self._start(
            client, doc_auth_headers, shelf_a, doc_partner, doc_template
        )

        def planned_code() -> str | None:
            session = client.get(
                f'/api/v1/warehouse/documents/{doc_id}/receiving',
                headers=doc_auth_headers,
            ).json()['items'][0]
            return cast('str | None', session['lines'][0]['planned_location_code'])

        assert planned_code() == 'SHF-A1'

        # Without a code of its own the place is asked for only when a label
        # is printed for it; with neither the line has nothing to scan, so
        # its chip must not promise a label.
        shelf_a.short_code = None
        db_session.commit()
        assert planned_code() is None
        db_session.add(
            LabelPool(
                short_code='STM-LOC5',
                organization_id=doc_org.id,
                created_by=doc_user.id,
                label_type='STORAGE',
                is_assigned=True,
                target_storage_location_id=shelf_a.id,
            )
        )
        db_session.commit()
        assert planned_code() == 'STM-LOC5'

    def test_a_wrong_shelf_after_the_right_one_withdraws_the_confirmation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, doc_partner, doc_template
        )
        right = _scan(
            client, doc_auth_headers, doc_id, 'receiving', session_id, 'SHF-A1'
        )
        assert right['status'] == 'shelf_confirmed'

        wrong = _scan(
            client, doc_auth_headers, doc_id, 'receiving', session_id, 'SHF-B2'
        )
        assert wrong['status'] == 'wrong_shelf'

        session = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving', headers=doc_auth_headers
        ).json()['items'][0]
        assert session['confirmed_shelf_id'] is None
        product = _scan(
            client,
            doc_auth_headers,
            doc_id,
            'receiving',
            session_id,
            doc_template.barcode,
        )
        assert product['status'] == 'shelf_required'
        short = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
            headers=doc_auth_headers,
            json={'line_id': session['lines'][0]['id'], 'received_quantity': 2},
        )
        assert short.json()['status'] == 'shelf_required'

    def test_the_planned_shelf_then_the_product_books_the_receipt_there(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, doc_partner, doc_template
        )

        shelf = _scan(
            client, doc_auth_headers, doc_id, 'receiving', session_id, 'SHF-A1'
        )
        assert shelf['status'] == 'shelf_confirmed'
        received = _scan(
            client,
            doc_auth_headers,
            doc_id,
            'receiving',
            session_id,
            doc_template.barcode,
            quantity=10,
        )
        assert received['status'] == 'received'

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/complete',
            headers=doc_auth_headers,
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )
        assert done.status_code == status.HTTP_200_OK, done.text
        on_shelf = _shelf_quant(db_session, doc_org.id, doc_template.id, shelf_a.id)
        assert float(on_shelf.quantity) == 10.0
        assert uuid.UUID(str(on_shelf.storage_location_id)) == shelf_a.id

    def test_short_receive_and_receive_full_answer_to_the_same_rule(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = self._start(
            client, doc_auth_headers, shelf_a, doc_partner, doc_template
        )
        session = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving', headers=doc_auth_headers
        ).json()['items'][0]
        line_id = session['lines'][0]['id']
        short = (
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive'
        )

        refused = client.post(
            short,
            headers=doc_auth_headers,
            json={'line_id': line_id, 'received_quantity': 10},
        )
        assert refused.status_code == status.HTTP_200_OK, refused.text
        assert refused.json()['status'] == 'shelf_required'
        assert 'SHF-A1' in refused.json()['shelf']
        assert refused.json()['received_quantity'] == 0
        after = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving', headers=doc_auth_headers
        ).json()['items'][0]
        assert after['lines'][0]['status'] == 'pending'

        nothing = client.post(
            short,
            headers=doc_auth_headers,
            json={'line_id': line_id, 'received_quantity': 0},
        )
        assert nothing.json()['status'] == 'short_receive_confirmed'


@pytest.fixture
def renumbered_shelf(
    client: TestClient,
    h: ModuleTestHelper,
    db_session: Session,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
    doc_auth_headers: dict[str, str],
    shelf_a: StorageLocation,
) -> StorageLocation:
    """Shelf A, set up as LOC-7KQ2 by a household, renumbered to A by the
    business it became: the sticker on the shelf still says LOC-7KQ2."""
    warehouse = h.create_storage_location(
        doc_org, doc_storage_type, doc_user, name='Main Warehouse'
    )
    shelf_a.parent_id = warehouse.id
    shelf_a.short_code = 'LOC-7KQ2'
    db_session.commit()
    resp = client.post(
        f'/api/v1/locations/{warehouse.id}/number',
        headers=doc_auth_headers,
        json={'renumber': True},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    db_session.refresh(shelf_a)
    assert shelf_a.short_code == 'A'
    return shelf_a


@pytest.mark.integration
class TestAnOldStickerStillNamesTheShelf:
    """The sticker on the shelf is the old code, or a QR whose whole address a
    2D hardware scanner types into the field: either names the same shelf."""

    @pytest.mark.parametrize(
        'read', ['LOC-7KQ2', 'https://wh.example.test/labels/scan/LOC-7KQ2']
    )
    def test_picking_confirms_the_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        renumbered_shelf: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        read: str,
    ) -> None:
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            renumbered_shelf.id,
            '20',
        )
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = TestPickingConfirmsTheShelf()._start(
            client,
            doc_auth_headers,
            renumbered_shelf,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
        )

        shelf = _scan(client, doc_auth_headers, doc_id, 'picking', session_id, read)

        assert shelf['status'] == 'shelf_confirmed'
        assert shelf['shelf_id'] == str(renumbered_shelf.id)

    @pytest.mark.parametrize('read', ['LOC-7KQ2', 'https://wh.example.test/s/A', 'A'])
    def test_receiving_confirms_the_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        renumbered_shelf: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        read: str,
    ) -> None:
        _turn_on(client, doc_auth_headers)
        doc_id, session_id = TestReceivingConfirmsTheShelf()._start(
            client, doc_auth_headers, renumbered_shelf, doc_partner, doc_template
        )

        shelf = _scan(client, doc_auth_headers, doc_id, 'receiving', session_id, read)

        assert shelf['status'] == 'shelf_confirmed'
        assert shelf['shelf_id'] == str(renumbered_shelf.id)
