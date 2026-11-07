"""
Business scenario integration tests for Recipes module.

Each test represents a realistic end-to-end business workflow executed through
the API. Tests cover recipe CRUD, availability checking, picking workflow with
FEFO, nutrition estimation, tag management, and import/export round-trip.
"""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import put_on_shelf, run_in_async_session


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
def rec_org(db_session: Session) -> Organization:
    org = Organization(
        name='Recipes Scenario Org',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'recipes',
            # WMS module — needed for the conditional stock bridge (Option D)
            # to activate, so picking writes its movements.
            'warehouse',
        ],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def rec_user(db_session: Session, rec_org: Organization) -> User:
    user = User(
        email='recipes-scenario@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Recipes Scenario User',
        organization_id=rec_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def rec_headers(rec_user: User) -> dict[str, str]:
    return _auth(rec_user)


@pytest.fixture
def wh_type(db_session: Session) -> StorageType:
    st = StorageType(name='Warehouse', type_code='WAREHOUSE', behavior_mode='NONE')
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)
    return st


@pytest.fixture
def rec_location(
    db_session: Session, rec_org: Organization, wh_type: StorageType, rec_user: User
) -> StorageLocation:
    loc = StorageLocation(
        name='Kitchen Storage',
        organization_id=rec_org.id,
        storage_type_id=wh_type.id,
        created_by=rec_user.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


def _grams(db_session: Session) -> UUID:
    grams = db_session.scalar(select(Uom.id).where(Uom.symbol == 'g'))
    assert grams is not None, "'g' is not seeded"
    return grams


def _create_template(
    db_session: Session,
    org: Organization,
    name: str,
    barcode: str | None = None,
    nutrition_info: dict[str, Any] | None = None,
    uom_id: UUID | None = None,
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        barcode=barcode,
        meta_data={'nutrition': nutrition_info} if nutrition_info else None,
        uom_id=uom_id,
    )
    db_session.add(template)
    db_session.flush()
    return template


@pytest.fixture
def create_item_with_stock(
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    rec_user: User,
    rec_location: StorageLocation,
) -> Callable[..., Item]:
    """Put a record of a product on the kitchen shelf through the items service."""

    def _create(
        template: ProductTemplate,
        quantity: Decimal,
        expiry_date: date | None = None,
        purchase_price: Decimal | None = None,
    ) -> Item:
        db_session.commit()

        async def _put(session: AsyncSession) -> UUID:
            record = await put_on_shelf(
                session,
                rec_user,
                template,
                rec_location.id,
                quantity,
                expiry_date=expiry_date,
                purchase_price=purchase_price,
            )
            return record.id

        item_id = run_in_async_session(async_engine_fixture, _put)
        db_session.expire_all()
        item = db_session.get(Item, item_id)
        assert item is not None
        return item

    return _create


def _recipe_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        'name': 'Test Recipe',
        'description': 'Test description',
        'servings': 2,
        'prep_time_minutes': 30,
        'tags': ['test'],
        'is_favorite': False,
        'ingredients': [],
    }
    base.update(overrides)
    return base


@pytest.mark.integration
class TestR1RecipeCRUDAvailability:
    """
    R1 — Recipe CRUD + Availability Check

    Tests creating recipes with ingredients, checking availability,
    and verifying that the /available endpoint returns correct match percentages.
    """

    def test_recipe_availability_check(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        db_session: Session,
        rec_org: Any,
        rec_location: StorageLocation,
        create_item_with_stock: Callable[..., Item],
    ) -> None:
        grams = _grams(db_session)
        # Create 3 templates: Mąka (1000g stock), Cukier (500g stock), Masło (no stock)
        maka_tpl = _create_template(db_session, rec_org, 'Mąka', uom_id=grams)
        create_item_with_stock(maka_tpl, Decimal('1000'))

        cukier_tpl = _create_template(db_session, rec_org, 'Cukier', uom_id=grams)
        create_item_with_stock(cukier_tpl, Decimal('500'))

        maslo_tpl = _create_template(db_session, rec_org, 'Masło')

        # Create recipe with 3 ingredients
        payload = _recipe_payload(
            name='Ciasto',
            servings=1,
            ingredients=[
                {
                    'name': 'Mąka',
                    'template_id': str(maka_tpl.id),
                    'uom_id': str(grams),
                    'quantity': '300',
                    'is_optional': False,
                },
                {
                    'name': 'Cukier',
                    'template_id': str(cukier_tpl.id),
                    'uom_id': str(grams),
                    'quantity': '200',
                    'is_optional': False,
                },
                {
                    'name': 'Masło',
                    'template_id': str(maslo_tpl.id),
                    'quantity': '100',
                    'is_optional': False,
                },
            ],
        )
        resp = client.post('/api/v1/recipes', json=payload, headers=rec_headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_id = resp.json()['id']

        # Check availability — 2/3 available → match_percentage ≈ 0.67
        resp = client.get(
            f'/api/v1/recipes/{recipe_id}/availability', headers=rec_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        data = resp.json()
        assert data['match_percentage'] == pytest.approx(0.67, abs=0.01), (
            f'Expected ~67% match, got {data["match_percentage"]}'
        )

        ingredient_statuses = {i['name']: i['status'] for i in data['ingredients']}
        assert ingredient_statuses['Mąka'] == 'available'
        assert ingredient_statuses['Cukier'] == 'available'
        assert ingredient_statuses['Masło'] == 'missing'

        # Check /available endpoint with min_match=50 — recipe should appear
        resp = client.get(
            '/api/v1/recipes/available?min_match=0.5', headers=rec_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        available_ids = [r['id'] for r in resp.json()['items']]
        assert recipe_id in available_ids

        # Check servings=2 — Mąka needs 600g (still available from 1000g)
        resp = client.get(
            f'/api/v1/recipes/{recipe_id}/availability?servings=2',
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        data_servings2 = resp.json()
        maka_ing = next(i for i in data_servings2['ingredients'] if i['name'] == 'Mąka')
        assert maka_ing['status'] == 'available'


@pytest.mark.integration
class TestR2FullPickingWorkflow:
    """
    R2 — Full Picking Workflow with Stock Deduction

    Tests the complete picking workflow: start session, scan item,
    complete session, and verify Item.quantity and the shelf's group agree.
    """

    def test_picking_workflow_stock_deduction(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        db_session: Session,
        rec_org: Any,
        rec_location: StorageLocation,
        create_item_with_stock: Callable[..., Item],
    ) -> None:
        grams = _grams(db_session)
        # Create template and item with 1000g
        maka_tpl = _create_template(db_session, rec_org, 'Mąka', uom_id=grams)
        maka_item = create_item_with_stock(maka_tpl, Decimal('1000'))

        # Create recipe: 250g per serving
        payload = _recipe_payload(
            name='Naleśniki',
            servings=1,
            ingredients=[
                {
                    'name': 'Mąka',
                    'template_id': str(maka_tpl.id),
                    'uom_id': str(grams),
                    'quantity': '250',
                    'is_optional': False,
                }
            ],
        )
        resp = client.post('/api/v1/recipes', json=payload, headers=rec_headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_id = resp.json()['id']

        # Start picking session - 1 serving
        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        data = resp.json()
        session_id = data['picking_session_id']
        assert len(data['items_to_pick']) == 1
        checklist_item = data['items_to_pick'][0]
        assert checklist_item['recommended_item_id'] == str(maka_item.id)
        assert checklist_item['status'] == 'pending'

        # Scan the item
        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(maka_item.id)},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        scan_data = resp.json()
        assert scan_data['status'] == 'picked'

        db_session.flush()
        db_session.expire_all()

        # Complete the session
        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/{session_id}/complete',
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Verify Item.quantity == 750
        db_session.refresh(maka_item)
        assert maka_item.quantity == Decimal('750'), (
            f'Expected Item.quantity=750, got {maka_item.quantity}'
        )

        # Verify the shelf holds 750
        sq = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == rec_org.id,
                ShelfRow.product_template_id == maka_tpl.id,
                ShelfRow.storage_location_id == rec_location.id,
            )
        ).first()
        assert sq is not None, 'the shelf holds nothing of the product'
        assert sq.quantity == Decimal('750'), (
            f'Expected the shelf to hold 750, got {sq.quantity}'
        )


@pytest.mark.integration
class TestR3UndoPickRestoresStock:
    """
    R3 — Undo Pick Restores Stock

    Tests that undoing a pick restores both Item.quantity and the shelf
    to their pre-pick values, and resets the session item to pending.
    """

    def test_undo_pick_restores_stock(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        db_session: Session,
        rec_org: Any,
        rec_location: StorageLocation,
        create_item_with_stock: Callable[..., Item],
    ) -> None:
        grams = _grams(db_session)
        # Setup: item qty=1000, recipe needs 250g
        maka_tpl = _create_template(db_session, rec_org, 'Mąka', uom_id=grams)
        maka_item = create_item_with_stock(maka_tpl, Decimal('1000'))

        # Create recipe
        payload = _recipe_payload(
            name='Chleb',
            servings=1,
            ingredients=[
                {
                    'name': 'Mąka',
                    'template_id': str(maka_tpl.id),
                    'uom_id': str(grams),
                    'quantity': '250',
                    'is_optional': False,
                }
            ],
        )
        resp = client.post('/api/v1/recipes', json=payload, headers=rec_headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_id = resp.json()['id']

        # Start and scan
        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=rec_headers,
        )
        session_id = resp.json()['picking_session_id']

        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(maka_item.id)},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Verify qty reduced to 750
        db_session.refresh(maka_item)
        assert maka_item.quantity == Decimal('750')

        # Get ingredient_id directly from the session item in the database
        from app.modules.recipes.models import PickingSessionItem

        session_item = db_session.scalars(
            select(PickingSessionItem).where(
                PickingSessionItem.session_id == session_id,
                PickingSessionItem.status == 'picked',
            )
        ).first()
        assert session_item is not None, 'Session item should be marked as picked'
        ingredient_id = session_item.ingredient_id

        # Undo the pick
        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': str(ingredient_id)},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Verify Item.quantity == 1000
        db_session.refresh(maka_item)
        assert maka_item.quantity == Decimal('1000'), (
            f'Expected Item.quantity=1000 after undo, got {maka_item.quantity}'
        )

        # Verify the shelf holds 1000
        sq = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == rec_org.id,
                ShelfRow.product_template_id == maka_tpl.id,
                ShelfRow.storage_location_id == rec_location.id,
            )
        ).first()
        assert sq is not None
        assert sq.quantity == Decimal('1000'), (
            f'Expected the shelf to hold 1000 after undo, got {sq.quantity}'
        )

    def test_undo_pick_conserves_cost(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        db_session: Session,
        rec_org: Any,
        rec_location: StorageLocation,
        create_item_with_stock: Callable[..., Item],
    ) -> None:
        grams = _grams(db_session)
        # Regression: pick consumes FIFO valuation layers at the template's
        # AVCO rate; undo must restore AT that rate, not as a zero-cost layer
        # (which would permanently destroy the cost of returned stock).

        maka_tpl = _create_template(db_session, rec_org, 'Mąka kosztowa', uom_id=grams)
        # Receive 1000 units @ $10 -> AVCO rate = $10.00
        maka_item = create_item_with_stock(
            maka_tpl, Decimal('1000'), purchase_price=Decimal('10')
        )
        # Recompute AVCO
        from sqlalchemy import select as sa_select

        layers = db_session.scalars(
            sa_select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == maka_tpl.id,
                StockValuationLayer.remaining_qty > 0,
                StockValuationLayer.direction == 'IN',
            )
        ).all()
        total_value = sum(
            (layer.remaining_qty * layer.unit_cost for layer in layers), Decimal('0')
        )
        total_qty = sum((layer.remaining_qty for layer in layers), Decimal('0'))
        # Read straight off the layers. This used to be written to
        # `maka_tpl.current_valuation_rate` and then read back — a round trip
        # through a column that a global template shares with every
        # organization, and which is gone for that reason.
        assert total_qty > 0
        assert (total_value / total_qty).quantize(Decimal('0.01')) == Decimal('10.00')
        db_session.commit()
        db_session.expire_all()

        payload = _recipe_payload(
            name='Chleb kosztowy',
            servings=1,
            ingredients=[
                {
                    'name': 'Mąka',
                    'template_id': str(maka_tpl.id),
                    'uom_id': str(grams),
                    'quantity': '250',
                    'is_optional': False,
                }
            ],
        )
        resp = client.post('/api/v1/recipes', json=payload, headers=rec_headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_id = resp.json()['id']

        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=rec_headers,
        )
        session_id = resp.json()['picking_session_id']

        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(maka_item.id)},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        from app.modules.recipes.models import PickingSessionItem

        session_item = db_session.scalars(
            select(PickingSessionItem).where(
                PickingSessionItem.session_id == session_id,
                PickingSessionItem.status == 'picked',
            )
        ).first()
        assert session_item is not None
        ingredient_id = session_item.ingredient_id

        # Undo — must restore the 250 units AT COST, conserving AVCO.
        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': str(ingredient_id)},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.expire_all()
        layers_after = db_session.scalars(
            sa_select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == maka_tpl.id,
                StockValuationLayer.remaining_qty > 0,
                StockValuationLayer.direction == 'IN',
            )
        ).all()
        value_after = sum(
            (layer.remaining_qty * layer.unit_cost for layer in layers_after),
            Decimal('0'),
        )
        qty_after = sum((layer.remaining_qty for layer in layers_after), Decimal('0'))
        rate_after = (
            (value_after / qty_after).quantize(Decimal('0.01'))
            if qty_after > 0
            else None
        )
        # Pre-fix this dropped to $7.50: (750*10 + 250*0)/1000.
        assert rate_after == Decimal('10.00'), (
            f'AVCO corrupted by undo: expected 10.00, got {rate_after}'
        )


@pytest.mark.integration
class TestR4FEFOPickingExpiryBasedRecommendation:
    """
    R4 — FEFO Picking — Expiry-Based Recommendation

    Tests that when multiple items of the same template exist,
    the picking session recommends the one with the earliest expiry date (FEFO).
    """

    def test_fefo_picks_earliest_expiry(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        db_session: Session,
        rec_org: Any,
        rec_location: StorageLocation,
        create_item_with_stock: Callable[..., Item],
    ) -> None:
        grams = _grams(db_session)
        # Create template
        jogurt_tpl = _create_template(db_session, rec_org, 'Jogurt', uom_id=grams)

        today = date.today()
        item_a_expiry = today + timedelta(days=5)
        item_b_expiry = today + timedelta(days=30)

        # Create 2 items in same location: A (5d expiry), B (30d expiry)
        item_a = create_item_with_stock(
            jogurt_tpl,
            Decimal('500'),
            expiry_date=item_a_expiry,
        )
        create_item_with_stock(
            jogurt_tpl,
            Decimal('500'),
            expiry_date=item_b_expiry,
        )

        # Create recipe with 200g jogurt
        payload = _recipe_payload(
            name='Jogurtowiec',
            servings=1,
            ingredients=[
                {
                    'name': 'Jogurt',
                    'template_id': str(jogurt_tpl.id),
                    'uom_id': str(grams),
                    'quantity': '200',
                    'is_optional': False,
                }
            ],
        )
        resp = client.post('/api/v1/recipes', json=payload, headers=rec_headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_id = resp.json()['id']

        # Start picking
        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        data = resp.json()

        checklist = data['items_to_pick'][0]
        # FEFO should recommend Item A (shorter expiry)
        assert checklist['recommended_item_id'] == str(item_a.id), (
            'FEFO should recommend item with shorter expiry'
        )
        assert checklist['fefo_days_left'] is not None
        assert checklist['fefo_days_left'] <= 30


@pytest.mark.integration
class TestR5NutritionEstimationThreeTierFallback:
    """
    R5 — Nutrition Estimation — 3-Tier Fallback

    Tests the 3-tier nutrition fallback:
    1. Template nutrition_info (tier 1)
    2. IngredientNutritionDefault (tier 2)
    3. calories_kcal_per_100g override (tier 3)
    """

    def test_nutrition_three_tier_fallback(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        db_session: Session,
        rec_org: Any,
    ) -> None:
        from sqlalchemy import text

        uom_row = db_session.execute(
            text('SELECT id FROM uoms WHERE symbol = :s'), {'s': 'g'}
        ).fetchone()
        uom_id = str(uom_row[0]) if uom_row else None

        # Tier 1: Template with full nutrition_info
        platki_tpl = _create_template(
            db_session,
            rec_org,
            'Płatki',
            nutrition_info={
                'calories_kcal': 350.0,
                'protein_g': 12.0,
                'fat_g': 5.0,
                'carbs_g': 65.0,
                'fiber_g': 2.5,
                'sugar_g': 1.0,
                'salt_g': 0.5,
            },
        )

        # Tier 2: Template without nutrition_info, but IngredientNutritionDefault exists
        from app.modules.recipes.models import IngredientNutritionDefault

        mleko_tpl = _create_template(db_session, rec_org, 'Mleko')
        mleko_default = IngredientNutritionDefault(
            organization_id=rec_org.id,
            lang='en',
            name='Mleko',
            name_normalized='mleko',
            calories_kcal=42.0,
            protein_g=3.4,
            fat_g=1.0,
            carbs_g=5.0,
            source='manual',
        )
        db_session.add(mleko_default)
        db_session.flush()

        # Tier 3: No template nutrition, no default — only kcal override on ingredient
        miod_tpl = _create_template(db_session, rec_org, 'Miód')

        # Create recipe with 3 ingredients
        payload = _recipe_payload(
            name='Owsianka',
            servings=1,
            ingredients=[
                {
                    'name': 'Płatki',
                    'template_id': str(platki_tpl.id),
                    'quantity': '100',
                    'uom_id': uom_id,
                    'is_optional': False,
                },
                {
                    'name': 'Mleko',
                    'template_id': str(mleko_tpl.id),
                    'quantity': '200',
                    'uom_id': uom_id,
                    'is_optional': False,
                },
                {
                    'name': 'Miód',
                    'template_id': str(miod_tpl.id),
                    'quantity': '15',
                    'uom_id': uom_id,
                    'calories_kcal_per_100g': '304',
                    'is_optional': False,
                },
            ],
        )
        resp = client.post('/api/v1/recipes', json=payload, headers=rec_headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_id = resp.json()['id']

        # Get nutrition
        resp = client.get(
            f'/api/v1/recipes/{recipe_id}/nutrition?servings=1',
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        data = resp.json()

        ings_by_name = {i['ingredient_name']: i for i in data['ingredients']}

        # Tier 1: Płatki — full nutrition from template
        platki = ings_by_name.get('Płatki')
        assert platki is not None
        assert platki['has_data'] is True
        assert platki['nutrition'] is not None
        assert platki['nutrition']['calories_kcal'] == pytest.approx(350.0, abs=10.0)
        assert platki['nutrition']['protein_g'] is not None

        # Tier 2: Mleko — nutrition from IngredientNutritionDefault
        mleko = ings_by_name.get('Mleko')
        assert mleko is not None
        assert mleko['has_data'] is True
        assert mleko['nutrition'] is not None
        assert mleko['nutrition']['calories_kcal'] == pytest.approx(84.0, abs=10.0)

        # Tier 3: Miód — only calories from kcal override
        miod = ings_by_name.get('Miód')
        assert miod is not None
        assert miod['has_data'] is True
        assert miod['nutrition'] is not None
        assert miod['nutrition']['calories_kcal'] == pytest.approx(45.6, abs=15.0)


@pytest.mark.integration
class TestR6MultiRecipeStockConsistency:
    """
    R6 — Multi-Recipe Stock Consistency

    Tests that after picking for Recipe A, Recipe B correctly fails to pick
    due to insufficient stock, and that no partial deduction occurs on failure.
    """

    def test_multi_recipe_stock_consistency(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        db_session: Session,
        rec_org: Any,
        rec_location: StorageLocation,
        create_item_with_stock: Callable[..., Item],
    ) -> None:
        grams = _grams(db_session)
        # Template "Mąka" with 1000g
        maka_tpl = _create_template(db_session, rec_org, 'Mąka', uom_id=grams)
        maka_item = create_item_with_stock(maka_tpl, Decimal('1000'))

        # Recipe A "Naleśniki": Mąka 300g
        payload_a = _recipe_payload(
            name='Naleśniki',
            servings=1,
            ingredients=[
                {
                    'name': 'Mąka',
                    'template_id': str(maka_tpl.id),
                    'uom_id': str(grams),
                    'quantity': '300',
                    'is_optional': False,
                }
            ],
        )
        resp = client.post('/api/v1/recipes', json=payload_a, headers=rec_headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_a_id = resp.json()['id']

        # Recipe B "Chleb": Mąka 800g
        payload_b = _recipe_payload(
            name='Chleb',
            servings=1,
            ingredients=[
                {
                    'name': 'Mąka',
                    'template_id': str(maka_tpl.id),
                    'uom_id': str(grams),
                    'quantity': '800',
                    'is_optional': False,
                }
            ],
        )
        resp = client.post('/api/v1/recipes', json=payload_b, headers=rec_headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_b_id = resp.json()['id']

        # Start and complete Recipe A
        resp = client.post(
            f'/api/v1/recipes/{recipe_a_id}/picking/start',
            json={'servings': 1},
            headers=rec_headers,
        )
        session_a_id = resp.json()['picking_session_id']

        resp = client.post(
            f'/api/v1/recipes/{recipe_a_id}/picking/{session_a_id}/scan',
            json={'item_id': str(maka_item.id)},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        resp = client.post(
            f'/api/v1/recipes/{recipe_a_id}/picking/{session_a_id}/complete',
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Verify qty=700 after Recipe A
        db_session.refresh(maka_item)
        assert maka_item.quantity == Decimal('700'), (
            f'Expected 700 after Recipe A, got {maka_item.quantity}'
        )

        # Start Recipe B picking
        resp = client.post(
            f'/api/v1/recipes/{recipe_b_id}/picking/start',
            json={'servings': 1},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        session_b_id = resp.json()['picking_session_id']

        # Recipe B needs 800g but only 700g available
        # Picking service CAPS at available stock — does NOT error
        resp = client.post(
            f'/api/v1/recipes/{recipe_b_id}/picking/{session_b_id}/scan',
            json={'item_id': str(maka_item.id)},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        scan_data = resp.json()
        # quantity_consumed should be capped at available (700), not the full 800
        assert Decimal(str(scan_data['quantity_consumed'])) == Decimal('700'), (
            f'Expected capping at 700, got {scan_data["quantity_consumed"]}'
        )

        db_session.flush()
        db_session.expire_all()

        # Verify item stock fully depleted (700 - 700 = 0, not negative)
        db_session.refresh(maka_item)
        assert maka_item.quantity == Decimal('0'), (
            f'Expected 0 after capped pick, got {maka_item.quantity}'
        )

        # The shelf must be consistent — also 0, or the group is gone
        sq = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == rec_org.id,
                ShelfRow.product_template_id == maka_tpl.id,
                ShelfRow.storage_location_id == rec_location.id,
            )
        ).first()
        on_shelf = sq.quantity if sq else Decimal('0')
        assert on_shelf == Decimal('0'), (
            f'the shelf should be empty (its group gone), got {on_shelf}'
        )


@pytest.mark.integration
class TestR7TagLifecycle:
    """
    R7 — Tag Lifecycle: Create → Color → Merge → Verify

    Tests creating recipes with tags, updating tag colors,
    merging tags, and verifying the merged state.
    """

    def test_tag_lifecycle(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        db_session: Session,
        rec_org: Any,
    ) -> None:
        # Create Recipe A with tags=["obiad", "szybkie"]
        payload_a = _recipe_payload(
            name='Risotto',
            tags=['obiad', 'szybkie'],
        )
        resp = client.post('/api/v1/recipes', json=payload_a, headers=rec_headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_a_id = resp.json()['id']

        # Create Recipe B with tags=["obiad", "zdrowe"]
        payload_b = _recipe_payload(
            name='Sałatka',
            tags=['obiad', 'zdrowe'],
        )
        resp = client.post('/api/v1/recipes', json=payload_b, headers=rec_headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

        # Get initial tags
        resp = client.get('/api/v1/recipes/tags', headers=rec_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        tags_before = {t['name']: t['count'] for t in resp.json()['items']}
        assert tags_before.get('obiad', 0) == 2
        assert tags_before.get('szybkie', 0) == 1
        assert tags_before.get('zdrowe', 0) == 1

        # Update color for "szybkie" tag
        resp = client.patch(
            '/api/v1/recipes/tags/szybkie/color',
            json={'color': '#FF0000'},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['color'] == '#FF0000'

        # Merge "szybkie" into "obiad"
        resp = client.post(
            '/api/v1/recipes/tags/merge',
            json={'old_tag': 'szybkie', 'new_tag': 'obiad'},
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['old_tag'] == 'szybkie'
        assert resp.json()['new_tag'] == 'obiad'
        assert resp.json()['updated_recipes'] == 1

        # Get tags after merge
        resp = client.get('/api/v1/recipes/tags', headers=rec_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        tags_after = {t['name']: t['count'] for t in resp.json()['items']}

        # "szybkie" should not exist
        assert 'szybkie' not in tags_after
        # "obiad" count should be 2 (Recipe A and Recipe B both have "obiad")
        assert tags_after.get('obiad', 0) == 2
        # "zdrowe" should still be 1
        assert tags_after.get('zdrowe', 0) == 1

        # Verify Recipe A now only has "obiad" tag
        resp = client.get(f'/api/v1/recipes/{recipe_a_id}', headers=rec_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert 'obiad' in resp.json()['tags']
        assert 'szybkie' not in resp.json()['tags']


@pytest.mark.integration
class TestR8ImportExportRoundTrip:
    """
    R8 — Import + Export Round-Trip

    Tests importing a recipe via JSON, verifying it was created correctly,
    and then exporting it back in both JSON and schema_org formats.
    """

    def test_import_export_roundtrip(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        db_session: Session,
        rec_org: Any,
    ) -> None:
        # Import recipe via JSON
        import_payload = {
            'format': 'json',
            'data': {
                'name': 'Testowe Muffinki',
                'description': 'Prosty przepis',
                'instructions': 'Wymieszaj i piecz',
                'servings': 12,
                'prep_time_minutes': 30,
                'ingredients': [
                    {'name': 'Mąka', 'quantity': 300, 'unit': 'g'},
                    {'name': 'Cukier', 'quantity': 100, 'unit': 'g'},
                    {'name': 'Jajka', 'quantity': 2, 'unit': 'pcs'},
                ],
                'tags': ['wypieki', 'deser'],
            },
        }
        resp = client.post(
            '/api/v1/recipes/import',
            json=import_payload,
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_data = resp.json()
        assert recipe_data['name'] == 'Testowe Muffinki'
        assert recipe_data['servings'] == 12
        assert len(recipe_data['ingredients']) == 3
        recipe_id = recipe_data['id']

        # Export as JSON
        resp = client.get(
            f'/api/v1/recipes/{recipe_id}/export?format=json',
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        export_data = resp.json()

        # Verify round-trip data
        assert export_data['name'] == 'Testowe Muffinki'
        assert export_data['servings'] == 12
        assert export_data['description'] == 'Prosty przepis'
        assert export_data['instructions'] == 'Wymieszaj i piecz'
        assert len(export_data['ingredients']) == 3
        assert export_data['tags'] == ['wypieki', 'deser']

        # Units must survive the round-trip (no silent unit loss).
        exported_units = {ing['uom'] for ing in export_data['ingredients']}
        assert exported_units == {'g', 'pcs'}

        # Export as schema_org
        resp = client.get(
            f'/api/v1/recipes/{recipe_id}/export?format=schema_org',
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        schema_org_data = resp.json()

        # Verify Schema.org format
        assert schema_org_data['@context'] == 'https://schema.org'
        assert schema_org_data['@type'] == 'Recipe'
        assert schema_org_data['name'] == 'Testowe Muffinki'
        assert 'recipeIngredient' in schema_org_data
        assert 'recipeYield' in schema_org_data

    def test_import_preview_json_carries_original_unit_text(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        rec_org: Any,
    ) -> None:
        # The JSON preview path must expose the raw unit string so the
        # UI can warn when it does not resolve to a known UoM.
        payload = {
            'format': 'json',
            'data': {
                'name': 'Preview Units',
                'ingredients': [
                    {'name': 'Mąka', 'quantity': 300, 'unit': 'g'},
                    {'name': 'Tajemniczy składnik', 'quantity': 1, 'unit': 'handful'},
                    {'name': 'Bez jednostki', 'quantity': 2},
                ],
            },
        }
        resp = client.post(
            '/api/v1/recipes/import/preview',
            json=payload,
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        ingredients = resp.json()['ingredients']
        assert len(ingredients) == 3

        resolved = ingredients[0]
        assert resolved['uom_id'] is not None
        assert resolved['original_unit_text'] == 'g'

        unrecognized = ingredients[1]
        assert unrecognized['uom_id'] is None
        assert unrecognized['original_unit_text'] == 'handful'

        no_unit = ingredients[2]
        assert no_unit['uom_id'] is None
        assert no_unit['original_unit_text'] is None

    def test_export_schema_org_includes_allergens(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        rec_org: Any,
    ) -> None:
        # Allergens must survive into the Schema.org export via the
        # documented 'inventari:allergens' extension (recipe-level union).
        import_payload = {
            'format': 'json',
            'data': {
                'name': 'Alergenowe Ciasto',
                'servings': 4,
                'ingredients': [
                    {
                        'name': 'Mąka',
                        'quantity': 300,
                        'unit': 'g',
                        'allergens': ['gluten'],
                    },
                    {
                        'name': 'Jajka',
                        'quantity': 2,
                        'unit': 'pcs',
                        'allergens': ['eggs'],
                    },
                    {
                        'name': 'Mleko',
                        'quantity': 200,
                        'unit': 'ml',
                        'allergens': ['milk'],
                    },
                    {'name': 'Sól', 'quantity': 1, 'unit': 'g'},
                ],
            },
        }
        resp = client.post(
            '/api/v1/recipes/import',
            json=import_payload,
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        recipe_id = resp.json()['id']

        resp = client.get(
            f'/api/v1/recipes/{recipe_id}/export?format=schema_org',
            headers=rec_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        schema_org_data = resp.json()
        assert schema_org_data['inventari:allergens'] == ['eggs', 'gluten', 'milk']


@pytest.mark.integration
class TestImportRefusesALineWithNoUnit:
    """An imported amount names a unit the instance knows, or the import stops.

    "2 tbsp" arriving as "2" reached the shopping list as "Soy sauce 2 —":
    the unit it could not read was dropped without a word. The recipe form
    already refuses an amount with no unit; the import is the other door.
    """

    @pytest.mark.parametrize('unit', ['tbsp', 'handful', 'kg-ish'])
    def test_a_unit_the_instance_does_not_know_is_refused_and_nothing_is_saved(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
        unit: str,
    ) -> None:
        resp = client.post(
            '/api/v1/recipes/import',
            json={
                'format': 'json',
                'data': {
                    'name': 'Chicken fried rice',
                    'ingredients': [
                        {'name': 'Rice', 'quantity': 300, 'uom': 'g'},
                        {'name': 'Soy sauce', 'quantity': 2, 'uom': unit},
                    ],
                },
            },
            headers=rec_headers,
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        detail = resp.json()['detail']
        assert detail['code'] == 'RECIPE_IMPORT_UNIT_UNKNOWN', detail
        assert 'Soy sauce' in detail['message']
        assert unit in detail['message']
        listed = client.get('/api/v1/recipes', headers=rec_headers)
        assert listed.status_code == status.HTTP_200_OK, listed.text
        assert 'Chicken fried rice' not in listed.text

    def test_an_amount_with_no_unit_at_all_is_refused(
        self,
        client: TestClient,
        rec_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            '/api/v1/recipes/import',
            json={
                'format': 'json',
                'data': {
                    'name': 'Unitless',
                    'ingredients': [{'name': 'Salt', 'quantity': 2}],
                },
            },
            headers=rec_headers,
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        detail = resp.json()['detail']
        assert detail['code'] == 'RECIPE_INGREDIENT_UNIT_MISSING', detail
        assert 'Salt' in detail['message']


@pytest.mark.integration
def test_list_recipes_reports_ingredients_linked(
    db_session: Session,
    client: TestClient,
    rec_org: Organization,
    rec_headers: dict[str, str],
) -> None:
    """the list endpoint must distinguish "ingredients linked to
    stock" from the plain ingredient count — the empty-state discriminator
    in the UI depends on it."""
    maka_tpl = _create_template(db_session, rec_org, 'Maka')
    payload = _recipe_payload(
        name='List Linked Count',
        ingredients=[
            {
                'name': 'Maka',
                'template_id': str(maka_tpl.id),
                'quantity': '300',
                'is_optional': False,
            },
            {
                'name': 'Sos',
                'template_id': None,
                'quantity': '100',
                'is_optional': False,
            },
            {
                'name': 'Bazylia',
                'template_id': None,
                'quantity': '5',
                'is_optional': True,
            },
        ],
    )
    resp = client.post('/api/v1/recipes', json=payload, headers=rec_headers)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    recipe_id = resp.json()['id']

    resp = client.get('/api/v1/recipes', headers=rec_headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    item = next(r for r in resp.json()['items'] if r['id'] == recipe_id)
    assert item['ingredients_linked'] == 1
    assert item['ingredients_total'] == 2  # non-optional only
