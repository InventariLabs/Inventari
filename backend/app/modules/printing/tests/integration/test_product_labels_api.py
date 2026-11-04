"""A product's barcode label: drawn from the product page or the list, or queued.

The code on the label is the one a scan finds the product by — a generated
internal EAN-13 here, read back off the PNG, not taken from the function
that chose it.
"""

import io
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.printing.models import PrintJob
from app.modules.printing.schemas import PROTOCOL_VERSION
from app.modules.printing.services.product_label_service import barcode_modules
from app.modules.printing.tests.bars import read_bars

_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
_BASE = '/api/v1/printing'


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Workshop', ['core', 'items', 'locations', 'printing'])


@pytest.fixture
def user(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='labels@example.com')


@pytest.fixture
def headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


@pytest.fixture
def shelf(h: ModuleTestHelper, org: Organization, user: User) -> StorageLocation:
    kind = h.create_storage_type('Shelf', 'SHELF', organization_id=org.id)
    return h.create_storage_location(org, kind, user, name='Shelf A')


def _product(
    client: TestClient,
    headers: dict[str, str],
    shelf: StorageLocation,
    name: str,
    **fields: Any,
) -> str:
    resp = client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': name,
            'location_id': str(shelf.id),
            'quantity': 1,
            **fields,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


def _generated_code(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(
        '/api/v1/items/product-templates/generate-barcode', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(str, resp.json()['barcode'])


@pytest.mark.integration
class TestProductLabelPng:
    def test_the_label_carries_the_generated_code(
        self, client: TestClient, headers: dict[str, str], shelf: StorageLocation
    ) -> None:
        code = _generated_code(client, headers)
        item_id = _product(client, headers, shelf, 'Plum butter', barcode=code)

        resp = client.post(
            f'{_BASE}/product-labels/png', headers=headers, json={'item_ids': [item_id]}
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.content.startswith(_PNG_MAGIC)
        assert resp.headers['X-Labels-Without-Code'] == '0'
        assert read_bars(resp.content) == barcode_modules(code)

    def test_many_labels_wrap_into_rows_of_full_size_labels(
        self, client: TestClient, headers: dict[str, str], shelf: StorageLocation
    ) -> None:
        """The dialog shows this file, so a long strip is an unreadable preview."""
        item_id = _product(
            client,
            headers,
            shelf,
            'Plum butter',
            barcode=_generated_code(client, headers),
        )

        resp = client.post(
            f'{_BASE}/product-labels/png',
            headers=headers,
            json={'item_ids': [item_id], 'copies': 4},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        sheet = Image.open(io.BytesIO(resp.content))
        assert sheet.size == (3 * 591 + 2 * 10, 2 * 283)

    def test_the_response_says_how_many_labels_carry_a_date(
        self, client: TestClient, headers: dict[str, str], shelf: StorageLocation
    ) -> None:
        """The option to print lot and expiry has something to print only then."""
        plain = _product(
            client,
            headers,
            shelf,
            'Plum butter',
            barcode=_generated_code(client, headers),
        )
        dated = _product(
            client,
            headers,
            shelf,
            'Yoghurt',
            barcode=_generated_code(client, headers),
            expiry_date='2031-05-01',
        )

        def counted(ids: list[str], details: bool) -> str:
            resp = client.post(
                f'{_BASE}/product-labels/png',
                headers=headers,
                json={'item_ids': ids, 'details': details},
            )
            assert resp.status_code == status.HTTP_200_OK, resp.text
            return str(resp.headers['X-Labels-With-Details'])

        assert counted([plain], details=True) == '0'
        assert counted([plain, dated], details=True) == '1'
        # Switched off, the count is still the truth about the records, or the
        # screen would lose the option the moment it was unticked.
        assert counted([plain, dated], details=False) == '1'

    def test_a_product_without_a_code_is_left_out_and_counted(
        self, client: TestClient, headers: dict[str, str], shelf: StorageLocation
    ) -> None:
        coded = _product(
            client,
            headers,
            shelf,
            'Plum butter',
            barcode=_generated_code(client, headers),
        )
        bare = _product(client, headers, shelf, 'Loose screws')

        resp = client.post(
            f'{_BASE}/product-labels/png',
            headers=headers,
            json={'item_ids': [coded, bare]},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.headers['X-Labels-Without-Code'] == '1'

    def test_no_product_with_a_code_is_refused(
        self, client: TestClient, headers: dict[str, str], shelf: StorageLocation
    ) -> None:
        bare = _product(client, headers, shelf, 'Loose screws')

        resp = client.post(
            f'{_BASE}/product-labels/png', headers=headers, json={'item_ids': [bare]}
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'code' in resp.json()['detail']['message']

    def test_a_code_wider_than_the_label_is_refused(
        self, client: TestClient, headers: dict[str, str], shelf: StorageLocation
    ) -> None:
        long_code = 'ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWX'
        item_id = _product(client, headers, shelf, 'Crate', barcode=long_code)

        resp = client.post(
            f'{_BASE}/product-labels/png',
            headers=headers,
            json={'item_ids': [item_id], 'width_mm': 50, 'height_mm': 24},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert long_code in resp.json()['detail']['message']

    def test_a_label_too_short_for_its_bars_is_refused(
        self, client: TestClient, headers: dict[str, str], shelf: StorageLocation
    ) -> None:
        item_id = _product(client, headers, shelf, 'Crate', barcode='2000000000022')

        resp = client.post(
            f'{_BASE}/product-labels/png',
            headers=headers,
            json={'item_ids': [item_id], 'width_mm': 50, 'height_mm': 5},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert '2000000000022' in resp.json()['detail']['message']

    def test_another_organizations_product_does_not_print(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        headers: dict[str, str],
        shelf: StorageLocation,
    ) -> None:
        theirs_org = h.create_org('Theirs', ['core', 'items', 'locations', 'printing'])
        theirs_user = h.create_user(theirs_org, email='theirs@example.com')
        theirs_headers = h.get_auth_headers(theirs_user)
        kind = h.create_storage_type('Shelf', 'SHELF', organization_id=theirs_org.id)
        theirs_shelf = h.create_storage_location(
            theirs_org, kind, theirs_user, name='Shelf B'
        )
        theirs = _product(
            client,
            theirs_headers,
            theirs_shelf,
            'Their jam',
            barcode=_generated_code(client, theirs_headers),
        )

        resp = client.post(
            f'{_BASE}/product-labels/png', headers=headers, json={'item_ids': [theirs]}
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestProductLabelJob:
    def test_a_queued_product_label_prints_its_code_and_expiry(
        self,
        client: TestClient,
        db_session: Session,
        headers: dict[str, str],
        shelf: StorageLocation,
    ) -> None:
        code = _generated_code(client, headers)
        item_id = _product(
            client,
            headers,
            shelf,
            'Plum butter',
            barcode=code,
            expiry_date='2027-12-31',
        )
        agent = client.post(
            f'{_BASE}/agent/register',
            headers=headers,
            json={
                'name': 'office',
                'printer_type': 'brother-p710bt',
                'agent_version': '1.0.0',
                'protocol_version': PROTOCOL_VERSION,
            },
        )
        assert agent.status_code == status.HTTP_200_OK, agent.text

        queued = client.post(
            f'{_BASE}/jobs', headers=headers, json={'item_ids': [item_id], 'copies': 2}
        )

        assert queued.status_code == status.HTTP_201_CREATED, queued.text
        job = queued.json()
        assert job['count'] == 2
        assert job['short_codes'] == [code, code]
        stored = db_session.scalar(select(PrintJob).where(PrintJob.id == job['id']))
        assert stored is not None
        assert stored.labels[0]['details'] == 'Exp. Dec 31, 2027'

        image = client.get(
            f'{_BASE}/agent/jobs/{job["id"]}/image',
            headers=headers,
            params={'index': 1},
        )
        assert image.status_code == status.HTTP_200_OK
        assert read_bars(image.content) == barcode_modules(code)

    def test_a_queued_label_dates_follow_the_organizations_country(
        self,
        client: TestClient,
        db_session: Session,
        org: Organization,
        headers: dict[str, str],
        shelf: StorageLocation,
    ) -> None:
        """The label caller only knows the language; the order comes with the request.

        The product screen of a British organization reads 3 Apr 2027, so the
        label stuck on the tin must not read Apr 3, 2027.
        """
        org.country = 'GB'
        db_session.commit()
        item_id = _product(
            client,
            headers,
            shelf,
            'Plum butter',
            barcode=_generated_code(client, headers),
            expiry_date='2027-04-03',
        )
        client.post(
            f'{_BASE}/agent/register',
            headers=headers,
            json={
                'name': 'office',
                'printer_type': 'brother-p710bt',
                'agent_version': '1.0.0',
                'protocol_version': PROTOCOL_VERSION,
            },
        )

        queued = client.post(
            f'{_BASE}/jobs', headers=headers, json={'item_ids': [item_id], 'copies': 1}
        )

        assert queued.status_code == status.HTTP_201_CREATED, queued.text
        stored = db_session.scalar(
            select(PrintJob).where(PrintJob.id == queued.json()['id'])
        )
        assert stored is not None
        assert stored.labels[0]['details'] == 'Exp. 3 Apr 2027'

    def test_a_code_wider_than_the_label_is_not_queued(
        self, client: TestClient, headers: dict[str, str], shelf: StorageLocation
    ) -> None:
        long_code = 'ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWX'
        item_id = _product(client, headers, shelf, 'Crate', barcode=long_code)
        agent = client.post(
            f'{_BASE}/agent/register',
            headers=headers,
            json={
                'name': 'office',
                'printer_type': 'brother-p710bt',
                'agent_version': '1.0.0',
                'protocol_version': PROTOCOL_VERSION,
            },
        )
        assert agent.status_code == status.HTTP_200_OK, agent.text

        queued = client.post(
            f'{_BASE}/jobs',
            headers=headers,
            json={'item_ids': [item_id], 'width_mm': 50, 'height_mm': 24},
        )

        assert queued.status_code == status.HTTP_400_BAD_REQUEST
        assert long_code in queued.json()['detail']['message']

    def test_a_label_too_short_for_its_bars_is_not_queued(
        self, client: TestClient, headers: dict[str, str], shelf: StorageLocation
    ) -> None:
        item_id = _product(client, headers, shelf, 'Crate', barcode='2000000000022')
        agent = client.post(
            f'{_BASE}/agent/register',
            headers=headers,
            json={
                'name': 'office',
                'printer_type': 'brother-p710bt',
                'agent_version': '1.0.0',
                'protocol_version': PROTOCOL_VERSION,
            },
        )
        assert agent.status_code == status.HTTP_200_OK, agent.text

        queued = client.post(
            f'{_BASE}/jobs',
            headers=headers,
            json={'item_ids': [item_id], 'width_mm': 50, 'height_mm': 5},
        )

        assert queued.status_code == status.HTTP_400_BAD_REQUEST
        assert '2000000000022' in queued.json()['detail']['message']
