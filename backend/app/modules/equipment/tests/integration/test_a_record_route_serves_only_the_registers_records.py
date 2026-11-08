"""A route of the register that names one record serves the register's records.

Every equipment route addressed by a record id read that record as a product
of the organization, not as one of the register's assets. A role holding
only ``equipment:read`` opened ``/equipment/<id>`` for an ordinary product
and every read of the card answered 200: the valuation with the product's
name, serial and purchase price, its attachments, its approval state, its
assignment and maintenance history and its timeline. The writes were no
better — retiring wrote an equipment status into a product nobody counts as
equipment, and archiving soft-deleted it.

A record the register's own list does not show (the module ownership rule
the list, its locations and its counts read) is now a record these routes do
not know: 404, as for an id that names nothing. The register's own asset,
live or archived, answers as before.
"""

import uuid
from datetime import date
from typing import cast

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration

_BASE = '/api/v1/equipment'

#: The reads of the asset card, each naming the record in its path.
_CARD_READS = {
    'valuation': '{base}/{id}/valuation',
    'attachments': '{base}/{id}/attachments',
    'approval-status': '{base}/{id}/approval-status',
    'assignment history': '{base}/assignments/item/{id}',
    'maintenance log': '{base}/maintenance/item/{id}',
    'timeline': '{base}/assets/{id}/timeline',
}


@pytest.fixture
def plain_product(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_storage_location: StorageLocation,
) -> str:
    """An ordinary product, filed under no category and claimed by no module."""
    created = client.post(
        '/api/v1/items',
        headers=eq_auth_headers,
        json={
            'name': 'Plain product',
            'location_id': str(eq_storage_location.id),
            'quantity': 1,
            'purchase_price': 12.5,
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return cast(str, created.json()['id'])


def _reader(h: ModuleTestHelper, org: Organization) -> dict[str, str]:
    user = h.create_user(
        org, email=f'eq_reader_{uuid.uuid4().hex[:8]}@example.com', role='user'
    )
    h.grant_permissions(user, ['equipment:read'])
    return h.get_auth_headers(user)


def _card(client: TestClient, headers: dict[str, str], item_id: str) -> dict[str, int]:
    return {
        name: client.get(
            path.format(base=_BASE, id=item_id), headers=headers
        ).status_code
        for name, path in _CARD_READS.items()
    }


class TestTheCardReadsServeTheRegistersRecords:
    def test_an_equipment_reader_meets_404_on_a_product_outside_the_register(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        eq_org: Organization,
        plain_product: str,
    ) -> None:
        answers = _card(client, _reader(h, eq_org), plain_product)

        assert answers == dict.fromkeys(_CARD_READS, status.HTTP_404_NOT_FOUND)

    def test_no_caller_reads_a_product_through_the_register(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        plain_product: str,
    ) -> None:
        """Whoever asks, the register's routes are the register's: an
        administrator reads an ordinary product through Core, not here."""
        answers = _card(client, eq_auth_headers, plain_product)

        assert answers == dict.fromkeys(_CARD_READS, status.HTTP_404_NOT_FOUND)

    def test_the_registers_own_asset_answers_live_and_archived(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        eq_org: Organization,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        reader = _reader(h, eq_org)

        live = _card(client, reader, str(eq_item.id))
        archived = client.delete(f'/api/v1/items/{eq_item.id}', headers=eq_auth_headers)
        assert archived.status_code == status.HTTP_204_NO_CONTENT, archived.text
        after_archive = _card(client, reader, str(eq_item.id))

        assert live == dict.fromkeys(_CARD_READS, status.HTTP_200_OK)
        assert after_archive == dict.fromkeys(_CARD_READS, status.HTTP_200_OK)


class TestTheRegistersWritesLeaveAProductAlone:
    def test_a_write_naming_a_product_outside_the_register_is_404(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        plain_product: str,
    ) -> None:
        headers = eq_auth_headers
        bulk = client.patch(
            f'{_BASE}/assets/bulk',
            headers=headers,
            json={
                'item_ids': [plain_product],
                'action': 'change_status',
                'data': {'status': 'MAINTENANCE'},
            },
        )
        answers = {
            'retire': client.post(
                f'{_BASE}/items/{plain_product}/retire', headers=headers
            ).status_code,
            'checkout': client.post(
                f'{_BASE}/assignments',
                headers=headers,
                json={'item_id': plain_product, 'assigned_to_name': 'Someone'},
            ).status_code,
            'maintenance': client.post(
                f'{_BASE}/maintenance',
                headers=headers,
                json={
                    'item_id': plain_product,
                    'maintenance_type': 'REPAIR',
                    'title': 'Fix',
                    'performed_at': date.today().isoformat(),
                },
            ).status_code,
            'attachment': client.post(
                f'{_BASE}/{plain_product}/attachments',
                headers=headers,
                files={'file': ('note.pdf', b'%PDF-1.4\n%%EOF\n', 'application/pdf')},
            ).status_code,
            'approval request': client.post(
                f'{_BASE}/{plain_product}/request-approval', headers=headers
            ).status_code,
            # Last: an archive that went through would hide the product from
            # every live-only write after it.
            'archive': client.post(
                f'{_BASE}/items/{plain_product}/archive', headers=headers
            ).status_code,
        }

        assert answers == dict.fromkeys(answers, status.HTTP_404_NOT_FOUND)
        assert bulk.status_code == status.HTTP_200_OK, bulk.text
        assert bulk.json()['updated'] == 0
        product = client.get(f'/api/v1/items/{plain_product}', headers=headers)
        assert product.status_code == status.HTTP_200_OK, product.text
        assert product.json()['is_deleted'] is False
        assert 'equipment' not in (product.json()['metadata'] or {})
