"""Integration tests for the availability check + shortage strategy.

Test contract:
  - Availability per-location, fallback global per ``availability_check_scope``
  - max_batches correctly computed (bottleneck ingredient)
  - Shortage list in recipe unit when UoM conversion impossible
  - ``available = physical − reserved`` (the records' view)
  - Create with ALLOW/WARN/BLOCK strategy behaviour
  - Complete → 422 with actionable shortage list
  - Settings: new knobs GET/PATCH round-trip
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.i18n.service import get_error_message
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.modules.maker.models import (
    BoMLine,
    MakerModuleSettings,
    MakerRecipe,
)
from tests.integration._shelf import (
    post_on_shelf,
    reserve_for_an_order,
    run_in_async_session,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers (same patterns as test_production_actual_qty_and_fixed_costs.py)
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


def _recipe(
    db: Session,
    org: Organization,
    template_id: UUID,
    *,
    batch_yield_qty: str = '1',
    name: str = 'Test Recipe',
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=template_id,
        name=name,
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
    recipe_id: UUID,
    parent_id: UUID,
    child_id: UUID,
    qty: str = '1.0',
    unit: str = 'szt',
    uom_id: UUID | None = None,
) -> BoMLine:
    line = BoMLine(
        organization_id=org.id,
        recipe_id=recipe_id,
        parent_template_id=parent_id,
        child_template_id=child_id,
        qty_per_batch=Decimal(qty),
        unit=unit,
        uom_id=uom_id,
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
    qty: str,
) -> dict[str, Any]:
    """Put *qty* of *template* on the shelf as one record, as a person's entry does."""
    return post_on_shelf(client, headers, template, location.id, qty)


def _set_settings(
    db: Session,
    org_id: UUID,
    *,
    create_on_shortage_strategy: str = 'ALLOW',
    availability_check_scope: str = 'GLOBAL',
) -> None:
    settings = (
        db.query(MakerModuleSettings)
        .filter(MakerModuleSettings.organization_id == org_id)
        .first()
    )
    if settings is None:
        settings = MakerModuleSettings(organization_id=org_id)
        db.add(settings)
    settings.create_on_shortage_strategy = create_on_shortage_strategy
    settings.availability_check_scope = availability_check_scope
    db.commit()


def _uom_category(db: Session, org: Organization, *, name: str) -> UomCategory:
    cat = UomCategory(
        organization_id=org.id,
        name=f'{name}-{uuid.uuid4().hex[:8]}',
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _uom(
    db: Session,
    org: Organization,
    *,
    category_id: UUID,
    symbol: str,
    factor: float,
) -> Uom:
    u = Uom(
        organization_id=org.id,
        category_id=category_id,
        name=f'{symbol}-{uuid.uuid4().hex[:8]}',
        symbol=symbol,
        factor=factor,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------------------------------------------------------------------------
# Settings: new knobs round-trip
# ---------------------------------------------------------------------------


class TestShortageSettings:
    """availability_check_scope + create_on_shortage_strategy GET/PATCH."""

    def test_default_values(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get('/api/v1/maker/settings', headers=mk_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body['availability_check_scope'] == 'GLOBAL'
        # WARN: an order over stock still gets created, but with a warning.
        assert body['create_on_shortage_strategy'] == 'WARN'

    def test_the_read_schema_defaults_to_what_the_column_does(self) -> None:
        """The settings row and the schema that reads it name one default.

        The column defaults to WARN and the read schema said ALLOW, so the
        published API contract promised a strategy no organization starts
        with.
        """
        from app.modules.maker._schemas_recipes import MakerSettingsRead

        column = MakerModuleSettings.__table__.c.create_on_shortage_strategy
        field = MakerSettingsRead.model_fields['create_on_shortage_strategy']
        assert field.default == column.default.arg == 'WARN'

    def test_patch_round_trip(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        resp = client.patch(
            '/api/v1/maker/settings',
            headers=mk_auth_headers,
            json={
                'availability_check_scope': 'PER_LOCATION',
                'create_on_shortage_strategy': 'BLOCK',
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['availability_check_scope'] == 'PER_LOCATION'
        assert body['create_on_shortage_strategy'] == 'BLOCK'

        # Verify persisted
        resp = client.get('/api/v1/maker/settings', headers=mk_auth_headers)
        assert resp.json()['availability_check_scope'] == 'PER_LOCATION'
        assert resp.json()['create_on_shortage_strategy'] == 'BLOCK'

    def test_patch_invalid_value_rejected(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        resp = client.patch(
            '/api/v1/maker/settings',
            headers=mk_auth_headers,
            json={'create_on_shortage_strategy': 'INVALID'},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Availability endpoint
# ---------------------------------------------------------------------------


class TestAvailabilityEndpoint:
    """GET /maker/recipes/{id}/availability."""

    def test_availability_sufficient_stock(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='Jam')
        flour = _template(db_session, mk_org, name='Flour')
        recipe = _recipe(db_session, mk_org, output.id, batch_yield_qty='12')
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=flour.id,
            qty='2',
        )
        _stock(client, mk_auth_headers, flour, mk_input_loc, '50')

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability?batches=1',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['has_shortage'] is False
        assert len(body['ingredients']) == 1
        ing = body['ingredients'][0]
        assert Decimal(ing['needed']) == Decimal('2')
        assert Decimal(ing['available']) == Decimal('50')
        assert Decimal(ing['shortage']) == Decimal('0')

    def test_availability_shortage(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='Candle')
        wax = _template(db_session, mk_org, name='Wax')
        recipe = _recipe(db_session, mk_org, output.id, batch_yield_qty='1')
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=wax.id,
            qty='5',
        )
        # Only 3 available, need 5 for 1 batch.
        _stock(client, mk_auth_headers, wax, mk_input_loc, '3')

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability?batches=1',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['has_shortage'] is True
        ing = body['ingredients'][0]
        assert Decimal(ing['needed']) == Decimal('5')
        assert Decimal(ing['available']) == Decimal('3')
        assert Decimal(ing['shortage']) == Decimal('2')

    def test_max_batches_bottleneck(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='Soap')
        oil = _template(db_session, mk_org, name='Oil')
        lye = _template(db_session, mk_org, name='Lye')
        recipe = _recipe(db_session, mk_org, output.id, batch_yield_qty='1')
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=oil.id,
            qty='2',
        )
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=lye.id,
            qty='1',
        )
        # Oil: 10 in stock, need 2/batch → 5 batches
        # Lye: 3 in stock, need 1/batch → 3 batches  ← bottleneck
        _stock(client, mk_auth_headers, oil, mk_input_loc, '10')
        _stock(client, mk_auth_headers, lye, mk_input_loc, '3')

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert Decimal(body['max_batches']) == Decimal('3')

    def test_max_batches_goes_out_as_a_plain_number(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
    ) -> None:
        """Ten batches read "Max batches from stock: 1E+1" on the BOM header."""
        output = _template(db_session, mk_org, name='Flavoured oil')
        oil = _template(db_session, mk_org, name='Oil')
        recipe = _recipe(db_session, mk_org, output.id, batch_yield_qty='1')
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=oil.id,
            qty='1',
        )
        _stock(client, mk_auth_headers, oil, mk_input_loc, '10')

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 200
        assert resp.json()['max_batches'] == '10'

    def test_max_batches_is_whole_batches(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
    ) -> None:
        """A batch is made or it is not — 2.5 of them is not an answer.

        The catalog offered "Max batches from stock: 568.1818" for a tray
        bake. The division was quantised to four decimals and sent as it
        stood, so the screen invited a quantity nobody can produce.
        """
        output = _template(db_session, mk_org, name='Apple cake')
        flour = _template(db_session, mk_org, name='Flour')
        recipe = _recipe(db_session, mk_org, output.id, batch_yield_qty='1')
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=flour.id,
            qty='2',
        )
        # 5 in stock, 2 per batch → two whole cakes and half the flour for
        # a third, which is two cakes.
        _stock(client, mk_auth_headers, flour, mk_input_loc, '5')

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 200
        assert Decimal(resp.json()['max_batches']) == Decimal('2')

    def test_stock_short_of_one_batch_is_no_batches(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='Bread')
        flour = _template(db_session, mk_org, name='Rye flour')
        # Flour is weighed, so a shelf can hold 1.8 of it; a counted unit
        # takes whole numbers only.
        flour.uom_id = (
            db_session.scalars(
                select(Uom).where(Uom.symbol == 'kg', Uom.organization_id.is_(None))
            )
            .one()
            .id
        )
        db_session.commit()
        recipe = _recipe(db_session, mk_org, output.id, batch_yield_qty='1')
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=flour.id,
            qty='2',
        )
        _stock(client, mk_auth_headers, flour, mk_input_loc, '1.8')

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability?batches=1',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert Decimal(body['max_batches']) == Decimal('0')
        # Not "almost": 1.8 of the 2 needed is short, and 0.9 batches was
        # the number the screen used to offer instead.
        assert body['has_shortage'] is True

    def test_available_excludes_reserved(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        output = _template(db_session, mk_org, name='Product')
        ingredient = _template(db_session, mk_org, name='Ingredient')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='5',
        )
        # Physical 10, reserved 4 → available 6
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, '10')
        run_in_async_session(
            async_engine_fixture,
            lambda session: reserve_for_an_order(
                session, ingredient, mk_input_loc.id, '4'
            ),
        )

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability?batches=1',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        ing = resp.json()['ingredients'][0]
        assert Decimal(ing['available']) == Decimal('6')

    def test_per_location_scope(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_storage_type: StorageType,
        mk_user: User,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        loc_a = h.create_storage_location(
            mk_org, mk_storage_type, mk_user, name='Loc A'
        )
        loc_b = h.create_storage_location(
            mk_org, mk_storage_type, mk_user, name='Loc B'
        )

        output = _template(db_session, mk_org, name='Item')
        ingredient = _template(db_session, mk_org, name='Component')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='5',
        )
        # 3 at loc_a, 10 at loc_b
        _stock(client, mk_auth_headers, ingredient, loc_a, '3')
        _stock(client, mk_auth_headers, ingredient, loc_b, '10')

        # Global: 13 total → no shortage.
        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability?batches=1',
            headers=mk_auth_headers,
        )
        assert resp.json()['has_shortage'] is False
        assert Decimal(resp.json()['ingredients'][0]['available']) == Decimal('13')

        # Per-location A: only 3 → shortage of 2.
        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability?batches=1'
            f'&location_id={loc_a.id}',
            headers=mk_auth_headers,
        )
        assert resp.json()['has_shortage'] is True
        assert Decimal(resp.json()['ingredients'][0]['available']) == Decimal('3')

    def test_recipe_not_found_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            f'/api/v1/maker/recipes/{uuid.uuid4()}/availability',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Create flow: create_on_shortage_strategy
# ---------------------------------------------------------------------------


class TestCreateShortageStrategy:
    """POST /production/orders respects create_on_shortage_strategy."""

    def test_allow_strategy_creates_despite_shortage(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='Output')
        ingredient = _template(db_session, mk_org, name='Ingredient')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='100',
        )
        # No stock at all.
        _set_settings(db_session, mk_org.id, create_on_shortage_strategy='ALLOW')

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert resp.status_code == 201
        assert resp.json()['status'] == 'DRAFT'

    def test_block_strategy_rejects_on_shortage(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='Blocked')
        ingredient = _template(db_session, mk_org, name='Missing')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='100',
        )
        # No stock.
        _set_settings(db_session, mk_org.id, create_on_shortage_strategy='BLOCK')

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert resp.status_code == 422
        body = resp.json()
        assert 'detail' in body
        # Shortage list should mention the missing ingredient.
        detail_str = str(body['detail'])
        assert 'Missing' in detail_str or 'shortage' in detail_str.lower()

    def test_block_strategy_allows_when_stock_sufficient(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        mk_input_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='OK')
        ingredient = _template(db_session, mk_org, name='Available')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='5',
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, '10')
        _set_settings(db_session, mk_org.id, create_on_shortage_strategy='BLOCK')

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert resp.status_code == 201

    def test_warn_strategy_returns_warning(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='Warned')
        ingredient = _template(db_session, mk_org, name='Low')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='100',
        )
        # Only 5 in stock.
        _set_settings(db_session, mk_org.id, create_on_shortage_strategy='WARN')

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        # WARN without confirm raises ShortageWarningError, which the router
        # turns into a 422 carrying the shortage payload. A 200 here would mean
        # the order was created despite the shortage — the opposite outcome.
        assert resp.status_code == 422
        body = resp.json()
        detail_str = str(body)
        assert 'shortage' in detail_str.lower() or 'warning' in detail_str.lower()

    def test_warn_strategy_creates_with_confirm(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='WarnConfirm')
        ingredient = _template(db_session, mk_org, name='Low2')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='100',
        )
        _set_settings(db_session, mk_org.id, create_on_shortage_strategy='WARN')

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
                'confirm_shortage': True,
            },
        )
        assert resp.status_code == 201
        assert resp.json()['status'] == 'DRAFT'

    def test_block_is_not_lifted_by_a_confirmation(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        """A confirmation answers a warning; a block is not a question.

        ``confirm_shortage`` exists for the WARN dialog. The screen never
        sends it under BLOCK, but an API client could, and the draft BLOCK
        exists to refuse was created.
        """
        output = _template(db_session, mk_org, name='Still blocked')
        ingredient = _template(db_session, mk_org, name='Absent')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='100',
        )
        _set_settings(db_session, mk_org.id, create_on_shortage_strategy='BLOCK')

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
                'confirm_shortage': True,
            },
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()['detail']['error'] == 'shortage_blocked'

    @pytest.mark.parametrize(
        ('strategy', 'expected'), [('BLOCK', 422), ('WARN', 201), ('ALLOW', 201)]
    )
    def test_a_copy_is_a_plan_the_strategy_has_a_say_over(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        strategy: str,
        expected: int,
    ) -> None:
        """Duplicating a run over stock is creating one, so BLOCK refuses it.

        The copy never asked: an organization that blocks plans over stock
        had one in its list from a single click on an old order. WARN lets
        the copy through — it opens on its own page, which names the
        shortage.
        """
        output = _template(db_session, mk_org, name=f'Copied {strategy}')
        ingredient = _template(db_session, mk_org, name=f'Gone {strategy}')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='100',
        )
        _set_settings(db_session, mk_org.id, create_on_shortage_strategy='ALLOW')
        source = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert source.status_code == 201, source.text
        _set_settings(db_session, mk_org.id, create_on_shortage_strategy=strategy)

        resp = client.post(
            f'/api/v1/maker/production/orders/{source.json()["id"]}/duplicate',
            headers=mk_auth_headers,
        )

        assert resp.status_code == expected, resp.text
        if expected == 422:
            assert resp.json()['detail']['error'] == 'shortage_blocked'
        else:
            assert resp.json()['status'] == 'DRAFT'
            assert resp.json()['shortage_count'] == 1


# ---------------------------------------------------------------------------
# Complete flow: actionable 422 with shortage list
# ---------------------------------------------------------------------------


class TestCompleteShortage422:
    """complete_production returns 422 (not 500) with a shortage list."""

    def test_complete_shortage_returns_422(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='CompleteShort')
        ingredient = _template(db_session, mk_org, name='ShortIngredient')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='100',
        )
        _set_settings(db_session, mk_org.id, create_on_shortage_strategy='ALLOW')

        # Create DRAFT (ALLOW lets us create despite shortage).
        create = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create.status_code == 201
        order_id = create.json()['id']

        # Complete → should 422 with shortage detail.
        resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 422
        body = resp.json()
        detail_str = str(body['detail'])
        assert 'ShortIngredient' in detail_str or 'shortage' in detail_str.lower()


# ---------------------------------------------------------------------------
# The refusals' bodies: what the shortage dialogs read, in the shared envelope
# ---------------------------------------------------------------------------


class TestShortageRefusalBodies:
    """Each refusal keeps the keys its dialog reads and adds a code and a sentence."""

    #: ``ShortageEntry`` in the frontend's maker types: the columns of the dialog.
    ENTRY_KEYS = {
        'child_template_id',
        'child_template_name',
        'needed',
        'available',
        'shortage',
        'uom_symbol',
        'convertible',
        'available_uom_symbol',
    }

    def _short_recipe(
        self,
        db_session: Session,
        org: Organization,
        *,
        strategy: str,
    ) -> tuple[ProductTemplate, ProductTemplate]:
        output = _template(db_session, org, name=f'Bodies {strategy}')
        ingredient = _template(db_session, org, name=f'Bodies {strategy} ingredient')
        recipe = _recipe(db_session, org, output.id)
        _bom_line(
            db_session,
            org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='100',
        )
        _set_settings(db_session, org.id, create_on_shortage_strategy=strategy)
        return output, ingredient

    def _assert_body(
        self,
        detail: dict[str, Any],
        *,
        error: str,
        ingredient: ProductTemplate,
        **context: Any,
    ) -> None:
        shortages = detail.pop('shortages')
        assert detail == {
            'code': error,
            'message': get_error_message('production_short_of_stock', 'en'),
            'error': error,
            **context,
        }
        assert len(shortages) == 1
        assert set(shortages[0]) == self.ENTRY_KEYS
        assert shortages[0]['child_template_id'] == str(ingredient.id)
        assert shortages[0]['child_template_name'] == ingredient.name

    @pytest.mark.parametrize(
        ('strategy', 'error'),
        [('BLOCK', 'shortage_blocked'), ('WARN', 'shortage_warning')],
    )
    def test_creating_over_stock(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        strategy: str,
        error: str,
    ) -> None:
        output, ingredient = self._short_recipe(db_session, mk_org, strategy=strategy)

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        )

        assert resp.status_code == 422
        self._assert_body(resp.json()['detail'], error=error, ingredient=ingredient)

    def test_completing_over_stock(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output, ingredient = self._short_recipe(db_session, mk_org, strategy='ALLOW')
        create = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create.status_code == 201, create.text

        resp = client.post(
            f'/api/v1/maker/production/orders/{create.json()["id"]}/complete',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 422
        self._assert_body(
            resp.json()['detail'],
            error='insufficient_stock',
            ingredient=ingredient,
            short_at_create=True,
        )


# ---------------------------------------------------------------------------
# availability_check_scope actually drives the checks (audit fix)
# ---------------------------------------------------------------------------


class TestScopeSettingEnforced:
    """``availability_check_scope`` must influence endpoint, create and complete.

    Semantics: an explicit ``location_id`` query param always wins. Without it,
    PER_LOCATION checks stock at the order's output location; when no location
    context exists (availability endpoint without ``location_id``), the check
    falls back to GLOBAL.
    """

    def test_endpoint_per_location_without_location_falls_back_to_global(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_storage_type: StorageType,
        mk_user: User,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        loc_a = h.create_storage_location(mk_org, mk_storage_type, mk_user, name='A')
        loc_b = h.create_storage_location(mk_org, mk_storage_type, mk_user, name='B')

        output = _template(db_session, mk_org, name='ScopeFallback')
        ingredient = _template(db_session, mk_org, name='ScopeFallbackIng')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='5',
        )
        _stock(client, mk_auth_headers, ingredient, loc_a, '3')
        _stock(client, mk_auth_headers, ingredient, loc_b, '10')
        _set_settings(db_session, mk_org.id, availability_check_scope='PER_LOCATION')

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability?batches=1',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        # No location context → GLOBAL fallback: 13 available, no shortage.
        assert resp.json()['has_shortage'] is False
        assert Decimal(resp.json()['ingredients'][0]['available']) == Decimal('13')

    def test_create_per_location_checks_order_location(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_storage_type: StorageType,
        mk_user: User,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        loc_out = h.create_storage_location(
            mk_org, mk_storage_type, mk_user, name='OutLoc'
        )
        loc_other = h.create_storage_location(
            mk_org, mk_storage_type, mk_user, name='OtherLoc'
        )

        output = _template(db_session, mk_org, name='ScopedOutput')
        ingredient = _template(db_session, mk_org, name='ScopedIng')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='5',
        )
        # Stock exists ONLY at another location — globally sufficient (10 >= 5),
        # but nothing at the order's output location.
        _stock(client, mk_auth_headers, ingredient, loc_other, '10')
        _set_settings(
            db_session,
            mk_org.id,
            create_on_shortage_strategy='BLOCK',
            availability_check_scope='PER_LOCATION',
        )

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(loc_out.id),
            },
        )
        assert resp.status_code == 422
        assert resp.json()['detail']['error'] == 'shortage_blocked'

        # GLOBAL scope → the same create succeeds (stock summed across locations).
        _set_settings(
            db_session,
            mk_org.id,
            create_on_shortage_strategy='BLOCK',
            availability_check_scope='GLOBAL',
        )
        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(loc_out.id),
            },
        )
        assert resp.status_code == 201

    def test_complete_per_location_checks_order_location(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_storage_type: StorageType,
        mk_user: User,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        loc_out = h.create_storage_location(
            mk_org, mk_storage_type, mk_user, name='CompleteOut'
        )
        loc_other = h.create_storage_location(
            mk_org, mk_storage_type, mk_user, name='CompleteOther'
        )

        output = _template(db_session, mk_org, name='CompleteScoped')
        ingredient = _template(db_session, mk_org, name='CompleteScopedIng')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='5',
        )
        _stock(client, mk_auth_headers, ingredient, loc_other, '10')
        _set_settings(
            db_session,
            mk_org.id,
            create_on_shortage_strategy='ALLOW',
            availability_check_scope='PER_LOCATION',
        )

        create = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(loc_out.id),
            },
        )
        assert create.status_code == 201
        order_id = create.json()['id']

        # PER_LOCATION: nothing at the order location → actionable 422,
        # even though global stock (10) would suffice.
        resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()['detail']['error'] == 'insufficient_stock'


# ---------------------------------------------------------------------------
# UoM conversion through availability (audit fix: nested lines + legacy unit)
# ---------------------------------------------------------------------------


class TestAvailabilityUomConversion:
    """Structural UoM conversion in availability and shortage lists."""

    def test_converts_stock_uom_to_recipe_uom(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
    ) -> None:
        weight = _uom_category(db_session, mk_org, name='Weight')
        kg = _uom(db_session, mk_org, category_id=weight.id, symbol='kg', factor=1000.0)
        g = _uom(db_session, mk_org, category_id=weight.id, symbol='g', factor=1.0)

        output = _template(db_session, mk_org, name='ConvOut')
        ingredient = _template(db_session, mk_org, name='ConvIng')
        ingredient.uom_id = g.id
        db_session.commit()
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='5',
            unit='kg',
            uom_id=kg.id,
        )
        # 4000 g in stock = 4 kg; recipe needs 5 kg → shortage 1 kg.
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, '4000')

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability?batches=1',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        ing = resp.json()['ingredients'][0]
        assert Decimal(ing['available']) == Decimal('4')
        assert Decimal(ing['shortage']) == Decimal('1')
        assert ing['convertible'] is True
        assert ing['uom_symbol'] == 'kg'

    def test_nested_subrecipe_line_uom_converts(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
    ) -> None:
        """Leaves reached via a sub-recipe must keep their line UoM (audit fix)."""
        weight = _uom_category(db_session, mk_org, name='WeightN')
        kg = _uom(db_session, mk_org, category_id=weight.id, symbol='kg', factor=1000.0)
        g = _uom(db_session, mk_org, category_id=weight.id, symbol='g', factor=1.0)

        output = _template(db_session, mk_org, name='NestOut')
        sub = _template(db_session, mk_org, name='NestSub')
        leaf = _template(db_session, mk_org, name='NestLeaf')
        leaf.uom_id = g.id
        db_session.commit()

        # Sub-recipe: 0.5 kg of leaf per batch.
        sub_recipe = _recipe(db_session, mk_org, sub.id, name='Sub recipe')
        _bom_line(
            db_session,
            mk_org,
            recipe_id=sub_recipe.id,
            parent_id=sub.id,
            child_id=leaf.id,
            qty='0.5',
            unit='kg',
            uom_id=kg.id,
        )
        # Parent recipe: 2 sub-assemblies per batch → 1 kg leaf per batch.
        parent_recipe = _recipe(db_session, mk_org, output.id, name='Parent recipe')
        _bom_line(
            db_session,
            mk_org,
            recipe_id=parent_recipe.id,
            parent_id=output.id,
            child_id=sub.id,
            qty='2',
        )
        # 4000 g = 4 kg available; need 1 kg → converted available must be 4 kg,
        # not the raw 4000 (regression: nested leaves lost their line UoM).
        _stock(client, mk_auth_headers, leaf, mk_input_loc, '4000')

        resp = client.get(
            f'/api/v1/maker/recipes/{parent_recipe.id}/availability?batches=1',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        ing = resp.json()['ingredients'][0]
        assert ing['child_template_name'] == 'NestLeaf'
        assert Decimal(ing['available']) == Decimal('4')
        assert ing['convertible'] is True
        assert resp.json()['has_shortage'] is False
        assert Decimal(resp.json()['max_batches']) == Decimal('4')

    def test_cross_dimension_marks_not_convertible(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
    ) -> None:
        weight = _uom_category(db_session, mk_org, name='WeightX')
        volume = _uom_category(db_session, mk_org, name='VolumeX')
        kg = _uom(db_session, mk_org, category_id=weight.id, symbol='kg', factor=1000.0)
        liter = _uom(db_session, mk_org, category_id=volume.id, symbol='l', factor=1.0)

        output = _template(db_session, mk_org, name='XDimOut')
        ingredient = _template(db_session, mk_org, name='XDimIng')
        ingredient.uom_id = liter.id
        db_session.commit()
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='5',
            unit='kg',
            uom_id=kg.id,
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, '100')

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe.id}/availability?batches=1',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        ing = body['ingredients'][0]
        assert ing['convertible'] is False
        # Raw (unconverted) stock is reported — no silent failure.
        assert Decimal(ing['available']) == Decimal('100')
        # ...and it is labelled with the unit it was counted in, not the
        # recipe's, so "100 l" never renders as "100 kg".
        assert ing['available_uom_symbol'] == 'l'
        assert ing['uom_symbol'] == 'kg'
        # No verdict is invented from two incomparable measures.
        assert ing['shortage'] is None
        assert body['max_batches'] is None
        assert body['has_shortage'] is False
        assert body['has_unknown'] is True

    def test_shortage_list_falls_back_to_legacy_unit(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        """Lines without ``uom_id`` surface their legacy ``unit`` string."""
        output = _template(db_session, mk_org, name='LegacyOut')
        ingredient = _template(db_session, mk_org, name='LegacyIng')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='5',
            unit='kg',
        )
        _set_settings(db_session, mk_org.id, create_on_shortage_strategy='BLOCK')

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert resp.status_code == 422
        shortages = resp.json()['detail']['shortages']
        assert shortages[0]['uom_symbol'] == 'kg'


# ---------------------------------------------------------------------------
# Regression: legacy orders without recipe_id must still complete
# ---------------------------------------------------------------------------


class TestLegacyOrderComplete:
    """Orders created before recipe snapshotting have ``recipe_id = None``."""

    def test_complete_legacy_order_without_recipe(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_user: User,
        mk_output_loc: StorageLocation,
        mk_input_loc: StorageLocation,
    ) -> None:
        from app.modules.maker.models import ProductionOrder

        output = _template(db_session, mk_org, name='LegacyProd')
        ingredient = _template(db_session, mk_org, name='LegacyProdIng')
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='2',
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, '10')
        order = ProductionOrder(
            organization_id=mk_org.id,
            output_template_id=output.id,
            recipe_id=None,
            planned_qty=Decimal('1'),
            output_storage_location_id=mk_output_loc.id,
            status='DRAFT',
            created_by=mk_user.id,
        )
        db_session.add(order)
        db_session.commit()
        db_session.refresh(order)

        resp = client.post(
            f'/api/v1/maker/production/orders/{order.id}/complete',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['status'] == 'COMPLETED'
