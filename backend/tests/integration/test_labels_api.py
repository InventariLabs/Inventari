from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def lbl_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Labels Test Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'stats'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def lbl_user(real_async_db_session: AsyncSession, lbl_org: Organization) -> User:
    user = User(
        email=f'lbl_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Labels User',
        organization_id=lbl_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def lbl_storage_type(real_async_db_session: AsyncSession):
    from app.models.storage_type import StorageType

    st = StorageType(
        name='Labels Storage', type_code='LBL_STORAGE', behavior_mode='NONE'
    )
    real_async_db_session.add(st)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(st)
    return st


@pytest.fixture
async def lbl_storage_location(
    real_async_db_session: AsyncSession,
    lbl_org: Organization,
    lbl_storage_type,
    lbl_user: User,
):
    from app.models.storage_location import StorageLocation

    loc = StorageLocation(
        organization_id=lbl_org.id,
        created_by=lbl_user.id,
        storage_type_id=lbl_storage_type.id,
        name='Labels Shelf A',
    )
    real_async_db_session.add(loc)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(loc)
    return loc


@pytest.fixture
async def lbl_item(
    real_async_db_session: AsyncSession,
    lbl_org: Organization,
    lbl_storage_location,
):
    from app.models.item import Item

    item = Item(
        name='Label Test Item',
        organization_id=lbl_org.id,
        storage_location_id=lbl_storage_location.id,
        quantity=1,
    )
    real_async_db_session.add(item)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(item)
    return item


@pytest.mark.integration
@pytest.mark.asyncio
class TestLabelsAPI:
    """Tests for labels API endpoints."""

    async def test_generate_label_pool_success(self, real_async_client, lbl_user):
        """Tests successful label pool generation."""
        response = await real_async_client.post(
            '/api/v1/labels/pool/generate',
            headers=_auth(lbl_user),
            json={'count': 5},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert len(data) == 5
        assert all(label['short_code'].startswith('STM-') for label in data)
        assert all(not label['is_assigned'] for label in data)

    async def test_generate_label_pool_custom_prefix(self, real_async_client, lbl_user):
        """Tests successful label pool generation with custom prefix."""
        response = await real_async_client.post(
            '/api/v1/labels/pool/generate',
            headers=_auth(lbl_user),
            json={'count': 3, 'prefix': 'XYZ'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert len(data) == 3
        assert all(label['short_code'].startswith('XYZ-') for label in data)

    async def test_create_from_codes_success(self, real_async_client, lbl_user):
        """Create labels from explicit short_codes (e.g. equipment serials)."""
        response = await real_async_client.post(
            '/api/v1/labels/pool/from-codes',
            headers=_auth(lbl_user),
            json={
                'codes': [
                    {'short_code': 'ASD-1', 'description': 'Laptop A'},
                    {'short_code': 'ASD-2', 'description': 'Laptop B'},
                ],
                'label_type': 'EQUIPMENT',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert {lbl['short_code'] for lbl in data} == {'ASD-1', 'ASD-2'}
        assert all(lbl['description'] for lbl in data)

    async def test_a_taken_code_is_refused_with_its_own_code(
        self, real_async_client, lbl_user
    ):
        """The 409 stays, the code names the reason: the codes are taken."""
        body = {'codes': [{'short_code': 'ASD-9'}], 'label_type': 'EQUIPMENT'}
        url = '/api/v1/labels/pool/from-codes'
        created = await real_async_client.post(url, headers=_auth(lbl_user), json=body)
        assert created.status_code == status.HTTP_201_CREATED, created.text

        refused = await real_async_client.post(url, headers=_auth(lbl_user), json=body)

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        assert refused.json()['detail']['code'] == 'SHORT_CODES_TAKEN'

    async def test_get_label_pool(
        self, real_async_client, real_async_db_session, lbl_user, lbl_org
    ):
        """Tests fetching label pool."""
        for i in range(3):
            label = LabelPool(
                short_code=f'STM-T{i}',
                organization_id=lbl_org.id,
                created_by=lbl_user.id,
            )
            real_async_db_session.add(label)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/labels/pool', headers=_auth(lbl_user)
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) >= 3
        assert data['total'] >= 3
        assert 'limit' in data and 'offset' in data and 'has_more' in data

    async def test_get_label_pool_paginated_and_status_filter(
        self, real_async_client, real_async_db_session, lbl_user, lbl_org
    ):
        """Pool endpoint supports offset/limit pagination and status filter."""
        from datetime import UTC, datetime

        free = LabelPool(
            short_code='STM-F1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
        )
        printed = LabelPool(
            short_code='STM-P1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            printed_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        real_async_db_session.add_all([free, printed])
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/labels/pool',
            params={'limit': 1, 'offset': 0},
            headers=_auth(lbl_user),
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) == 1
        assert data['total'] >= 2
        assert data['has_more'] is True

        free_response = await real_async_client.get(
            '/api/v1/labels/pool',
            params={'status': 'FREE'},
            headers=_auth(lbl_user),
        )
        assert free_response.status_code == status.HTTP_200_OK
        free_data = free_response.json()
        assert all(not lbl['is_assigned'] for lbl in free_data['items'])
        assert any(lbl['short_code'] == 'STM-F1' for lbl in free_data['items'])
        assert not any(lbl['printed_at'] is not None for lbl in free_data['items'])

        printed_response = await real_async_client.get(
            '/api/v1/labels/pool',
            params={'status': 'PRINTED'},
            headers=_auth(lbl_user),
        )
        printed_data = printed_response.json()
        assert all(lbl['printed_at'] for lbl in printed_data['items'])

    async def test_get_pool_stats(
        self, real_async_client, real_async_db_session, lbl_user, lbl_org
    ):
        """Tests label pool statistics."""
        l1 = LabelPool(
            short_code='STM-S1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=True,
        )
        l2 = LabelPool(
            short_code='STM-S2',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=False,
        )
        l3 = LabelPool(
            short_code='STM-S3',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=False,
        )
        real_async_db_session.add_all([l1, l2, l3])
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/labels/pool/stats', headers=_auth(lbl_user)
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['assigned'] >= 1
        assert data['unassigned'] >= 2
        assert data['total'] >= 3

    async def test_scan_label_unassigned(
        self, real_async_client, real_async_db_session, lbl_user, lbl_org
    ):
        """Tests scanning an unassigned label."""
        label = LabelPool(
            short_code='STM-SCAN1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/labels/scan/STM-SCAN1', headers=_auth(lbl_user)
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['status'] == 'unassigned'
        assert data['action'] == 'show_quick_add'
        assert data['label_code'] == 'STM-SCAN1'

    async def test_scan_label_assigned(
        self, real_async_client, real_async_db_session, lbl_user, lbl_org, lbl_item
    ):
        """Tests scanning an assigned label."""
        label = LabelPool(
            short_code='STM-SCAN2',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=True,
            item_id=lbl_item.id,
        )
        real_async_db_session.add(label)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/labels/scan/STM-SCAN2', headers=_auth(lbl_user)
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['status'] == 'assigned'
        assert data['action'] == 'show_quick_actions'
        assert data['item']['id'] == str(lbl_item.id)

    async def test_one_scan_moves_the_count_by_one(
        self, real_async_client, real_async_db_session, lbl_user, lbl_org
    ):
        """A scan is one read of the label, so the counter moves by one.

        The counter is written twice in one pass: the atomic UPDATE bumps
        the row, and the ORM mirrors the same increment on the in-session
        object. The second write only reaches the database with the
        request's commit, so a read through the pool after the response is
        what makes the difference visible.
        """
        from sqlalchemy import select

        label = LabelPool(
            short_code='STM-COUNT1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.commit()

        for expected in (1, 2):
            response = await real_async_client.get(
                '/api/v1/labels/scan/STM-COUNT1', headers=_auth(lbl_user)
            )
            assert response.status_code == status.HTTP_200_OK

            count = (
                await real_async_db_session.execute(
                    select(LabelPool.scan_count).where(LabelPool.id == label.id)
                )
            ).scalar_one()
            assert count == expected

    async def test_assign_label_success(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_location,
    ):
        """Tests successful label assignment to a new item."""
        from sqlalchemy import select

        from app.models.uom import Uom

        label = LabelPool(
            short_code='STM-ASGN1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.commit()

        # Half a kilogram is a quantity, half a piece is not: the scan is
        # measured in the unit it lands with, so the request names one
        # explicitly. The field is ``uom_id``; an unknown ``unit`` key was
        # silently dropped and left the default to answer for it.
        kg = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'kg'))
        ).first()

        response = await real_async_client.post(
            '/api/v1/labels/scan/STM-ASGN1/assign',
            headers=_auth(lbl_user),
            json={
                'name': 'Scanned Product',
                'location_id': str(lbl_storage_location.id),
                'quantity': 2.5,
                'uom_id': str(kg.id),
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'Scanned Product'
        assert data['uom']['symbol'] == 'kg'
        assert float(data['quantity']) == 2.5

        await real_async_db_session.refresh(label)
        assert label.is_assigned
        assert label.item_id is not None

    async def test_a_pool_label_keeps_the_product_code_the_form_sent(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_location,
    ):
        """A blank label is not a product code, so after scanning one the form
        offers the code field — and what is typed or generated there is the
        product's code. The request used to have no such field: the code was
        dropped under a 200, and a scan of it found nothing."""
        real_async_db_session.add(
            LabelPool(
                short_code='STM-CODE1',
                organization_id=lbl_org.id,
                created_by=lbl_user.id,
                is_assigned=False,
            )
        )
        await real_async_db_session.commit()

        response = await real_async_client.post(
            '/api/v1/labels/scan/STM-CODE1/assign',
            headers=_auth(lbl_user),
            json={
                'name': 'Bench vice',
                'location_id': str(lbl_storage_location.id),
                'quantity': 1,
                'barcode': '2000000000213',
            },
        )
        assert response.status_code == status.HTTP_200_OK, response.text

        rescan = await real_async_client.get(
            '/api/v1/labels/scan/2000000000213', headers=_auth(lbl_user)
        )
        assert rescan.status_code == status.HTTP_200_OK, rescan.text
        assert rescan.json()['status'] == 'product_stock'
        assert [i['id'] for i in rescan.json()['stock_summary']['items']] == [
            response.json()['id']
        ]

    async def test_assign_label_with_uom_eager_loaded(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_location,
    ):
        """Regression: assigning a label with a uom_id must not trigger a lazy
        load (MissingGreenlet) during response serialization."""
        from app.models.uom import Uom, UomCategory

        category = UomCategory(organization_id=lbl_org.id, name='Weight')
        real_async_db_session.add(category)
        await real_async_db_session.flush()
        uom = Uom(
            organization_id=lbl_org.id,
            category_id=category.id,
            name='kilogram',
            symbol='kg',
            is_reference=True,
        )
        real_async_db_session.add(uom)
        label = LabelPool(
            short_code='STM-UOM1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.commit()

        response = await real_async_client.post(
            '/api/v1/labels/scan/STM-UOM1/assign',
            headers=_auth(lbl_user),
            json={
                'name': 'Uom Item',
                'location_id': str(lbl_storage_location.id),
                'quantity': 1.0,
                'uom_id': str(uom.id),
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['uom'] is not None
        assert data['uom']['symbol'] == 'kg'

    async def test_a_fractional_scan_on_a_whole_number_unit_is_refused(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_location,
    ):
        """The scan is one more door into the same warehouse, and the
        precision gate the manual create answers to answers the same way
        here: a unit whose step is a whole number does not accept halves,
        whichever door brought the quantity in."""
        from sqlalchemy import select

        from app.models.item import Item
        from app.models.uom import Uom, UomCategory

        category = UomCategory(organization_id=lbl_org.id, name='Count')
        real_async_db_session.add(category)
        await real_async_db_session.flush()
        whole = Uom(
            organization_id=lbl_org.id,
            category_id=category.id,
            name='box',
            symbol='box',
            rounding=1.0,
        )
        real_async_db_session.add(whole)
        label = LabelPool(
            short_code='STM-FRAC1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.commit()

        response = await real_async_client.post(
            '/api/v1/labels/scan/STM-FRAC1/assign',
            headers=_auth(lbl_user),
            json={
                'name': 'Half A Box',
                'location_id': str(lbl_storage_location.id),
                'quantity': 2.5,
                'uom_id': str(whole.id),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        left_over = await real_async_db_session.scalars(
            select(Item).where(Item.name == 'Half A Box')
        )
        assert left_over.first() is None

    async def test_a_scan_claimed_by_a_module_carries_its_owner(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_location,
    ):
        """The manual create stamps ``module_name`` from the record's
        namespaces; a scan building the same row without it produced records
        no module list could find."""
        from sqlalchemy import select

        from app.models.item import Item

        label = LabelPool(
            short_code='STM-OWNR1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.commit()

        response = await real_async_client.post(
            '/api/v1/labels/scan/STM-OWNR1/assign',
            headers=_auth(lbl_user),
            json={
                'name': 'Scanned ThinkPad',
                'location_id': str(lbl_storage_location.id),
                'quantity': 1,
                'metadata': {'equipment': {'asset_tag': 'IT-SCAN-1'}},
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        created = await real_async_db_session.scalars(
            select(Item).where(Item.name == 'Scanned ThinkPad')
        )
        assert created.first().module_name == 'equipment'

    async def test_a_scanned_record_answers_for_its_currency(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_location,
    ):
        """The organization's currency fills a record left without one on
        the manual create; the scan built the same row and left the column
        empty, so two reads of one shelf disagreed about money."""
        from sqlalchemy import select

        from app.models.item import Item

        label = LabelPool(
            short_code='STM-CURR1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.commit()

        response = await real_async_client.post(
            '/api/v1/labels/scan/STM-CURR1/assign',
            headers=_auth(lbl_user),
            json={
                'name': 'Scanned With A Price',
                'location_id': str(lbl_storage_location.id),
                'quantity': 1,
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        created = await real_async_db_session.scalars(
            select(Item).where(Item.name == 'Scanned With A Price')
        )
        assert created.first().currency == lbl_org.currency

    async def test_export_png_unauthorized(self, real_async_client):
        """Tests export endpoint without auth."""
        response = await real_async_client.get('/api/v1/labels/pool/export/png')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_get_label_pool_names_what_the_assigned_item_is(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_location,
    ):
        """The row says what the label points at, not only what it printed for.

        A generic label assigned to an asset used to describe itself as a
        product everywhere — the assignment line carried what the item is,
        which the label's own purpose never knew.
        """
        from app.models.category import Category
        from app.models.item import Item

        equipment_cat = Category(
            name='LBL Laptop',
            code='LBL_LAPTOP',
            context_tag='equipment',
            organization_id=lbl_org.id,
        )
        real_async_db_session.add(equipment_cat)
        await real_async_db_session.flush()

        asset = Item(
            name='LBL Asset',
            organization_id=lbl_org.id,
            storage_location_id=lbl_storage_location.id,
            category_id=equipment_cat.id,
            quantity=1,
        )
        real_async_db_session.add(asset)
        await real_async_db_session.flush()

        assigned = LabelPool(
            short_code='STM-A9',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            item_id=asset.id,
            is_assigned=True,
        )
        real_async_db_session.add(assigned)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/labels/pool', headers=_auth(lbl_user)
        )
        assert response.status_code == status.HTTP_200_OK
        row = next(
            lbl for lbl in response.json()['items'] if lbl['short_code'] == 'STM-A9'
        )
        assert row['is_assigned'] is True
        assert row['assigned_item_name'] == 'LBL Asset'
        assert row['assigned_item_context_tag'] == 'equipment'


class TestTheScanAnswersForWhatItCreates:
    """The scan is one more door into the same warehouse, so the gates the
    manual create answers to answer the scan too: an archived shelf is no
    back door, a category's field contract binds whatever rode in on the
    scan, a code belongs to the product rather than exploding on the
    uniqueness index, and the record the scan mints exists in the
    organization's journal."""

    async def _scan(
        self,
        real_async_client,
        lbl_user: User,
        storage_location_id,
        *,
        name: str = 'Scan Gate Item',
        barcode: str | None = None,
        category_id=None,
        metadata: dict | None = None,
        expiry_date: str | None = None,
    ):
        payload = {
            'name': name,
            'location_id': str(storage_location_id),
            'quantity': 1,
        }
        if barcode:
            payload['barcode'] = barcode
        if category_id:
            payload['category_id'] = str(category_id)
        if metadata is not None:
            payload['metadata'] = metadata
        if expiry_date:
            payload['expiry_date'] = expiry_date
        return await real_async_client.post(
            '/api/v1/labels/scan/STM-GATE1/assign',
            headers=_auth(lbl_user),
            json=payload,
        )

    async def _gate_label(self, real_async_db_session, lbl_org, lbl_user):
        label = LabelPool(
            short_code='STM-GATE1',
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.commit()
        return label

    async def test_a_scan_cannot_store_on_an_archived_location(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_type,
    ):
        from app.models.storage_location import StorageLocation

        loc = StorageLocation(
            organization_id=lbl_org.id,
            created_by=lbl_user.id,
            storage_type_id=lbl_storage_type.id,
            name='Closed Shelf',
            settings={'archived': True},
        )
        real_async_db_session.add(loc)
        await self._gate_label(real_async_db_session, lbl_org, lbl_user)
        await real_async_db_session.commit()

        response = await self._scan(
            real_async_client, lbl_user, loc.id, name='On the closed shelf'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text

    async def test_a_scan_answers_for_the_categorys_field_contract(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_location,
    ):
        from app.models.category import Category

        cat = Category(
            organization_id=lbl_org.id,
            name='Scan Gate Dairy',
            field_definitions=[
                {
                    'key': 'lactose_free',
                    'label': 'Lactose free',
                    'type': 'select',
                    'options': ['No', 'Yes'],
                }
            ],
        )
        real_async_db_session.add(cat)
        await self._gate_label(real_async_db_session, lbl_org, lbl_user)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(cat)

        response = await self._scan(
            real_async_client,
            lbl_user,
            lbl_storage_location.id,
            name='Maybe Lactose',
            category_id=cat.id,
            metadata={'lactose_free': 'Maybe'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text

    async def test_a_second_scan_of_the_same_code_does_not_explode(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_location,
    ):
        """The everyday grocery flow: the same product, a new delivery, a
        new best-before. The code belongs to the product (the template),
        so the second record stays bare instead of dying on the uniqueness
        index."""
        from sqlalchemy import select

        from app.models.item import Item

        await self._gate_label(real_async_db_session, lbl_org, lbl_user)
        await real_async_db_session.commit()

        first = await self._scan(
            real_async_client,
            lbl_user,
            lbl_storage_location.id,
            name='Scan Gate Yogurt',
            barcode='5901234123457',
            expiry_date='2026-01-01',
        )
        assert first.status_code == status.HTTP_200_OK, first.text

        # The second delivery has no new label — the delivery is scanned by
        # the product's own barcode, which is exactly the route that used to
        # hit the uniqueness index.
        second = await real_async_client.post(
            '/api/v1/labels/scan/5901234123457/assign',
            headers=_auth(lbl_user),
            json={
                'name': 'Scan Gate Yogurt',
                'location_id': str(lbl_storage_location.id),
                'quantity': 1,
                'barcode': '5901234123457',
                'expiry_date': '2026-02-01',
            },
        )
        assert second.status_code == status.HTTP_200_OK, second.text
        rows = await real_async_db_session.scalars(
            select(Item).where(Item.name == 'Scan Gate Yogurt')
        )
        names = rows.all()
        assert len(names) == 2
        assert all(row.barcode is None for row in names)

    async def test_a_scanned_record_lands_in_the_organization_journal(
        self,
        real_async_client,
        real_async_db_session,
        lbl_user,
        lbl_org,
        lbl_storage_location,
    ):
        from sqlalchemy import select

        from app.models.audit_log import AuditAction, AuditLog, AuditTargetType

        await self._gate_label(real_async_db_session, lbl_org, lbl_user)
        await real_async_db_session.commit()

        response = await self._scan(
            real_async_client, lbl_user, lbl_storage_location.id
        )
        assert response.status_code == status.HTTP_200_OK, response.text

        entries = await real_async_db_session.scalars(
            select(AuditLog).where(
                AuditLog.organization_id == lbl_org.id,
                AuditLog.action == AuditAction.CREATE,
                AuditLog.target_type == AuditTargetType.ITEM,
                AuditLog.target_id == response.json()['id'],
            )
        )
        assert entries.first() is not None
