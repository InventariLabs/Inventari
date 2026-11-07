"""
Integration tests for product search API endpoint.

Tests verify correctness of:
- GET /api/v1/warehouse/product-search - search product templates by name/SKU/barcode
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.tests.integration._records import (
    hold as _hold,
)
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)


@pytest.mark.integration
class TestProductSearch:
    """Tests for product search endpoint."""

    def test_search_by_name_returns_matching_products(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Typing a name fragment returns matching products."""
        t1 = ProductTemplate(
            organization_id=doc_org.id, name='Piwo Tyskie', sku='WH-001'
        )
        t2 = ProductTemplate(
            organization_id=doc_org.id, name='Piwo Żywiec', sku='WH-002'
        )
        t3 = ProductTemplate(organization_id=doc_org.id, name='Chleb', sku='WH-003')
        db_session.add_all([t1, t2, t3])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'piwo'},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        names = [r['name'] for r in data]
        assert 'Piwo Tyskie' in names
        assert 'Piwo Żywiec' in names

    def test_search_by_sku_returns_exact_match_first(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Typing SKU returns exact match first."""
        t1 = ProductTemplate(
            organization_id=doc_org.id, name='Piwo Tyskie', sku='WH-00702'
        )
        t2 = ProductTemplate(
            organization_id=doc_org.id, name='WH-00702 Specjalny', sku='WH-00999'
        )
        db_session.add_all([t1, t2])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'WH-00702'},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data[0]['sku'] == 'WH-00702'
        assert data[0]['name'] == 'Piwo Tyskie'

    def test_search_by_barcode_returns_exact_match(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Typing barcode returns exact match."""
        t1 = ProductTemplate(
            organization_id=doc_org.id,
            name='Masło',
            barcode='5901234567890',
            sku='WH-005',
        )
        db_session.add(t1)
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': '5901234567890'},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) >= 1
        assert data[0]['barcode'] == '5901234567890'

    def test_search_returns_sku_barcode_uom_in_result(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Each result has sku, barcode, uom_id, uom_symbol fields."""
        t1 = ProductTemplate(
            organization_id=doc_org.id,
            name='Mleko',
            sku='WH-010',
            barcode='5901111111111',
        )
        db_session.add(t1)
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'Mleko'},
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()[0]
        assert 'sku' in result
        assert 'barcode' in result
        assert 'name' in result
        assert 'brand' in result
        assert 'uom_id' in result
        assert 'image_url' in result

    def test_search_empty_query_returns_400(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """Empty query returns 400."""
        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': ''},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_search_limits_results_to_10(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Max 10 results even when more matches exist."""
        templates = [
            ProductTemplate(
                organization_id=doc_org.id, name=f'Piwo {i}', sku=f'WH-{i:04d}'
            )
            for i in range(20)
        ]
        db_session.add_all(templates)
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'Piwo'},
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) <= 10

    def test_search_does_not_return_other_org_products(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Does not return products from another organization."""
        other_org = Organization(name='Other Org', enabled_modules=['core'])
        db_session.add(other_org)
        db_session.commit()
        t1 = ProductTemplate(
            organization_id=doc_org.id, name='Mój Produkt', sku='WH-100'
        )
        t2 = ProductTemplate(
            organization_id=other_org.id, name='Mój Produkt', sku='WH-200'
        )
        db_session.add_all([t1, t2])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'Mój Produkt'},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]['sku'] == 'WH-100'

    def test_quick_create_creates_stub_product_template(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """POST /product-search/quick-create creates a minimal template."""
        response = client.post(
            '/api/v1/warehouse/product-search/quick-create',
            headers=doc_auth_headers,
            json={'name': 'Nowy Produkt', 'barcode': '5909999999999'},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Nowy Produkt'
        assert data['barcode'] == '5909999999999'
        assert data['sku'] is not None
        assert data['is_stub'] is True

    def test_quick_create_requires_name(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """Missing name returns 422."""
        response = client.post(
            '/api/v1/warehouse/product-search/quick-create',
            headers=doc_auth_headers,
            json={'barcode': '5909999999999'},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_quick_create_rejects_duplicate_barcode(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Duplicate barcode returns 409."""
        t = ProductTemplate(
            organization_id=doc_org.id,
            name='Istniejący',
            barcode='5909999999999',
            sku='WH-001',
        )
        db_session.add(t)
        db_session.commit()

        response = client.post(
            '/api/v1/warehouse/product-search/quick-create',
            headers=doc_auth_headers,
            json={'name': 'Nowy', 'barcode': '5909999999999'},
        )
        assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.integration
class TestStockSearchForDispatch:
    """With a location, the search offers the stock a dispatch can actually take.

    The stock executor decrements a specific item and refuses a line without
    one, so a dispatch built from a catalogue search was refused by the form
    that offered it.
    """

    def test_location_search_returns_items_with_item_id(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        here = Item(
            name='Bolt M8 crate',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('7'),
        )
        elsewhere = Item(
            name='Bolt M8 spare',
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            quantity=Decimal('3'),
        )
        db_session.add_all([here, elsewhere])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'bolt', 'location_id': str(doc_source_location.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [r['name'] for r in data] == ['Bolt M8 crate']
        assert data[0]['item_id'] == str(here.id)
        assert Decimal(str(data[0]['available_quantity'])) == Decimal('7')

    def test_location_search_at_a_zone_offers_the_shelf_below(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
        doc_user: User,
    ) -> None:
        shelf = StorageLocation(
            organization_id=doc_org.id,
            name='Shelf under source',
            parent_id=doc_source_location.id,
            storage_type_id=doc_source_location.storage_type_id,
            created_by=doc_user.id,
        )
        db_session.add(shelf)
        db_session.flush()
        db_session.add(
            Item(
                name='Washer pack',
                organization_id=doc_org.id,
                storage_location_id=shelf.id,
                quantity=Decimal('12'),
            )
        )
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'washer', 'location_id': str(doc_source_location.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        assert [row['name'] for row in response.json()] == ['Washer pack']

    def test_catalogue_search_still_answers_without_a_location(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        db_session.add(
            ProductTemplate(
                organization_id=doc_org.id, name='Catalogue only', sku='CAT-1'
            )
        )
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'catalogue'},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]['item_id'] is None
        assert data[0]['product_template_id'] is not None


class TestStockSearchTellsRowsApart:
    """Two records of one product standing on one shelf are two rows the
    reader has to tell apart - and a row with nothing on it cannot back a
    dispatch line, so offering it builds a document that breaks later."""

    def test_a_transfer_row_carries_the_day_it_was_added(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """Two unmarked records of one product on one shelf differ by
        nothing but their quantity — the record's own day is the third
        thing the row says, so the picker is not a guessing game. It is the
        day the product card prints as "Added on" (the record's date, not
        an instant a browser would shift into its own zone), so the two
        screens cannot disagree about one record."""
        older = Item(
            name='Shelf twin',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('3'),
            # A moment past midnight UTC: the instant falls on the 16th, the
            # record's own day is the 15th.
            created_at=datetime(2026, 9, 16, 0, 30, 0),
            added_date=date(2026, 9, 15),
        )
        newer = Item(
            name='Shelf twin',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('4'),
            created_at=datetime(2026, 9, 17, 8, 0, 0),
            added_date=date(2026, 9, 17),
        )
        db_session.add_all([older, newer])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'twin', 'location_id': str(doc_source_location.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        added = {Decimal(str(r['available_quantity'])): r['added_date'] for r in data}
        assert added[Decimal('3')] == '2026-09-15'
        assert added[Decimal('4')] == '2026-09-17'
        assert [r['merged'] for r in data] == [False, False]

    def test_a_merged_row_names_no_record_day_and_says_it_is_merged(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """A merged row is a shelf total, not a record — it has no single
        landing date, and showing one would dress the group up as a row."""
        first = Item(
            name='Bulk twin',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('3'),
            created_at=datetime(2026, 9, 1, 8, 0, 0),
        )
        second = Item(
            name='Bulk twin',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('4'),
            created_at=datetime(2026, 9, 2, 8, 0, 0),
        )
        db_session.add_all([first, second])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'bulk',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]['added_date'] is None
        # The row names one record (a dispatch line needs it) but is the
        # total of two — the flag lets a reader not mistake it for a record.
        assert data[0]['merged'] is True

    def test_a_drained_row_is_not_offered_for_dispatch(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        drained = Item(
            name='Bolt M8 crate',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('0'),
        )
        stocked = Item(
            name='Bolt M8 crate',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('5'),
        )
        db_session.add_all([drained, stocked])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'bolt', 'location_id': str(doc_source_location.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [r['name'] for r in data] == ['Bolt M8 crate']
        assert Decimal(str(data[0]['available_quantity'])) == Decimal('5')

    def test_rows_of_one_product_carry_their_best_before(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """Two records of the same product on the same shelf used to read as
        the same line twice, with two numbers and nothing to tell them apart.
        The best-before is what makes the grocery pair two rows in the first
        place, so it rides along."""
        first = Item(
            name='Yogurt',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('10'),
            expiry_date=date(2026, 1, 1),
        )
        second = Item(
            name='Yogurt',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('2'),
            expiry_date=date(2026, 2, 1),
        )
        db_session.add_all([first, second])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'yogurt', 'location_id': str(doc_source_location.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        assert {row['expiry_date'] for row in data} == {
            '2026-01-01',
            '2026-02-01',
        }

    def test_interchangeable_records_are_one_row_with_the_shelf_total(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """Two records nothing on a row can tell apart - same product, same
        shelf, no date, no serial - are one choice to make, not two identical
        ones. The executor checks and pulls by product and shelf, so the one
        row carries the shelf's total."""
        first = Item(
            name='Confirm Test',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('3'),
        )
        second = Item(
            name='Confirm Test',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('4'),
        )
        db_session.add_all([first, second])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'confirm',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert Decimal(str(data[0]['available_quantity'])) == Decimal('7')

    def test_rows_name_the_shelf_they_stand_on(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """A scrap searches the whole organisation: same-named rows on different shelves used to
        differ by nothing but their quantity."""
        here = Item(
            name='Yogurt',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('4'),
            expiry_date=date(2026, 1, 1),
        )
        there = Item(
            name='Yogurt',
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            quantity=Decimal('10'),
            expiry_date=date(2026, 1, 1),
        )
        db_session.add_all([here, there])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'yogurt', 'stock': 'true'},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        shelves = {row['location_name'] for row in data}
        assert shelves == {doc_source_location.name, doc_target_location.name}

    def test_a_fully_reserved_shelf_is_not_offered(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """Another document's reservation claims the shelf's stock before the
        goods move, and the claim this line implies would be refused at
        confirmation. A shelf with nothing left to claim does not get to say
        "in stock"."""
        claimed_tpl = ProductTemplate(
            organization_id=doc_org.id, name='Claimed flour', sku='CLM-1'
        )
        free_tpl = ProductTemplate(
            organization_id=doc_org.id, name='Free flour', sku='CLM-2'
        )
        db_session.add_all([claimed_tpl, free_tpl])
        db_session.flush()
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            claimed_tpl,
            doc_source_location.id,
            Decimal('10'),
        )
        _hold(
            db_session,
            async_engine_fixture,
            claimed_tpl,
            doc_source_location.id,
            Decimal('10'),
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            free_tpl,
            doc_source_location.id,
            Decimal('3'),
        )
        _hold(
            db_session,
            async_engine_fixture,
            free_tpl,
            doc_source_location.id,
            Decimal('1'),
        )

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'flour', 'location_id': str(doc_source_location.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        assert [r['name'] for r in response.json()] == ['Free flour']

    def test_the_stock_floor_bites_before_the_page_is_cut(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """A page full of emptied records used to push the one record still
        holding goods off the page, and the dialog answered "nothing found"
        about a shelf that had them."""
        stocked = Item(
            name='Ration pack',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('3'),
            created_at=datetime(2026, 9, 1, 12, 0, 0),
        )
        drained = [
            Item(
                name='Ration pack',
                organization_id=doc_org.id,
                storage_location_id=doc_source_location.id,
                quantity=Decimal('0'),
                created_at=datetime(2026, 9, 2, 12, 0, i),
            )
            for i in range(12)
        ]
        db_session.add_all([stocked, *drained])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'ration',
                'location_id': str(doc_source_location.id),
                'limit': 10,
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert Decimal(str(data[0]['available_quantity'])) == Decimal('3')

    def test_a_transfer_keeps_the_records_one_by_one(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """A transfer moves the single record its line names — a merged row
        promising the shelf total would move one record and leave its twin
        behind. Without the merge flag the interchangeable records answer
        one by one, the way the transfer executor spends them."""
        first = Item(
            name='Confirm Test',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('3'),
        )
        second = Item(
            name='Confirm Test',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('4'),
        )
        db_session.add_all([first, second])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'confirm', 'location_id': str(doc_source_location.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        assert {Decimal(str(r['available_quantity'])) for r in data} == {
            Decimal('3'),
            Decimal('4'),
        }

    def test_the_merged_total_does_not_depend_on_the_page_cut(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """Four records of one piece on one shelf are four pieces of stock:
        the sum happens in SQL, before any page is cut, so a small limit
        shows the whole shelf instead of however much fitted on the page."""
        records = [
            Item(
                name='Pallet pin',
                organization_id=doc_org.id,
                storage_location_id=doc_source_location.id,
                quantity=Decimal('1'),
            )
            for _ in range(4)
        ]
        db_session.add_all(records)
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'pallet pin',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
                'limit': 2,
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert Decimal(str(data[0]['available_quantity'])) == Decimal('4')

    def test_a_merged_row_offers_what_the_shelf_can_serve(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """The merged row's number is the shelf's claimable total — another
        document's reservation comes off it, instead of the row repeating a
        gross sum a second document could not book."""
        template = ProductTemplate(
            organization_id=doc_org.id, name='Partly claimed', sku='PCL-1'
        )
        db_session.add(template)
        db_session.flush()
        for quantity in (Decimal('3'), Decimal('7')):
            _sow(
                db_session,
                async_engine_fixture,
                doc_org,
                template,
                doc_source_location.id,
                quantity,
            )
        _hold(
            db_session,
            async_engine_fixture,
            template,
            doc_source_location.id,
            Decimal('3'),
        )

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'partly claimed',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert Decimal(str(data[0]['available_quantity'])) == Decimal('7')

    def test_a_mixed_shelf_offers_its_stock_once(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """Dated records travel individually and the undated remainder sums
        into its own row — the merged row must cover only the records
        nothing tells apart, and never more than the shelf can serve. A
        group that also counted the dated records offered the same goods
        twice: the shelf below holds ten, the picker answered fourteen, and
        both rows booked together built a document for stock that was never
        there. The records carry a template and a quant, because every
        record created through the UI or the API does — without the quant
        the reservation layer that answers the endpoint never runs and the
        test walks the SQL alone."""
        template = ProductTemplate(
            organization_id=doc_org.id, name='Shelf mix', sku='SXM-1'
        )
        db_session.add(template)
        db_session.flush()
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            template,
            doc_source_location.id,
            Decimal('2'),
            expiry_date=date(2027, 1, 1),
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            template,
            doc_source_location.id,
            Decimal('2'),
            expiry_date=date(2027, 2, 1),
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            template,
            doc_source_location.id,
            Decimal('5'),
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            template,
            doc_source_location.id,
            Decimal('1'),
        )

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'shelf mix',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        offered = sorted(Decimal(str(row['available_quantity'])) for row in data)
        assert offered == [Decimal('2'), Decimal('2'), Decimal('6')]
        assert sum(offered, Decimal('0')) == Decimal('10')

    def test_a_single_row_offers_what_can_still_be_reserved(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """A dated record rides alone, and its gross count ignores the
        reservations already standing on the shelf: a row saying ten when
        three are spoken for builds a document that dies at confirmation.
        For the executors that pull across records the row says what the
        shelf can still serve, capped by the record itself."""
        template = ProductTemplate(
            organization_id=doc_org.id, name='Dated and claimed', sku='DCL-1'
        )
        db_session.add(template)
        db_session.flush()
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            template,
            doc_source_location.id,
            Decimal('10'),
            expiry_date=date(2027, 3, 1),
        )
        _hold(
            db_session,
            async_engine_fixture,
            template,
            doc_source_location.id,
            Decimal('3'),
        )

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'dated and claimed',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert Decimal(str(data[0]['available_quantity'])) == Decimal('7')

    def test_a_merged_row_stands_where_its_newest_record_stands(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """The group's representative is its newest record — the date the
        reader goes by puts the row on the page. Picking the representative
        by the text form of the id put an older record in front: the shelf
        answered a day late for no reason a reader could see. The ids here
        are pinned so the text-form maximum is the OLDER record on purpose:
        a seed taken by text order lands the merged row after the dated
        one, a seed taken by date keeps it in front."""
        db_session.add_all(
            [
                Item(
                    id=uuid.UUID('ffffffff-0000-0000-0000-000000000001'),
                    name='Text trap',
                    organization_id=doc_org.id,
                    storage_location_id=doc_source_location.id,
                    quantity=Decimal('5'),
                    created_at=datetime.now(UTC) - timedelta(days=5),
                ),
                Item(
                    id=uuid.UUID('00000000-0000-0000-0000-000000000002'),
                    name='Text trap',
                    organization_id=doc_org.id,
                    storage_location_id=doc_source_location.id,
                    quantity=Decimal('1'),
                    created_at=datetime.now(UTC) - timedelta(days=1),
                ),
                Item(
                    name='Text trap dated',
                    organization_id=doc_org.id,
                    storage_location_id=doc_source_location.id,
                    quantity=Decimal('3'),
                    expiry_date=date(2027, 5, 1),
                    created_at=datetime.now(UTC) - timedelta(days=3),
                ),
            ]
        )
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'text trap',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [row['expiry_date'] for row in data] == [None, '2027-05-01']

    def _seed_partly_reserved_shelf(
        self,
        db_session: Session,
        engine: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
        record_quantity: Decimal,
        record_count: int,
        quant_quantity: Decimal,
        reserved_quantity: Decimal,
    ) -> ProductTemplate:
        """One template, several dated records on one shelf; the records sum
        to the pool the old quant named, and a reservation eats into it."""
        assert record_quantity * record_count == quant_quantity, (
            'the records have to sum to the pool the test offers from'
        )
        template = ProductTemplate(
            organization_id=doc_org.id, name='Split pool', sku='SPP-1'
        )
        db_session.add(template)
        db_session.flush()
        base = date(2027, 1, 1)
        for index in range(record_count):
            _sow(
                db_session,
                engine,
                doc_org,
                template,
                doc_source_location.id,
                record_quantity,
                expiry_date=base + timedelta(days=30 * index),
            )
        if reserved_quantity:
            _hold(
                db_session,
                engine,
                template,
                doc_source_location.id,
                reserved_quantity,
            )
        return template

    def test_the_pool_is_split_between_rows_earliest_best_before_first(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """The claimable pool belongs to the shelf, not to each row: four
        dated records of three under a pool of two were each offered two —
        eight in all, neither the shelf's stock nor its pool. The rows are
        served earliest best-before first until the pool runs dry."""
        self._seed_partly_reserved_shelf(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_source_location,
            record_quantity=Decimal('3'),
            record_count=4,
            quant_quantity=Decimal('12'),
            reserved_quantity=Decimal('10'),
        )

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'split pool',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        offered = sum(
            (Decimal(str(row['available_quantity'])) for row in data),
            Decimal('0'),
        )
        assert offered == Decimal('2')
        assert all(Decimal(str(row['available_quantity'])) > 0 for row in data)

    def test_a_row_says_what_is_left_after_the_rows_before_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """Two dated rows of three under a pool of four: the nearest date
        takes its whole three, the farther one answers with the remainder —
        a number the reader can book, not a repeat of the pool. (The
        handout runs FEFO since the pool went to the nearest date; the
        answer's row order still follows the query, so the farther row
        stands first with the leftover.)"""
        self._seed_partly_reserved_shelf(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_source_location,
            record_quantity=Decimal('3'),
            record_count=2,
            quant_quantity=Decimal('6'),
            reserved_quantity=Decimal('2'),
        )

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'split pool',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [Decimal(str(row['available_quantity'])) for row in data] == [
            Decimal('1'),
            Decimal('3'),
        ]

    def test_a_record_without_a_best_before_is_served_last(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """Nothing on an undated record can spoil, so under a shortage the
        dated record is served first: a pool of four over an undated three
        and a dated three leaves the dated row whole and the undated one
        with the remainder, however the query happened to order them."""
        template = ProductTemplate(
            organization_id=doc_org.id, name='Undated last', sku='UDL-1'
        )
        db_session.add(template)
        db_session.flush()
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            template,
            doc_source_location.id,
            Decimal('3'),
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            template,
            doc_source_location.id,
            Decimal('3'),
            expiry_date=date(2027, 1, 1),
        )
        _hold(
            db_session,
            async_engine_fixture,
            template,
            doc_source_location.id,
            Decimal('2'),
        )

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'undated last',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        offered = {
            row['expiry_date']: Decimal(str(row['available_quantity']))
            for row in response.json()
        }
        assert offered == {'2027-01-01': Decimal('3'), None: Decimal('1')}

    def test_a_document_built_from_the_whole_offer_confirms(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """Every row the picker offers has been paid for out of the pool, so
        a document assembled from nothing but the offer reserves what it
        names and confirms — the offer of eight against a pool of two used
        to die at confirmation with stock the shelf never had."""
        self._seed_partly_reserved_shelf(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_source_location,
            record_quantity=Decimal('3'),
            record_count=4,
            quant_quantity=Decimal('12'),
            reserved_quantity=Decimal('10'),
        )

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'split pool',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        offer = response.json()
        assert offer, 'the shelf has a pool of two — the offer is not empty'

        create = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [
                    {
                        'item_id': row['item_id'],
                        'expected_quantity': float(row['available_quantity']),
                    }
                    for row in offer
                ],
            },
        )
        assert create.status_code == status.HTTP_201_CREATED, create.text
        doc_id = create.json()['id']
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

    def test_the_pool_goes_to_the_record_expiring_soonest(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """A shortage has to land on the record FEFO makes the picker take
        anyway. The handout ran in whatever order the query returned, so
        with three dated records and a pool of two the row that survived
        was the one good for months and the records spoiling first were
        gone from the screen altogether."""
        template = ProductTemplate(
            organization_id=doc_org.id, name='Frytki', sku='FEFO-1'
        )
        db_session.add(template)
        db_session.flush()
        for quantity, expiry, age_days in (
            (Decimal('4'), date(2026, 10, 5), 9),
            (Decimal('3'), date(2026, 10, 15), 5),
            (Decimal('5'), date(2027, 2, 21), 1),
        ):
            _sow(
                db_session,
                async_engine_fixture,
                doc_org,
                template,
                doc_source_location.id,
                quantity,
                expiry_date=expiry,
                backdate_days=age_days,
            )
        _hold(
            db_session,
            async_engine_fixture,
            template,
            doc_source_location.id,
            Decimal('10'),
        )

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'frytki',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [row['expiry_date'] for row in data] == ['2026-10-05']
        assert Decimal(str(data[0]['available_quantity'])) == Decimal('2')

    def test_a_short_pool_trims_the_farthest_date_first(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_source_location: StorageLocation,
    ) -> None:
        """When the pool serves several rows, the trim lands from the
        farthest date backwards: the nearest-dated row keeps its whole
        record, the farthest-dated one answers with the remainder. The
        query order had the same two rows share the pool in reverse, so
        the row closest to spoiling offered less than the freshest."""
        template = ProductTemplate(
            organization_id=doc_org.id, name='Frytki mrozone', sku='FEFO-2'
        )
        db_session.add(template)
        db_session.flush()
        for quantity, expiry, age_days in (
            (Decimal('4'), date(2026, 10, 5), 9),
            (Decimal('3'), date(2027, 1, 20), 1),
        ):
            _sow(
                db_session,
                async_engine_fixture,
                doc_org,
                template,
                doc_source_location.id,
                quantity,
                expiry_date=expiry,
                backdate_days=age_days,
            )
        _hold(
            db_session,
            async_engine_fixture,
            template,
            doc_source_location.id,
            Decimal('2'),
        )

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={
                'q': 'frytki mrozone',
                'location_id': str(doc_source_location.id),
                'merge': 'true',
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        by_expiry = {
            row['expiry_date']: Decimal(str(row['available_quantity'])) for row in data
        }
        assert by_expiry == {
            '2026-10-05': Decimal('4'),
            '2027-01-20': Decimal('1'),
        }
