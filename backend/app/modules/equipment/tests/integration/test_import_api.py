from __future__ import annotations

import json

import pytest
from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User

"""Equipment import analyze / execute endpoints.

The import wizard (ImportEquipmentModal.tsx) already calls
``POST /equipment/import/analyze`` and ``POST /equipment/import/execute``,
but neither route was ever wired in ``equipment/router.py``. Both
service functions exist and are unit-tested, so we only need the HTTP
surface plus integration coverage.
"""


_SAMPLE_OK = (
    b'name,serial,storage\nLaptop-1,SN-A,Server Room A\nLaptop-2,SN-B,Server Room A\n'
)


@pytest.mark.integration
class TestAnalyzeEndpoint:
    """``POST /equipment/import/analyze`` is a dry-run: parses the file, returns
    headers + preview rows + total row count, never writes to the DB."""

    def test_analyze_returns_headers_preview_and_total(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/equipment/import/analyze',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', _SAMPLE_OK, 'text/csv')},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert set(body['headers']) == {'name', 'serial', 'storage'}
        assert len(body['preview_rows']) == 2
        assert body['total_rows'] == 2

    def test_analyze_does_not_write_to_db(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """The dry-run guarantee: analyze leaves the items table untouched."""
        before = db_session.scalar(select(func.count()).select_from(Item)) or 0
        client.post(
            '/api/v1/equipment/import/analyze',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', _SAMPLE_OK, 'text/csv')},
        )
        db_session.expire_all()
        after = db_session.scalar(select(func.count()).select_from(Item)) or 0
        assert after == before

    def test_analyze_requires_auth(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/equipment/import/analyze',
            files={'file': ('assets.csv', _SAMPLE_OK, 'text/csv')},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestExecuteEndpoint:
    """``POST /equipment/import/execute`` commits the batch."""

    def test_execute_happy_path_creates_items(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        mapping = {'name': 'name', 'serial_number': 'serial'}
        resp = client.post(
            '/api/v1/equipment/import/execute',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', _SAMPLE_OK, 'text/csv')},
            data={
                'mapping_json': json.dumps(mapping),
                'default_location_id': str(eq_storage_location.id),
                'default_category_id': str(eq_category.id),
            },
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert body['imported'] == 2
        assert body['failed'] == 0
        assert body['errors'] == []
        db_session.expire_all()
        items = (
            db_session.query(Item)
            .filter(Item.organization_id == eq_storage_location.organization_id)
            .all()
        )
        assert len(items) == 2
        names = {i.name for i in items}
        assert names == {'Laptop-1', 'Laptop-2'}

    def test_execute_invalid_mapping_json_returns_400(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
    ) -> None:
        resp = client.post(
            '/api/v1/equipment/import/execute',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', _SAMPLE_OK, 'text/csv')},
            data={
                'mapping_json': 'this is not json',
                'default_location_id': str(eq_storage_location.id),
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_execute_requires_auth(
        self, client: TestClient, eq_storage_location: StorageLocation
    ) -> None:
        resp = client.post(
            '/api/v1/equipment/import/execute',
            files={'file': ('assets.csv', _SAMPLE_OK, 'text/csv')},
            data={
                'mapping_json': json.dumps({'name': 'name'}),
                'default_location_id': str(eq_storage_location.id),
            },
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_execute_create_only_skips_duplicates(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        """Importing the same file twice in create_only
        mode reports the second run as skipped, not as new assets."""
        mapping = {
            'name': 'name',
            'serial_number': 'serial',
            'duplicate_mode': 'create_only',
        }
        data = {
            'mapping_json': json.dumps(mapping),
            'default_location_id': str(eq_storage_location.id),
            'default_category_id': str(eq_category.id),
        }
        first = client.post(
            '/api/v1/equipment/import/execute',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', _SAMPLE_OK, 'text/csv')},
            data=data,
        )
        assert first.status_code == status.HTTP_200_OK, first.text
        assert first.json()['imported'] == 2

        second = client.post(
            '/api/v1/equipment/import/execute',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', _SAMPLE_OK, 'text/csv')},
            data=data,
        )
        assert second.status_code == status.HTTP_200_OK, second.text
        body = second.json()
        assert body['imported'] == 0
        assert body['skipped'] == 2
        # The result names the serial numbers it skipped, not only how many.
        assert body['skipped_serials'] == ['SN-A', 'SN-B']

        db_session.expire_all()
        count = (
            db_session.query(Item)
            .filter(Item.organization_id == eq_storage_location.organization_id)
            .count()
        )
        assert count == 2

    def test_an_update_without_a_status_keeps_the_asset_in_maintenance(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """A sheet that says nothing about the status changes nothing about it.

        A blank status cell read as Available, so re-importing a sheet in
        update mode without the column took every matched asset out of the
        workshop, with its repair entry still open. Measured with the fix
        reverted: ``assert 'AVAILABLE' == 'MAINTENANCE'``.
        """

        def run(sheet: bytes, mapping: dict[str, str]) -> None:
            resp = client.post(
                '/api/v1/equipment/import/execute',
                headers=eq_auth_headers,
                files={'file': ('assets.csv', sheet, 'text/csv')},
                data={
                    'mapping_json': json.dumps(mapping),
                    'default_location_id': str(eq_storage_location.id),
                },
            )
            assert resp.status_code == status.HTTP_200_OK, resp.text
            assert resp.json()['errors'] == [], resp.json()

        run(
            b'name,serial,status\nLaptop-1,SN-M,Maintenance\n',
            {'name': 'name', 'serial_number': 'serial', 'equipment_status': 'status'},
        )
        run(
            b'name,serial\nLaptop-1 renamed,SN-M\n',
            {'name': 'name', 'serial_number': 'serial', 'duplicate_mode': 'update'},
        )

        db_session.expire_all()
        (item,) = db_session.query(Item).filter(
            Item.organization_id == eq_storage_location.organization_id
        )
        assert item.name == 'Laptop-1 renamed'
        assert item.meta_data is not None
        assert item.meta_data['equipment']['equipment_status'] == 'MAINTENANCE'

    def test_a_new_asset_without_a_status_arrives_available(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """The other half of a blank status: a new asset still gets one.

        A pin, not a measurement: it passes with the fix reverted too, and
        holds the creation path now that the importer writes no default.
        """
        resp = client.post(
            '/api/v1/equipment/import/execute',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', b'name\nLaptop-1\n', 'text/csv')},
            data={
                'mapping_json': json.dumps({'name': 'name'}),
                'default_location_id': str(eq_storage_location.id),
            },
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.expire_all()
        (item,) = db_session.query(Item).filter(
            Item.organization_id == eq_storage_location.organization_id
        )
        assert item.meta_data is not None
        assert item.meta_data['equipment']['equipment_status'] == 'AVAILABLE'


@pytest.mark.integration
class TestAnalyzeSuggestions:
    """The analyzer suggests field mappings for
    non-English headers."""

    _POLISH_CSV = (
        b'Nazwa,Numer seryjny,Producent,Model,Kategoria,Lokalizacja,'
        b'Cena zakupu,Data zakupu,Gwarancja do\n'
        b'Laptop,SN-PL,HP,EliteBook,Laptop,Server Room A,1000,2024-01-01,2026-01-01\n'
    )

    def test_analyze_suggests_polish_headers(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/equipment/import/analyze',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', self._POLISH_CSV, 'text/csv')},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        suggestions = resp.json()['suggested_mapping']
        assert suggestions['name'] == 'Nazwa'
        assert suggestions['serial_number'] == 'Numer seryjny'
        # Brand and manufacturer became one target; a Polish "Producent"
        # header maps onto it.
        assert suggestions['brand'] == 'Producent'
        assert 'manufacturer' not in suggestions
        assert suggestions['model'] == 'Model'
        assert suggestions['category'] == 'Kategoria'
        assert suggestions['location'] == 'Lokalizacja'
        assert suggestions['purchase_price'] == 'Cena zakupu'
        assert suggestions['purchase_date'] == 'Data zakupu'
        assert suggestions['warranty_until'] == 'Gwarancja do'


@pytest.mark.integration
class TestAnalyzeExecuteRoundtrip:
    """Analyze → fix mapping → re-analyze → execute.

    Roundtrip behaviour is the value the split delivers — operators see
    errors before any rows hit the database, can adjust the mapping, and
    re-analyze without leaving rows behind.
    """

    def test_dry_run_then_execute_after_fix_roundtrip(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        csv_with_bad_row = (
            b'name,serial,storage\n'
            b'Laptop-1,SN-A,Server Room A\n'
            b'Laptop-2,SN-B,Nonexistent Storage\n'
            b'Laptop-3,SN-C,Server Room A\n'
        )

        # 1. Analyze (dry-run).
        r = client.post(
            '/api/v1/equipment/import/analyze',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', csv_with_bad_row, 'text/csv')},
        )
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['total_rows'] == 3

        before = db_session.scalar(select(func.count()).select_from(Item)) or 0

        # 2. Execute WITHOUT default location → one row fails.
        r = client.post(
            '/api/v1/equipment/import/execute',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', csv_with_bad_row, 'text/csv')},
            data={
                'mapping_json': json.dumps(
                    {
                        'name': 'name',
                        'serial_number': 'serial',
                        'location': 'storage',
                    }
                ),
            },
        )
        assert r.status_code == status.HTTP_200_OK
        body = r.json()
        assert body['imported'] == 2
        assert body['failed'] == 1

        # 3. Re-analyze a corrected CSV (storage column dropped, default kicks in).
        csv_fixed = b'name,serial\nLaptop-4,SN-D\nLaptop-5,SN-E\n'
        r = client.post(
            '/api/v1/equipment/import/analyze',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', csv_fixed, 'text/csv')},
        )
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['total_rows'] == 2

        # 4. Execute with default_location_id → both rows succeed.
        r = client.post(
            '/api/v1/equipment/import/execute',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', csv_fixed, 'text/csv')},
            data={
                'mapping_json': json.dumps({'name': 'name', 'serial_number': 'serial'}),
                'default_location_id': str(eq_storage_location.id),
                'default_category_id': str(eq_category.id),
            },
        )
        assert r.status_code == status.HTTP_200_OK
        assert r.json() == {
            'imported': 2,
            'failed': 0,
            'errors': [],
            'skipped': 0,
            'updated': 0,
            'skipped_serials': [],
        }

        db_session.expire_all()
        after = db_session.scalar(select(func.count()).select_from(Item)) or 0
        assert after == before + 4  # 2 from step 2 + 2 from step 4


@pytest.mark.integration
class TestTheImportReadsTheSheetTheAppExports:
    """A list exported, edited and imported back carries the words the app
    prints — "Available", not AVAILABLE — and every row of it used to fail."""

    def test_status_as_the_app_shows_it_in_any_language_and_case(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        sheet = (
            b'name,status\n'
            b'Laptop-1,Available\n'
            b'Laptop-2,W serwisie\n'
            b'Laptop-3,ausgeliehen\n'
            b'Laptop-4,RETIRED\n'
        )
        resp = client.post(
            '/api/v1/equipment/import/execute',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', sheet, 'text/csv')},
            data={
                'mapping_json': json.dumps(
                    {'name': 'name', 'equipment_status': 'status'}
                ),
                'default_location_id': str(eq_storage_location.id),
            },
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['imported'] == 4, resp.json()
        db_session.expire_all()
        stored = {
            i.name: (i.meta_data or {})['equipment']['equipment_status']
            for i in db_session.query(Item).filter(
                Item.organization_id == eq_storage_location.organization_id
            )
        }
        assert stored == {
            'Laptop-1': 'AVAILABLE',
            'Laptop-2': 'MAINTENANCE',
            'Laptop-3': 'DEPLOYED',
            'Laptop-4': 'RETIRED',
        }

    def test_a_location_it_cannot_find_is_named_in_the_row(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
    ) -> None:
        resp = client.post(
            '/api/v1/equipment/import/execute',
            headers=eq_auth_headers,
            files={
                'file': ('assets.csv', b'name,storage\nLaptop-1,Shelf 9\n', 'text/csv')
            },
            data={'mapping_json': json.dumps({'name': 'name', 'location': 'storage'})},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert body['imported'] == 0
        assert body['errors'] == [
            {
                'row': 1,
                'error': 'No location is named “Shelf 9”',
                'code': 'IMPORT_LOCATION_NOT_FOUND',
            }
        ]

    def test_an_ambiguous_location_is_refused_in_the_readers_language(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        h: ModuleTestHelper,
        eq_org: Organization,
        eq_user: User,
        eq_storage_type: StorageType,
    ) -> None:
        """A word that names two shelves reaches the row as a keyed Polish refusal.

        The resolver is unit-tested in isolation; this drives the same
        refusal through the real request, where the row carries the sentence
        in the session language and the code a client branches on.
        """
        for rack in ('Rack A', 'Rack B'):
            parent = h.create_storage_location(
                eq_org, eq_storage_type, eq_user, name=rack
            )
            h.create_storage_location(
                eq_org, eq_storage_type, eq_user, name='Shelf 1', parent_id=parent.id
            )

        resp = client.post(
            '/api/v1/equipment/import/execute',
            headers={**eq_auth_headers, 'Accept-Language': 'pl'},
            files={
                'file': ('assets.csv', b'name,storage\nLaptop-1,Shelf 1\n', 'text/csv')
            },
            data={'mapping_json': json.dumps({'name': 'name', 'location': 'storage'})},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert body['imported'] == 0
        [row] = body['errors']
        assert row['row'] == 1
        assert row['error'].startswith('„Shelf 1” pasuje do 2 miejsc')
        assert 'Rack A › Shelf 1' in row['error']
        assert row['code'] == 'STORAGE_LOCATION_AMBIGUOUS'
