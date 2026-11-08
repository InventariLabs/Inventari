"""
Integration tests for Logistics 2.0 logic (Product Templates, UOM).
"""

import pytest
from fastapi import status
from sqlalchemy import select

from app.core.product_template_metadata import get_template_nutrition
from app.models.item import Item
from app.models.product_template import ProductTemplate


@pytest.mark.integration
class TestProductTemplateLogic:
    """Tests for Product Template automatic creation and linking."""

    def test_create_item_creates_template_by_barcode(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """Test that creating an item with barcode creates a ProductTemplate."""
        barcode = '123456789'
        name = 'Test Product Barcode'

        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': name,
                'barcode': barcode,
                'location_id': str(test_storage_location.id),
                'quantity': 1,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        item_id = response.json()['id']

        # Verify Item has template_id
        item = db_session.scalars(select(Item).where(Item.id == item_id)).first()
        assert item.template_id is not None

        # Verify Template exists
        template = db_session.scalars(
            select(ProductTemplate).where(ProductTemplate.id == item.template_id)
        ).first()
        assert template is not None
        assert template.barcode == barcode
        assert template.name == name

    def test_create_item_with_the_same_barcode_shares_the_template(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """A scanned code is the product's, so the second record carrying
        it is more stock of the same product: both records land on the
        template the code names, and the records themselves stay bare (the
        record-level column keeps only the one-off case)."""
        barcode = '987654321'

        # 1. Create first item
        first = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Product A',
                'barcode': barcode,
                'location_id': str(test_storage_location.id),
            },
        )
        assert first.status_code == status.HTTP_201_CREATED

        # 2. Create second item with the same barcode — same product
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Product B (Same Barcode)',
                'barcode': barcode,
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        template = db_session.scalars(
            select(ProductTemplate).where(ProductTemplate.barcode == barcode)
        ).first()
        assert template is not None
        assert template.barcode == barcode
        first_item = db_session.scalars(
            select(Item).where(Item.id == first.json()['id'])
        ).first()
        second_item = db_session.scalars(
            select(Item).where(Item.id == response.json()['id'])
        ).first()
        assert first_item.template_id == template.id
        assert second_item.template_id == template.id
        # The records stay bare: the code lives on the catalogue row.
        assert first_item.barcode is None
        assert second_item.barcode is None

    def test_create_item_creates_template_by_name(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """Test that creating an item without barcode creates template by name."""
        name = 'Unique Product Name'
        brand = 'Unique Brand'

        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': name,
                'brand': brand,
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        item_id = response.json()['id']
        item = db_session.scalars(select(Item).where(Item.id == item_id)).first()

        assert item.template_id is not None
        template = db_session.scalars(
            select(ProductTemplate).where(ProductTemplate.id == item.template_id)
        ).first()
        assert template.name == name
        assert template.brand == brand

    def test_create_item_reuses_template_by_name(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """Test reuse by name."""
        name = 'Reuse Name'

        # 1. Create first
        client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': name,
                'location_id': str(test_storage_location.id),
            },
        )

        template_first = db_session.scalars(
            select(ProductTemplate).where(ProductTemplate.name == name)
        ).first()
        assert template_first is not None

        # 2. Create second
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': name,
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        item_2_id = response.json()['id']
        item_2 = db_session.scalars(select(Item).where(Item.id == item_2_id)).first()

        assert item_2.template_id == template_first.id

    def test_consume_moves_to_virtual_location(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """Test that consuming an item moves it to virtual location."""
        # Create item
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'To Consume',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
            },
        )
        item_id = response.json()['id']

        # Consume full quantity
        response = client.patch(
            f'/api/v1/items/{item_id}/consume',
            headers=auth_headers,
            json={'quantity': 1, 'reason': 'eaten'},
        )
        assert response.status_code == status.HTTP_200_OK

        # Verify location
        from app.models.item import Item
        from app.models.storage_location import LocationUsage, StorageLocation

        item = db_session.scalars(select(Item).where(Item.id == item_id)).first()

        # Check if location has usage=CUSTOMER (Consumed)
        location = db_session.scalars(
            select(StorageLocation).where(
                StorageLocation.id == item.storage_location_id
            )
        ).first()

        # DEBUG: Check storage types if failure happens
        if location.usage != LocationUsage.CUSTOMER:
            from app.models.storage_type import StorageType

            types = list(db_session.scalars(select(StorageType)).all())
            print(f'Available Storage Types: {[t.type_code for t in types]}')
            print(f'Current Location: {location.name} (Usage: {location.usage})')

        assert location.usage == LocationUsage.CUSTOMER
        assert 'Consumed' in location.name

    @pytest.mark.asyncio
    async def test_create_item_normalizes_metadata_and_units(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Test that ItemService correctly normalizes metadata and handles unit-based weight."""
        from decimal import Decimal

        from app.models.uom import Uom
        from app.schemas.item import ItemCreate
        from app.services.items import (
            create_item,
        )

        # 1. Test Case: kg unit (weight should equal quantity). The request
        # names it: a record that names no unit is measured in pieces, and
        # pieces count whole.
        kg = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'kg'))
        ).first()
        item_in = ItemCreate(
            name='Mąka',
            location_id=async_test_storage_location.id,
            quantity=Decimal('1.5'),
            uom_id=kg.id,
            metadata={'source': 'test-suite'},
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)

        assert item.name == 'Mąka'
        assert float(item.quantity) == 1.5
        # metadata should be in meta_data column
        assert item.meta_data == {'source': 'test-suite'}

        # 2. Test Case: metadata normalization from schema to model
        item_in_2 = ItemCreate(
            name='Chleb',
            location_id=async_test_storage_location.id,
            quantity=Decimal('1'),
            metadata={'is_fresh': True},
        )

        item2 = await create_item(real_async_db_session, item_in_2, async_test_user)
        assert item2.meta_data == {'is_fresh': True}


@pytest.mark.integration
class TestProductTemplateNutritionFromOFF:
    """Tests for automatic nutrition_info population from OFF metadata."""

    @pytest.mark.asyncio
    async def test_create_item_with_off_metadata_populates_nutrition_info(
        self, real_async_db_session, async_test_storage_location, async_test_user
    ):
        """Item from OFF scan should populate meta_data['nutrition']."""
        from decimal import Decimal

        from app.schemas.item import ItemCreate
        from app.services.items import (
            create_item,
        )

        item_in = ItemCreate(
            name='Płatki owsiane OFF',
            barcode='5900111111119',
            location_id=async_test_storage_location.id,
            quantity=Decimal('1'),
            metadata={
                'off_enriched': True,
                'nutrition': {
                    'energy_kcal': 350.0,
                    'proteins': 12.0,
                    'carbohydrates': 58.0,
                    'fat': 7.0,
                    'fiber': 8.0,
                    'sugars': 1.5,
                    'salt': 0.02,
                },
            },
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)

        template = (
            await real_async_db_session.scalars(
                select(ProductTemplate).where(ProductTemplate.id == item.template_id)
            )
        ).first()

        assert template is not None
        nutrition = get_template_nutrition(template)
        assert nutrition is not None
        assert nutrition['calories_kcal'] == 350.0
        assert nutrition['protein_g'] == 12.0
        assert nutrition['carbs_g'] == 58.0
        assert nutrition['fat_g'] == 7.0
        assert nutrition['fiber_g'] == 8.0
        assert nutrition['salt_g'] == 0.02

    @pytest.mark.asyncio
    async def test_create_item_without_off_metadata_leaves_nutrition_info_none(
        self, real_async_db_session, async_test_storage_location, async_test_user
    ):
        """Item without OFF metadata leaves meta_data['nutrition'] empty."""
        from decimal import Decimal

        from app.schemas.item import ItemCreate
        from app.services.items import (
            create_item,
        )

        item_in = ItemCreate(
            name='Produkt bez OFF',
            barcode='5900222222226',
            location_id=async_test_storage_location.id,
            quantity=Decimal('1'),
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)

        template = (
            await real_async_db_session.scalars(
                select(ProductTemplate).where(ProductTemplate.id == item.template_id)
            )
        ).first()

        assert template is not None
        assert get_template_nutrition(template) is None

    @pytest.mark.asyncio
    async def test_second_item_with_same_name_does_not_overwrite_nutrition(
        self, real_async_db_session, async_test_storage_location, async_test_user
    ):
        """A second item reusing the template by name (no barcode to match
        by) must not overwrite the nutrition the template already carries."""
        from decimal import Decimal

        from app.schemas.item import ItemCreate
        from app.services.items import (
            create_item,
        )

        name = 'Makaron pełnoziarnisty'

        # 1. Create with OFF data
        item_in_1 = ItemCreate(
            name=name,
            barcode='5900333333333',
            location_id=async_test_storage_location.id,
            quantity=Decimal('1'),
            metadata={
                'off_enriched': True,
                'nutrition': {'energy_kcal': 340.0, 'proteins': 13.0},
            },
        )
        item1 = await create_item(real_async_db_session, item_in_1, async_test_user)

        template_before = (
            await real_async_db_session.scalars(
                select(ProductTemplate).where(ProductTemplate.id == item1.template_id)
            )
        ).first()
        nutrition_before = get_template_nutrition(template_before)
        assert nutrition_before is not None
        assert nutrition_before['calories_kcal'] == 340.0

        # 2. Create a second item with the same name and no barcode — the
        # resolver matches the template by name — carrying no nutrition data.
        # Reuse must leave what the template already holds untouched.
        item_in_2 = ItemCreate(
            name=name,
            location_id=async_test_storage_location.id,
            quantity=Decimal('2'),
        )
        item2 = await create_item(real_async_db_session, item_in_2, async_test_user)

        # The name matched: same template again, nutrition still the first
        # record's values.
        assert item2.template_id == item1.template_id
        template_after = (
            await real_async_db_session.scalars(
                select(ProductTemplate).where(ProductTemplate.id == item1.template_id)
            )
        ).first()
        await real_async_db_session.refresh(template_after)
        nutrition_after = get_template_nutrition(template_after)
        assert nutrition_after['calories_kcal'] == 340.0
        assert nutrition_after['protein_g'] == 13.0


@pytest.mark.integration
class TestScanFiguresReachAnExistingProduct:
    """A scan onto a product that already exists gives that product its figures.

    A recipe reads the product's nutrition, not the record's, so figures left
    on the record alone never reach it.
    """

    _SCAN = {
        'source': 'local_off_db',
        'off_enriched': True,
        'nutrition': {'energy_kcal': 321.0, 'proteins': 12.0},
    }

    async def _scan_onto(self, db, user, storage_location, template, *, named=True):
        from decimal import Decimal

        from app.schemas.item import ItemCreate
        from app.services.items import create_item

        item = await create_item(
            db,
            ItemCreate(
                name=template.name,
                template_id=template.id if named else None,
                location_id=storage_location.id,
                quantity=Decimal('1'),
                metadata=self._SCAN,
            ),
            user,
        )
        assert item.template_id == template.id
        await db.refresh(template)

    @pytest.mark.asyncio
    async def test_a_cleared_nutrition_panel_takes_the_figures(
        self, real_async_db_session, async_test_storage_location, async_test_user
    ):
        """Clearing every field in the editor stores ``{'nutrition': {}}``."""
        template = ProductTemplate(
            organization_id=async_test_user.organization_id,
            name='Own cleared flour',
            meta_data={'nutrition': {}},
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        await self._scan_onto(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            template,
        )

        assert get_template_nutrition(template) == {
            'calories_kcal': 321.0,
            'protein_g': 12.0,
        }

    @pytest.mark.asyncio
    async def test_the_matched_product_takes_the_figures_too(
        self, real_async_db_session, async_test_storage_location, async_test_user
    ):
        """No ``template_id``: the product the name matches is the one given."""
        template = ProductTemplate(
            organization_id=async_test_user.organization_id,
            name='Own matched flour',
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        await self._scan_onto(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            template,
            named=False,
        )

        assert get_template_nutrition(template) == {
            'calories_kcal': 321.0,
            'protein_g': 12.0,
        }

    @pytest.mark.asyncio
    async def test_own_product_without_figures_takes_them(
        self, real_async_db_session, async_test_storage_location, async_test_user
    ):
        template = ProductTemplate(
            organization_id=async_test_user.organization_id, name='Own plain flour'
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        await self._scan_onto(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            template,
        )

        nutrition = get_template_nutrition(template)
        assert nutrition == {'calories_kcal': 321.0, 'protein_g': 12.0}

    @pytest.mark.asyncio
    async def test_figures_already_on_the_product_stay(
        self, real_async_db_session, async_test_storage_location, async_test_user
    ):
        template = ProductTemplate(
            organization_id=async_test_user.organization_id,
            name='Own typed flour',
            meta_data={'nutrition': {'calories_kcal': 100.0}},
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        await self._scan_onto(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            template,
        )

        assert get_template_nutrition(template) == {'calories_kcal': 100.0}

    @pytest.mark.asyncio
    async def test_shared_product_is_never_written_to(
        self, real_async_db_session, async_test_storage_location, async_test_user
    ):
        template = ProductTemplate(organization_id=None, name='Shared plain flour')
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        await self._scan_onto(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            template,
        )

        assert get_template_nutrition(template) is None


@pytest.mark.integration
class TestReductionReasonIsRecorded:
    """The reason a quantity went down survives the request that carried it."""

    def _create_item(self, client, auth_headers, storage_location, name):
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': name,
                'location_id': str(storage_location.id),
                'quantity': 2,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()['id']

    def _history(self, db_session, item_id):
        from app.models.item_history import ItemHistory

        return list(
            db_session.scalars(
                select(ItemHistory).where(ItemHistory.item_id == item_id)
            ).all()
        )

    def test_consume_records_reason_and_notes(
        self, client, auth_headers, test_storage_location, db_session
    ):
        item_id = self._create_item(
            client, auth_headers, test_storage_location, 'Consumed with a reason'
        )

        response = client.patch(
            f'/api/v1/items/{item_id}/consume',
            headers=auth_headers,
            json={'quantity': 1, 'reason': 'OTHER', 'notes': 'spilled on the floor'},
        )
        assert response.status_code == status.HTTP_200_OK

        entries = [e for e in self._history(db_session, item_id) if e.action == 'USED']
        assert len(entries) == 1
        assert entries[0].changes['reason'] == 'OTHER'
        assert entries[0].changes['notes'] == 'spilled on the floor'

    def test_discard_records_reason_and_notes(
        self, client, auth_headers, test_storage_location, db_session
    ):
        item_id = self._create_item(
            client, auth_headers, test_storage_location, 'Disposed with a reason'
        )

        response = client.patch(
            f'/api/v1/items/{item_id}/discard',
            headers=auth_headers,
            json={'quantity': 1, 'reason': 'DAMAGED', 'notes': 'crushed in transit'},
        )
        assert response.status_code == status.HTTP_200_OK

        entries = [
            e for e in self._history(db_session, item_id) if e.action == 'DISPOSED'
        ]
        assert len(entries) == 1
        assert entries[0].changes['reason'] == 'DAMAGED'
        assert entries[0].changes['notes'] == 'crushed in transit'

    def test_history_stays_quiet_when_no_reason_is_given(
        self, client, auth_headers, test_storage_location, db_session
    ):
        item_id = self._create_item(
            client, auth_headers, test_storage_location, 'Consumed silently'
        )

        response = client.patch(
            f'/api/v1/items/{item_id}/consume',
            headers=auth_headers,
            json={'quantity': 1, 'reason': None},
        )
        assert response.status_code == status.HTTP_200_OK

        entries = [e for e in self._history(db_session, item_id) if e.action == 'USED']
        assert 'reason' not in entries[0].changes
        assert 'notes' not in entries[0].changes


class TestQuantityColumnCeiling:
    """The quantity column is numeric(12, 3): a value past its largest
    storable one is refused with the bound named, on every door that
    writes it — not with the driver's overflow."""

    def test_create_refuses_a_quantity_past_the_ceiling(
        self, client, auth_headers, test_storage_location
    ):
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Past the ceiling',
                'location_id': str(test_storage_location.id),
                'quantity': 1000000000,
            },
        )

        assert response.status_code == 422
        assert response.json()['detail'][0]['type'] == 'less_than_equal'

    def test_update_refuses_a_quantity_past_the_ceiling(
        self, client, auth_headers, test_storage_location
    ):
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'At the ceiling edge',
                'location_id': str(test_storage_location.id),
                'quantity': 2,
            },
        )
        assert created.status_code == 201, created.text

        response = client.put(
            f'/api/v1/items/{created.json()["id"]}',
            headers=auth_headers,
            json={'quantity': 1000000000},
        )

        assert response.status_code == 422
        assert response.json()['detail'][0]['type'] == 'less_than_equal'

    def test_the_largest_storable_value_is_accepted(
        self, client, auth_headers, test_storage_location, db_session
    ):
        # A decimal-capable unit: the whole-number gate on pcs. would
        # refuse the fraction before the ceiling had a say.
        from sqlalchemy import text

        kg = db_session.execute(
            text('SELECT id FROM uoms WHERE symbol = :s'), {'s': 'kg'}
        ).scalar()
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Exactly the ceiling',
                'location_id': str(test_storage_location.id),
                'uom_id': str(kg),
                'quantity': '999999999.999',
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()['quantity'] == '999999999.999'

    def test_the_quantity_patch_refuses_a_value_past_the_ceiling(
        self, client, auth_headers, test_storage_location
    ):
        # PATCH /{id}/quantity is a door of its own: the product page's
        # "+1 unit" sends the stored value plus one through it, so a
        # record at the edge overflows the column here first.
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Patched past the ceiling',
                'location_id': str(test_storage_location.id),
                'quantity': 2,
            },
        )
        assert created.status_code == 201, created.text

        response = client.patch(
            f'/api/v1/items/{created.json()["id"]}/quantity',
            headers=auth_headers,
            json={'quantity': 1000000000},
        )

        assert response.status_code == 400, response.text
        assert '999999999.999' in response.text

    def test_the_quantity_patch_accepts_the_largest_storable_value(
        self, client, auth_headers, test_storage_location, db_session
    ):
        from sqlalchemy import text

        kg = db_session.execute(
            text('SELECT id FROM uoms WHERE symbol = :s'), {'s': 'kg'}
        ).scalar()
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Patched at the ceiling',
                'location_id': str(test_storage_location.id),
                'uom_id': str(kg),
                'quantity': 2,
            },
        )
        assert created.status_code == 201, created.text

        response = client.patch(
            f'/api/v1/items/{created.json()["id"]}/quantity',
            headers=auth_headers,
            json={'quantity': '999999999.999'},
        )

        assert response.status_code == 200, response.text
        assert response.json()['quantity'] == '999999999.999'

    @pytest.mark.asyncio
    async def test_the_count_bridge_refuses_a_count_past_the_ceiling(
        self, real_async_db_session, async_test_storage_location, async_test_user
    ):
        # The bridge a stock take's counted quantity travels builds the
        # same ItemQuantityUpdate the PATCH door parses — the guard stands
        # where the column is written, so the count answers with the
        # sentence too, not the driver's overflow.
        from decimal import Decimal

        from app.core.exceptions import ServiceRejectionError
        from app.core.public_api import core_api
        from app.schemas.item import ItemCreate
        from app.services.items import create_item

        item = await create_item(
            real_async_db_session,
            ItemCreate(
                name='Counted past the ceiling',
                location_id=async_test_storage_location.id,
                quantity=Decimal('2'),
            ),
            async_test_user,
        )

        with pytest.raises(ServiceRejectionError) as refused:
            await core_api.items.update_quantity_async(
                real_async_db_session,
                async_test_user.organization_id,
                item.id,
                Decimal('1000000000'),
                user_id=async_test_user.id,
            )

        assert refused.value.key == 'item_quantity_above_ceiling'
