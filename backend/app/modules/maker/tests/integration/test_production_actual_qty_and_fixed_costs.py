"""Integration tests for actual_qty / scrap / overproduction / fixed costs.

Test contract:
  - actual < planned → scrap, unit_cost rises, consumption = full planned
  - actual > planned + allow_overproduction=true → overproduced=True, unit_cost drops
  - actual > planned + allow_overproduction=false → 400
  - actual = 0 → 400 (requires cancel + write-off)
  - actual omitted → defaults to planned_qty (backward compatible)
  - fixed cost lines included in total_cost
  - settings: allow_overproduction GET/PATCH round-trip
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import (
    BoMLine,
    MakerModuleSettings,
    MakerRecipe,
    MakerRecipeCostLine,
)
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers (same patterns as test_production_consume_create.py)
# ---------------------------------------------------------------------------


def _template(db: Session, org: Organization, *, name: str = 'T') -> ProductTemplate:
    t = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _ensure_recipe(
    db: Session,
    org: Organization,
    template_id: UUID,
    *,
    batch_yield_qty: str = '1',
) -> MakerRecipe:
    existing = (
        db.query(MakerRecipe)
        .filter(
            MakerRecipe.organization_id == org.id,
            MakerRecipe.output_template_id == template_id,
            MakerRecipe.is_default.is_(True),
        )
        .first()
    )
    if existing:
        return existing
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=template_id,
        name='Test',
        batch_yield_qty=Decimal(batch_yield_qty),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


def _bom_line(
    db: Session,
    org: Organization,
    *,
    parent_id: UUID,
    child_id: UUID,
    qty: str = '1.0',
) -> BoMLine:
    recipe = _ensure_recipe(db, org, parent_id)
    line = BoMLine(
        organization_id=org.id,
        recipe_id=recipe.id,
        parent_template_id=parent_id,
        child_template_id=child_id,
        qty_per_batch=Decimal(qty),
        unit='kg',
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def _stock(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    location: StorageLocation,
    *,
    unit_cost: str,
    qty: str = '100.000',
) -> dict[str, Any]:
    """Put *qty* of *template* on the shelf as one record bought at *unit_cost*.

    The record's receipt writes the movement and the cost layer the run is
    priced from, the way a person's entry does.
    """
    return post_on_shelf(
        client, headers, template, location.id, qty, purchase_price=unit_cost
    )


def _shelf_on(
    db: Session, org: Organization, template: ProductTemplate, location: StorageLocation
) -> ShelfRow:
    return db.execute(
        select(ShelfRow).where(
            ShelfRow.organization_id == org.id,
            ShelfRow.product_template_id == template.id,
            ShelfRow.storage_location_id == location.id,
        )
    ).scalar_one()


def _cost_line(
    db: Session,
    org: Organization,
    *,
    recipe_id: UUID,
    kind: str = 'LABOR',
    label: str = 'Labor',
    amount: str = '5.00',
    sort_order: int = 0,
) -> MakerRecipeCostLine:
    cl = MakerRecipeCostLine(
        recipe_id=recipe_id,
        organization_id=org.id,
        kind=kind,
        label=label,
        amount=Decimal(amount),
        sort_order=sort_order,
    )
    db.add(cl)
    db.commit()
    db.refresh(cl)
    return cl


def _set_allow_overproduction(
    db: Session,
    org_id: UUID,
    *,
    value: bool,
) -> None:
    settings = (
        db.query(MakerModuleSettings)
        .filter(MakerModuleSettings.organization_id == org_id)
        .first()
    )
    if settings is None:
        settings = MakerModuleSettings(organization_id=org_id)
        db.add(settings)
    settings.allow_overproduction = value
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestActualQtyScrap:
    """actual < planned → scrap, unit_cost rises, full planned consumed."""

    def test_actual_less_than_planned_produces_scrap(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Cocoa')
        output = _template(db_session, mk_org, name='Chocolate')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='1.0',
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, unit_cost='2.00')

        # Plan 10 units.
        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '10.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create_resp.status_code == 201
        order_id = create_resp.json()['id']

        # Complete with actual_qty = 8 (scrap 2).
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
            json={'actual_qty': '8.000'},
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()

        assert body['status'] == 'COMPLETED'
        assert Decimal(body['actual_qty']) == Decimal('8.000')
        assert body['overproduced'] is False
        # scrap = planned - actual = 10 - 8 = 2
        assert Decimal(body['scrap_qty']) == Decimal('2.000')

        # total = 10 kg × 2.00 AVCO = 20.00 (full planned consumption)
        assert Decimal(body['total_cost']) == Decimal('20.00')

        # unit_cost rises above total/planned: 20.00 / 8 = 2.50 > 2.00.
        assert Decimal(body['unit_cost']) == Decimal('2.50')
        assert Decimal(body['unit_cost']) > Decimal(body['total_cost']) / Decimal(
            '10.000'
        )

        # Ingredient consumed fully (10 planned, not 8 actual)
        refreshed = _shelf_on(db_session, mk_org, ingredient, mk_input_loc)
        assert refreshed.quantity == Decimal('100.000') - Decimal('10.000')

        # Output shelf gained actual (8), not planned (10)
        output_shelf = db_session.execute(
            select(ShelfRow).where(
                ShelfRow.organization_id == mk_org.id,
                ShelfRow.product_template_id == output.id,
                ShelfRow.storage_location_id == mk_output_loc.id,
            )
        ).scalar_one_or_none()
        assert output_shelf is not None
        assert output_shelf.quantity == Decimal('8.000')


class TestActualQtyOverproduction:
    """actual > planned → overproduced flag + allow_overproduction gate."""

    def test_actual_greater_than_planned_allowed_by_default(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Sugar')
        output = _template(db_session, mk_org, name='Syrup')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='1.0',
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, unit_cost='1.00')

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '10.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']

        # Overproduce: actual = 12, planned = 10.
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
            json={'actual_qty': '12.000'},
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()

        assert body['overproduced'] is True
        assert Decimal(body['actual_qty']) == Decimal('12.000')
        # scrap_qty is negative (overproduced)
        assert Decimal(body['scrap_qty']) == Decimal('-2.000')

        # total = 10 × 1.00 = 10.00 (full planned material consumption)
        assert Decimal(body['total_cost']) == Decimal('10.00')

        # unit_cost drops below total/planned: 10.00 / 12 ≈ 0.83 < 1.00.
        assert Decimal(body['unit_cost']) < Decimal('1.00')
        assert Decimal(body['unit_cost']) < Decimal(body['total_cost']) / Decimal(
            '10.000'
        )

        # Output shelf = actual (12)
        output_shelf = db_session.execute(
            select(ShelfRow).where(
                ShelfRow.organization_id == mk_org.id,
                ShelfRow.product_template_id == output.id,
                ShelfRow.storage_location_id == mk_output_loc.id,
            )
        ).scalar_one_or_none()
        assert output_shelf is not None
        assert output_shelf.quantity == Decimal('12.000')

    def test_actual_greater_than_planned_blocked_when_disabled(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Wax')
        output = _template(db_session, mk_org, name='Candle')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='1.0',
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, unit_cost='1.00')

        # Disable overproduction via settings.
        _set_allow_overproduction(db_session, mk_org.id, value=False)

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '10.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
            json={'actual_qty': '12.000'},
        )
        assert complete_resp.status_code == 400
        detail = complete_resp.json()['detail']
        assert 'overproduction' in detail['message'].lower()

        # Order stays DRAFT — no consumption happened.
        order_resp = client.get(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
        )
        assert order_resp.json()['status'] == 'DRAFT'


class TestActualQtyZero:
    """actual_qty = 0 → 400 (requires cancel + write-off)."""

    def test_actual_qty_zero_rejected(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Flour')
        output = _template(db_session, mk_org, name='Bread')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='1.0',
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, unit_cost='1.00')

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '10.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
            json={'actual_qty': '0.000'},
        )
        assert complete_resp.status_code == 400
        detail = complete_resp.json()['detail']
        assert 'greater than zero' in detail['message'].lower()

        # Order stays DRAFT.
        order_resp = client.get(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
        )
        assert order_resp.json()['status'] == 'DRAFT'


class TestActualQtyDefault:
    """Omitting actual_qty defaults to planned_qty (backward compatible)."""

    def test_complete_without_actual_qty_uses_planned(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Hop')
        output = _template(db_session, mk_org, name='Beer')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='1.0',
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, unit_cost='3.00')

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '5.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']

        # Complete WITHOUT body — backward compatible.
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()

        # actual_qty = planned_qty (backward compat)
        assert Decimal(body['actual_qty']) == Decimal('5.000')
        assert body['overproduced'] is False
        assert Decimal(body['scrap_qty']) == Decimal('0.000')
        # total = 5 × 3.00 = 15.00
        assert Decimal(body['total_cost']) == Decimal('15.00')


class TestFixedCostLines:
    """Fixed cost lines (LABOR/PACKAGING/etc.) included in total_cost."""

    def test_fixed_cost_lines_included_in_total(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Tomato')
        output = _template(db_session, mk_org, name='Sauce')
        recipe = _ensure_recipe(db_session, mk_org, output.id, batch_yield_qty='1')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='2.0',
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, unit_cost='1.50')
        # Fixed costs: 5.00 labor + 2.00 packaging = 7.00 per batch.
        _cost_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            kind='LABOR',
            label='Labor',
            amount='5.00',
        )
        _cost_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            kind='PACKAGING',
            label='Jars',
            amount='2.00',
        )

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '3.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()

        # Material: 3 batches × 2 kg × 1.50 = 9.00
        # Fixed: 3 batches × (5.00 + 2.00) = 21.00
        # Total: 9.00 + 21.00 = 30.00
        assert Decimal(body['total_cost']) == Decimal('30.00')


class TestSettingsAllowOverproduction:
    """allow_overproduction knob: GET/PATCH round-trip."""

    def test_settings_round_trip_allow_overproduction(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        # Default: allow_overproduction = true (server default in migration).
        get_resp = client.get(
            '/api/v1/maker/settings',
            headers=mk_auth_headers,
        )
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body['allow_overproduction'] is True

        # Patch to false.
        patch_resp = client.patch(
            '/api/v1/maker/settings',
            headers=mk_auth_headers,
            json={'allow_overproduction': False},
        )
        assert patch_resp.status_code == 200, patch_resp.text
        assert patch_resp.json()['allow_overproduction'] is False

        # Re-read.
        get_resp2 = client.get(
            '/api/v1/maker/settings',
            headers=mk_auth_headers,
        )
        assert get_resp2.json()['allow_overproduction'] is False


class TestExplicitRecipeExplosion:
    """Order with an explicit non-default recipe consumes by THAT recipe.

    Regression: completion used to explode by the DEFAULT recipe while
    fixed costs read ``order.recipe_id`` — consumption and costs could
    come from different recipes. With an explicit recipe, the top-level
    explosion must follow the order's recipe; nested sub-assemblies keep
    the default-recipe lookup (documented design).
    """

    def _variant_recipe(
        self,
        db: Session,
        org: Organization,
        output_id: UUID,
        *,
        child_id: UUID,
        qty: str,
    ) -> MakerRecipe:
        variant = MakerRecipe(
            organization_id=org.id,
            output_template_id=output_id,
            name=f'Variant-{uuid.uuid4().hex[:6]}',
            batch_yield_qty=Decimal('1'),
            is_default=False,
        )
        db.add(variant)
        db.commit()
        db.refresh(variant)
        line = BoMLine(
            organization_id=org.id,
            recipe_id=variant.id,
            parent_template_id=output_id,
            child_template_id=child_id,
            qty_per_batch=Decimal(qty),
            unit='kg',
        )
        db.add(line)
        db.commit()
        db.refresh(line)
        return variant

    def test_complete_uses_explicit_recipe_lines(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        default_ing = _template(db_session, mk_org, name='DefaultIng')
        variant_ing = _template(db_session, mk_org, name='VariantIng')
        output = _template(db_session, mk_org, name='Product')
        default_recipe = _ensure_recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=default_ing.id,
            qty='1.0',
        )
        variant = self._variant_recipe(
            db_session, mk_org, output.id, child_id=variant_ing.id, qty='2.0'
        )
        _stock(client, mk_auth_headers, default_ing, mk_input_loc, unit_cost='2.00')
        _stock(client, mk_auth_headers, variant_ing, mk_input_loc, unit_cost='3.00')

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'recipe_id': str(variant.id),
                'planned_qty': '5.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create_resp.status_code == 201
        order_id = create_resp.json()['id']
        # The order resolved to the explicit (non-default) recipe.
        assert create_resp.json()['recipe_id'] == str(variant.id)
        assert create_resp.json()['recipe_id'] != str(default_recipe.id)

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()

        # Only the variant's ingredient is consumed: 5 batches × 2 kg = 10.
        default_refreshed = _shelf_on(db_session, mk_org, default_ing, mk_input_loc)
        variant_refreshed = _shelf_on(db_session, mk_org, variant_ing, mk_input_loc)
        assert default_refreshed.quantity == Decimal('100.000')
        assert variant_refreshed.quantity == Decimal('90.000')

        # Material cost follows the same recipe: 10 kg × 3.00 = 30.00
        # (not the default recipe's 5 × 2.00 = 10.00).
        assert Decimal(body['total_cost']) == Decimal('30.00')

        # Order-line snapshot references the variant ingredient only.
        order_resp = client.get(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
        )
        lines = order_resp.json()['lines']
        assert [line['child_template_id'] for line in lines] == [str(variant_ing.id)]
        assert Decimal(lines[0]['consumed_qty']) == Decimal('10.0000')


class TestMultiLevelBoM:
    """Multi-level BOM: parent → sub-assembly (own recipe) → leaves."""

    def test_complete_explodes_nested_bom_by_planned_qty(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        leaf = _template(db_session, mk_org, name='Leaf')
        sub_assembly = _template(db_session, mk_org, name='SubAssembly')
        output = _template(db_session, mk_org, name='Final')
        # Output's recipe: 1 sub-assembly per unit.
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=sub_assembly.id,
            qty='1.0',
        )
        # Sub-assembly's OWN recipe: 1 leaf per sub-assembly unit.
        _bom_line(
            db_session,
            mk_org,
            parent_id=sub_assembly.id,
            child_id=leaf.id,
            qty='1.0',
        )
        _stock(client, mk_auth_headers, leaf, mk_input_loc, unit_cost='2.00')

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '10.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create_resp.status_code == 201
        order_id = create_resp.json()['id']

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
            json={'actual_qty': '8.000'},
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()

        # Output = actual (8); leaves consumed by PLANNED (10).
        assert Decimal(body['actual_qty']) == Decimal('8.000')
        leaf_refreshed = _shelf_on(db_session, mk_org, leaf, mk_input_loc)
        assert leaf_refreshed.quantity == Decimal('90.000')
        output_shelf = db_session.execute(
            select(ShelfRow).where(
                ShelfRow.organization_id == mk_org.id,
                ShelfRow.product_template_id == output.id,
                ShelfRow.storage_location_id == mk_output_loc.id,
            )
        ).scalar_one_or_none()
        assert output_shelf is not None
        assert output_shelf.quantity == Decimal('8.000')

        # Material cost: 10 kg leaf × 2.00 = 20.00 (full planned).
        assert Decimal(body['total_cost']) == Decimal('20.00')

        # Order lines: only the leaf (the sub-assembly is exploded through),
        # consumed by planned qty.
        order_resp = client.get(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
        )
        lines = order_resp.json()['lines']
        assert [line['child_template_id'] for line in lines] == [str(leaf.id)]
        assert Decimal(lines[0]['consumed_qty']) == Decimal('10.0000')


class TestReconciliationAfterProduction:
    """The shelf must stay in step with the movement ledger after production."""

    def test_zero_drift_after_complete(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Cocoa2')
        output = _template(db_session, mk_org, name='Chocolate2')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='1.0',
        )
        # The record and its movement arrive together, the way an entry
        # leaves them.
        record = _stock(
            client, mk_auth_headers, ingredient, mk_input_loc, unit_cost='2.00'
        )

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '10.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text

        # The record gave up the 10 the run drew.
        item_refreshed = db_session.execute(
            select(Item).where(Item.id == UUID(record['id']))
        ).scalar_one()
        assert item_refreshed.quantity == Decimal('90.000')

        resp = client.get('/api/v1/stats/reconciliation', headers=mk_auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # The shelf against the movement ledger: the run's draw wrote the
        # moves off the ingredient's shelf, and its output the move onto
        # the output's.
        assert data['quant_move_drift_count'] == 0, data
