"""A product's SKU, or an alphanumeric barcode it carries, scans like an EAN.

The barcode provider took eight to fourteen digits and nothing else, so a
small warehouse that prints its own Code 128 labels from the SKU scanned
into ``SCAN_UNRECOGNIZED`` -- while the product search, a few taps away,
found the very same code. One lookup now answers for the scan pages and for
the picking and receiving sessions, and a code that matches nothing stays an
unrecognized one so the screen can offer a search.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.core.scan_providers import BarcodeScanProvider
from app.models.item import Item
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def scan_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Alphanumeric Scan Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'printing'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def scan_user(
    real_async_db_session: AsyncSession, scan_org: Organization
) -> User:
    user = User(
        email=f'scan_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('Password123'),
        full_name='Alphanumeric Scan User',
        organization_id=scan_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


def _tag() -> str:
    return uuid.uuid4().hex[:8].upper()


async def _template(
    db: AsyncSession, org_id, *, sku: str | None = None, barcode: str | None = None
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org_id,
        name='Bearing 6204',
        sku=sku,
        barcode=barcode,
        weight_value=Decimal('0.1'),
    )
    db.add(template)
    await db.flush()
    return template


async def _stock(db: AsyncSession, org_id, user_id, template, quantity: str) -> Item:
    shelf = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name='Rack A',
        usage=LocationUsage.INTERNAL,
    )
    db.add(shelf)
    await db.flush()
    item = Item(
        organization_id=org_id,
        storage_location_id=shelf.id,
        name=template.name,
        quantity=Decimal(quantity),
        template_id=template.id,
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return item


async def _scan(client, user: User, code: str):
    return await client.get(
        f'/api/v1/labels/scan/{quote(code, safe="")}', headers=_auth(user)
    )


class TestTheScanPagesAnswerForASku:
    async def test_a_sku_answers_with_where_and_how_much(
        self, real_async_client, real_async_db_session, scan_user, scan_org
    ) -> None:
        sku = f'BRG{_tag()}'
        template = await _template(real_async_db_session, scan_org.id, sku=sku)
        await _stock(real_async_db_session, scan_org.id, scan_user.id, template, '7')
        await real_async_db_session.commit()

        scanned = await _scan(real_async_client, scan_user, sku)

        assert scanned.status_code == status.HTTP_200_OK, scanned.text
        body = scanned.json()
        assert body['status'] == 'product_stock'
        assert body['stock_summary']['total_quantity'] == 7.0
        assert body['stock_summary']['locations'] == ['Rack A']

    async def test_an_alphanumeric_barcode_on_the_template_answers_the_same(
        self, real_async_client, real_async_db_session, scan_user, scan_org
    ) -> None:
        code = f'X{_tag()}9'
        template = await _template(real_async_db_session, scan_org.id, barcode=code)
        await _stock(real_async_db_session, scan_org.id, scan_user.id, template, '3')
        await real_async_db_session.commit()

        scanned = await _scan(real_async_client, scan_user, code)

        assert scanned.status_code == status.HTTP_200_OK, scanned.text
        assert scanned.json()['stock_summary']['total_quantity'] == 3.0

    async def test_an_alphanumeric_barcode_on_a_record_without_a_template(
        self, real_async_client, real_async_db_session, scan_user, scan_org
    ) -> None:
        code = f'REC{_tag()}'
        shelf = StorageLocation(
            organization_id=scan_org.id,
            created_by=scan_user.id,
            name='Shelf 9',
            usage=LocationUsage.INTERNAL,
        )
        real_async_db_session.add(shelf)
        await real_async_db_session.flush()
        real_async_db_session.add(
            Item(
                organization_id=scan_org.id,
                storage_location_id=shelf.id,
                name='Loose hinge',
                quantity=Decimal('5'),
                barcode=code,
            )
        )
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        scanned = await _scan(real_async_client, scan_user, code)

        assert scanned.status_code == status.HTTP_200_OK, scanned.text
        assert scanned.json()['stock_summary']['total_quantity'] == 5.0

    async def test_another_organizations_sku_is_not_found(
        self, real_async_client, real_async_db_session, scan_user
    ) -> None:
        other = Organization(name='Other Org', enabled_modules=['core', 'items'])
        real_async_db_session.add(other)
        await real_async_db_session.flush()
        sku = f'FOREIGN{_tag()}'
        await _template(real_async_db_session, other.id, sku=sku)
        await real_async_db_session.commit()

        scanned = await _scan(real_async_client, scan_user, sku)

        assert scanned.status_code == status.HTTP_404_NOT_FOUND
        assert scanned.json()['detail']['code'] == 'SCAN_UNRECOGNIZED'

    async def test_a_code_that_matches_nothing_stays_unrecognized(
        self, real_async_client, scan_user
    ) -> None:
        # The screen turns this into an offer to search, which only works if
        # the server still says "nothing matched" rather than inventing a
        # "new product" answer for every string a scanner can read.
        scanned = await _scan(real_async_client, scan_user, f'NOPE{_tag()}')

        assert scanned.status_code == status.HTTP_404_NOT_FOUND
        assert scanned.json()['detail']['code'] == 'SCAN_UNRECOGNIZED'


class TestLocationAndLabelCodesStillWin:
    async def test_a_label_wins_over_a_product_sku_of_the_same_text(
        self, real_async_client, real_async_db_session, scan_user, scan_org
    ) -> None:
        code = f'AB-{_tag()}'
        await _template(real_async_db_session, scan_org.id, sku=code)
        real_async_db_session.add(
            LabelPool(
                organization_id=scan_org.id,
                created_by=scan_user.id,
                short_code=code,
                label_type='ITEM',
                is_assigned=False,
            )
        )
        await real_async_db_session.commit()

        scanned = await _scan(real_async_client, scan_user, code)

        assert scanned.status_code == status.HTTP_200_OK, scanned.text
        assert scanned.json()['status'] == 'unassigned'
        assert scanned.json()['action'] == 'show_quick_add'
        assert scanned.json()['stock_summary'] is None

    async def test_a_location_wins_over_a_product_sku_of_the_same_text(
        self, real_async_client, real_async_db_session, scan_user, scan_org
    ) -> None:
        code = f'LOC{_tag()}'
        await _template(real_async_db_session, scan_org.id, sku=code)
        real_async_db_session.add(
            StorageLocation(
                organization_id=scan_org.id,
                created_by=scan_user.id,
                name='Dock 4',
                short_code=code,
                usage=LocationUsage.INTERNAL,
            )
        )
        await real_async_db_session.commit()

        scanned = await _scan(real_async_client, scan_user, code)

        assert scanned.status_code == status.HTTP_200_OK, scanned.text
        assert scanned.json()['status'] == 'storage_context'


class TestTheSessionsUseTheSameLookup:
    async def test_a_sku_names_its_template(
        self, real_async_db_session, scan_org
    ) -> None:
        sku = f'SES{_tag()}'
        template = await _template(real_async_db_session, scan_org.id, sku=sku)
        await real_async_db_session.commit()

        found = await core_api.product_templates.lookup_by_barcode_async(
            real_async_db_session, scan_org.id, sku
        )

        assert found is not None
        assert found.id == template.id

    async def test_a_barcode_match_beats_a_sku_of_the_same_text(
        self, real_async_db_session, scan_org
    ) -> None:
        code = f'DUP{_tag()}'
        await _template(real_async_db_session, scan_org.id, sku=code)
        by_barcode = await _template(real_async_db_session, scan_org.id, barcode=code)
        await real_async_db_session.commit()

        found = await core_api.product_templates.lookup_by_barcode_async(
            real_async_db_session, scan_org.id, code
        )

        assert found is not None
        assert found.id == by_barcode.id

    async def test_a_printed_pool_label_names_the_template_of_its_record(
        self, real_async_db_session, scan_org, scan_user
    ) -> None:
        template = await _template(real_async_db_session, scan_org.id)
        item = await _stock(
            real_async_db_session, scan_org.id, scan_user.id, template, '2'
        )
        code = f'STM-{_tag()[:4]}'
        real_async_db_session.add(
            LabelPool(
                organization_id=scan_org.id,
                created_by=scan_user.id,
                short_code=code,
                label_type='ITEM',
                is_assigned=True,
                item_id=item.id,
            )
        )
        await real_async_db_session.commit()

        found = await core_api.product_templates.lookup_by_barcode_async(
            real_async_db_session, scan_org.id, code
        )

        assert found is not None
        assert found.id == template.id

    async def test_a_record_barcode_names_the_template_of_its_record(
        self, real_async_db_session, scan_org, scan_user
    ) -> None:
        template = await _template(real_async_db_session, scan_org.id)
        item = await _stock(
            real_async_db_session, scan_org.id, scan_user.id, template, '2'
        )
        item.barcode = f'REC{_tag()}'
        await real_async_db_session.commit()

        found = await core_api.product_templates.lookup_by_barcode_async(
            real_async_db_session, scan_org.id, item.barcode
        )

        assert found is not None
        assert found.id == template.id

    async def test_a_printed_label_beats_another_products_sku_of_the_same_text(
        self, real_async_db_session, scan_org, scan_user
    ) -> None:
        labelled = await _template(real_async_db_session, scan_org.id)
        item = await _stock(
            real_async_db_session, scan_org.id, scan_user.id, labelled, '2'
        )
        code = f'AB-{_tag()[:4]}'
        await _template(real_async_db_session, scan_org.id, sku=code)
        real_async_db_session.add(
            LabelPool(
                organization_id=scan_org.id,
                created_by=scan_user.id,
                short_code=code,
                label_type='ITEM',
                is_assigned=True,
                item_id=item.id,
            )
        )
        await real_async_db_session.commit()

        found = await core_api.product_templates.lookup_by_barcode_async(
            real_async_db_session, scan_org.id, code
        )

        assert found is not None
        assert found.id == labelled.id

    async def test_a_scan_address_is_unwrapped_before_the_lookup(
        self, real_async_db_session, scan_org
    ) -> None:
        sku = f'URL{_tag()}'
        template = await _template(real_async_db_session, scan_org.id, sku=sku)
        await real_async_db_session.commit()

        found = await core_api.product_templates.lookup_by_barcode_async(
            real_async_db_session, scan_org.id, f'https://inv.example.org/s/{sku}'
        )

        assert found is not None
        assert found.id == template.id

    async def test_the_provider_still_reads_digits_only_codes_as_new_products(
        self, real_async_db_session, scan_user
    ) -> None:
        result = await BarcodeScanProvider().handle(
            f'76{uuid.uuid4().int % 10**11:011d}', scan_user, real_async_db_session
        )

        assert result is not None
        assert result.message_key == 'scan:result.newProduct'
