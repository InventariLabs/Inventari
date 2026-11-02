"""A scan the document does not take says which product it read, and why.

On a phone the worker holds the product up to the camera and reads the answer
off the screen. "Not in the document" without a name leaves them to wonder
whether the camera read the right box, and a product whose line is already
done used to be mistaken for one that was never on the document: picking had
no word for it, so the picker was told the product did not belong there.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from tests.integration._shelf import (
    put_on_shelf,
    run_in_async_session,
    shelf_keeper,
)


def _create_document(
    client: TestClient, headers: dict[str, str], body: dict[str, Any]
) -> str:
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=body)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    return doc_id


def _start(client: TestClient, headers: dict[str, str], doc_id: str, kind: str) -> str:
    resp = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/{kind}/start', headers=headers
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


def _scan(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    kind: str,
    session_id: str,
    barcode: str | None,
    quantity: int,
) -> dict[str, Any]:
    resp = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/{kind}/{session_id}/scan',
        headers=headers,
        json={'barcode': barcode, 'quantity': quantity},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


@pytest.fixture
def second_template(h: ModuleTestHelper, doc_org: Organization) -> ProductTemplate:
    return h.create_template(doc_org, name='Second Product', barcode='4006381333931')


@pytest.fixture
def stranger(h: ModuleTestHelper, doc_org: Organization) -> ProductTemplate:
    """A real product the document does not carry."""
    return h.create_template(doc_org, name='Stranger Product', barcode='9999999999999')


@pytest.fixture
def second_stock_item(
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
    doc_source_location: StorageLocation,
    second_template: ProductTemplate,
) -> Item:
    db_session.commit()

    async def _put(session: AsyncSession) -> uuid.UUID:
        keeper = await shelf_keeper(session, doc_org.id)
        record = await put_on_shelf(
            session, keeper, second_template, doc_source_location.id, Decimal('100')
        )
        return record.id

    record_id = run_in_async_session(async_engine_fixture, _put)
    db_session.expire_all()
    item = db_session.get(Item, record_id)
    assert item is not None
    return item


@pytest.mark.integration
class TestReceivingRefusals:
    @pytest.fixture
    def session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        second_template: ProductTemplate,
    ) -> tuple[str, str]:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 2,
                    },
                    {
                        'product_template_id': str(second_template.id),
                        'expected_quantity': 5,
                    },
                ],
            },
        )
        return doc_id, _start(client, doc_auth_headers, doc_id, 'receiving')

    def test_a_product_not_on_the_delivery_is_named(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        session: tuple[str, str],
        stranger: ProductTemplate,
    ) -> None:
        doc_id, session_id = session
        data = _scan(
            client, doc_auth_headers, doc_id, 'receiving', session_id,
            stranger.barcode, 1,
        )  # fmt: skip
        assert data['status'] == 'not_in_document'
        assert data['product_name'] == 'Stranger Product'

    def test_a_received_line_says_how_much_of_it_came(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        session: tuple[str, str],
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, session_id = session
        first = _scan(
            client, doc_auth_headers, doc_id, 'receiving', session_id,
            doc_template.barcode, 2,
        )  # fmt: skip
        assert first['status'] == 'received'
        again = _scan(
            client, doc_auth_headers, doc_id, 'receiving', session_id,
            doc_template.barcode, 1,
        )  # fmt: skip
        assert again['status'] == 'already_received'
        assert again['product_name'] == 'New Product X'
        assert again['received_quantity'] == 2.0
        assert again['expected_quantity'] == 2.0

    def test_a_code_no_product_carries_stays_not_found(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        session: tuple[str, str],
    ) -> None:
        doc_id, session_id = session
        data = _scan(
            client, doc_auth_headers, doc_id, 'receiving', session_id,
            '0000000000000', 1,
        )  # fmt: skip
        assert data['status'] == 'not_found'
        assert data['product_name'] is None


@pytest.mark.integration
class TestPickingRefusals:
    @pytest.fixture
    def session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_stock_item: Item,
        second_stock_item: Item,
    ) -> tuple[str, str]:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {'item_id': str(doc_stock_item.id), 'expected_quantity': 3},
                    {'item_id': str(second_stock_item.id), 'expected_quantity': 4},
                ],
            },
        )
        return doc_id, _start(client, doc_auth_headers, doc_id, 'picking')

    def test_a_product_not_on_the_dispatch_is_named(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        session: tuple[str, str],
        stranger: ProductTemplate,
    ) -> None:
        doc_id, session_id = session
        data = _scan(
            client, doc_auth_headers, doc_id, 'picking', session_id,
            stranger.barcode, 1,
        )  # fmt: skip
        assert data['status'] == 'not_in_document'
        assert data['product_name'] == 'Stranger Product'

    def test_a_picked_line_says_how_much_of_it_was_taken(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        session: tuple[str, str],
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, session_id = session
        first = _scan(
            client, doc_auth_headers, doc_id, 'picking', session_id,
            doc_template.barcode, 3,
        )  # fmt: skip
        assert first['status'] == 'picked'
        again = _scan(
            client, doc_auth_headers, doc_id, 'picking', session_id,
            doc_template.barcode, 1,
        )  # fmt: skip
        assert again['status'] == 'already_picked'
        assert again['product_name'] == 'New Product X'
        assert again['picked_quantity'] == 3.0
        assert again['expected_quantity'] == 3.0

    def test_a_code_no_product_carries_stays_not_found(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        session: tuple[str, str],
    ) -> None:
        doc_id, session_id = session
        data = _scan(
            client, doc_auth_headers, doc_id, 'picking', session_id,
            '0000000000000', 1,
        )  # fmt: skip
        assert data['status'] == 'not_found'
        assert data['product_name'] is None
