"""Integration tests for recipe cost lines, BOM-line edits and org scoping.

Covers:
  - Cost-line CRUD (create / patch / delete / 404 / org-scoping)
  - BOM-line PATCH round-trip incl. ``uom_id`` exposure via GET detail
  - Catalog ``result`` = reference_price - last_unit_cost with real
    COMPLETED production orders (latest order wins)
  - Module settings org-scoping (MARGIN vs SAVINGS per org)
  - Order create rejects a recipe that belongs to another product (400)
  - Endpoints called by a user context without an organization → 403
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe
from app.modules.maker.tests.integration.test_production_consume_create import (
    _bom_line,
    _quant,
    _template,
)

pytestmark = pytest.mark.integration


def _create_recipe(
    client: TestClient,
    headers: dict[str, str],
    template_id: uuid.UUID,
    *,
    name: str = 'Recipe',
    **extra: Any,
) -> dict[str, Any]:
    """Create a recipe via the API and return the response body."""
    resp = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={'output_template_id': str(template_id), 'name': name, **extra},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _create_uom(db: Session) -> Uom:
    """Create a system-level UOM row (org-scoped UOMs need an org)."""
    category = UomCategory(organization_id=None, name='Weight')
    db.add(category)
    db.flush()
    uom = Uom(category_id=category.id, name='Kilogram', symbol='kg')
    db.add(uom)
    db.commit()
    db.refresh(uom)
    return uom


def _other_org_user(
    db: Session, h: ModuleTestHelper, *, email: str = 'other@example.com'
) -> tuple[Organization, User]:
    """Create a second organization + user for org-scoping tests."""
    org = h.create_org(
        'Other Org', ['core', 'items', 'locations', 'categories', 'maker']
    )
    user = h.create_user(org, email=email)
    return org, user


class TestCostLinesCrud:
    """POST/PATCH/DELETE /maker/recipes/{id}/cost-lines."""

    def test_create_cost_line_returns_201_and_appears_in_detail(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Candle')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)
        recipe = _create_recipe(client, mk_auth_headers, template.id, name='Soy')

        resp = client.post(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines',
            headers=mk_auth_headers,
            json={
                'kind': 'LABOR',
                'label': 'Hand-pouring',
                'amount': '5.50',
                'sort_order': 2,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body['kind'] == 'LABOR'
        assert body['label'] == 'Hand-pouring'
        assert Decimal(body['amount']) == Decimal('5.50')
        assert body['sort_order'] == 2
        assert body['recipe_id'] == recipe['id']

        # Detail must expose the cost line (was previously always []).
        detail = client.get(
            f'/api/v1/maker/recipes/{recipe["id"]}', headers=mk_auth_headers
        ).json()
        assert len(detail['cost_lines']) == 1
        assert detail['cost_lines'][0]['label'] == 'Hand-pouring'

    def test_patch_cost_line_updates_fields(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Soap')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)
        recipe = _create_recipe(client, mk_auth_headers, template.id, name='Lav')
        created = client.post(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines',
            headers=mk_auth_headers,
            json={'kind': 'OTHER', 'label': 'Packaging', 'amount': '1.00'},
        ).json()

        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines/{created["id"]}',
            headers=mk_auth_headers,
            json={'label': 'Premium Packaging', 'amount': '2.25', 'sort_order': 1},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['label'] == 'Premium Packaging'
        assert Decimal(body['amount']) == Decimal('2.25')
        assert body['sort_order'] == 1

    def test_delete_cost_line_returns_204(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Jam')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)
        recipe = _create_recipe(client, mk_auth_headers, template.id, name='Cherry')
        created = client.post(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines',
            headers=mk_auth_headers,
            json={'kind': 'LABOR', 'label': 'Stirring', 'amount': '0.50'},
        ).json()

        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines/{created["id"]}',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 204

        detail = client.get(
            f'/api/v1/maker/recipes/{recipe["id"]}', headers=mk_auth_headers
        ).json()
        assert detail['cost_lines'] == []

    def test_create_cost_line_unknown_recipe_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f'/api/v1/maker/recipes/{uuid.uuid4()}/cost-lines',
            headers=mk_auth_headers,
            json={'kind': 'LABOR', 'label': 'X', 'amount': '1.00'},
        )
        assert resp.status_code == 404

    def test_patch_missing_cost_line_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Bread')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)
        recipe = _create_recipe(client, mk_auth_headers, template.id, name='Rye')

        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines/{uuid.uuid4()}',
            headers=mk_auth_headers,
            json={'amount': '2.00'},
        )
        assert resp.status_code == 404

    def test_delete_missing_cost_line_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Tincture')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)
        recipe = _create_recipe(client, mk_auth_headers, template.id, name='Herb')

        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines/{uuid.uuid4()}',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 404

    def test_cost_line_other_org_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
        h: ModuleTestHelper,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Secret Soap')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)
        recipe = _create_recipe(client, mk_auth_headers, template.id, name='Secret')
        line = client.post(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines',
            headers=mk_auth_headers,
            json={'kind': 'LABOR', 'label': 'Secret labor', 'amount': '1.00'},
        ).json()

        _, other_user = _other_org_user(db_session, h)
        other_headers = h.get_auth_headers(other_user)

        # Create on another org's recipe → 404.
        resp = client.post(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines',
            headers=other_headers,
            json={'kind': 'LABOR', 'label': 'Hijack', 'amount': '1.00'},
        )
        assert resp.status_code == 404

        # Patch/delete another org's line → 404.
        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines/{line["id"]}',
            headers=other_headers,
            json={'amount': '99.00'},
        )
        assert resp.status_code == 404
        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines/{line["id"]}',
            headers=other_headers,
        )
        assert resp.status_code == 404


class TestBomLinePatch:
    """PATCH /maker/recipes/{id}/bom-lines/{line_id} — in-place edit."""

    def _make_recipe_with_line(
        self,
        client: TestClient,
        headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> tuple[MakerRecipe, BoMLine, ProductTemplate]:
        parent = _template(db_session, mk_org, name='Granola Bar')
        child = _template(db_session, mk_org, name='Oats')
        recipe = MakerRecipe(
            organization_id=mk_org.id,
            output_template_id=parent.id,
            name='Chewy Bar',
            batch_yield_qty=Decimal('1'),
            is_default=True,
        )
        db_session.add(recipe)
        db_session.commit()
        db_session.refresh(recipe)
        line = BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=parent.id,
            child_template_id=child.id,
            qty_per_batch=Decimal('1.0000'),
            unit='kg',
        )
        db_session.add(line)
        db_session.commit()
        db_session.refresh(line)
        return recipe, line, child

    def test_patch_bom_line_round_trip_via_detail(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        recipe, line, child = self._make_recipe_with_line(
            client, mk_auth_headers, mk_org, db_session
        )
        uom = _create_uom(db_session)

        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe.id}/bom-lines/{line.id}',
            headers=mk_auth_headers,
            json={
                'qty_per_batch': '2.5000',
                'uom_id': str(uom.id),
                'yield_loss_pct': '5.50',
                'notes': 'toasted oats',
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert Decimal(body['qty_per_batch']) == Decimal('2.5000')
        assert body['uom_id'] == str(uom.id)
        assert Decimal(body['yield_loss_pct']) == Decimal('5.50')
        assert body['notes'] == 'toasted oats'

        # GET detail round-trips the edited values incl. uom_id (bug: FE
        # in-place edit could PATCH uom_id but never read it back).
        detail = client.get(
            f'/api/v1/maker/recipes/{recipe.id}', headers=mk_auth_headers
        ).json()
        assert len(detail['lines']) == 1
        got = detail['lines'][0]
        assert got['id'] == str(line.id)
        assert got['child_template_id'] == str(child.id)
        assert got['child_template_name'] == 'Oats'
        assert Decimal(got['qty_per_batch']) == Decimal('2.5000')
        assert got['uom_id'] == str(uom.id)
        assert got['unit'] == 'kg'
        assert Decimal(got['yield_loss_pct']) == Decimal('5.50')
        assert got['notes'] == 'toasted oats'

    def test_patch_bom_line_other_org_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
        h: ModuleTestHelper,
    ) -> None:
        recipe, line, _child = self._make_recipe_with_line(
            client, mk_auth_headers, mk_org, db_session
        )
        _, other_user = _other_org_user(db_session, h, email='other2@example.com')

        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe.id}/bom-lines/{line.id}',
            headers=h.get_auth_headers(other_user),
            json={'qty_per_batch': '9.0000'},
        )
        assert resp.status_code == 404

    def test_patch_missing_bom_line_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Muesli')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)
        recipe = _create_recipe(client, mk_auth_headers, template.id, name='Muesli')

        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines/{uuid.uuid4()}',
            headers=mk_auth_headers,
            json={'qty_per_batch': '1.0000'},
        )
        assert resp.status_code == 404


class TestCatalogCostAndResult:
    """Catalog unit_cost from real COMPLETED orders + result/result_direction."""

    def _seed_and_complete_order(
        self,
        client: TestClient,
        headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
        input_loc: Any,
        output_loc: Any,
        *,
        qty: str,
    ) -> str:
        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=headers,
            json={
                'output_template_id': str(self.output.id),
                'planned_qty': qty,
                'output_location_id': str(output_loc.id),
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        order_id: str = create_resp.json()['id']
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text
        assert complete_resp.json()['status'] == 'COMPLETED'
        return order_id

    def test_catalog_result_after_completed_order(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: Any,
        mk_output_loc: Any,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Sugar')
        self.output = _template(db_session, mk_org, name='Jam')
        # Recipe first so it becomes the default — the BOM line and the
        # production order both resolve to it.
        _create_recipe(
            client,
            mk_auth_headers,
            self.output.id,
            name='Jam Recipe',
            reference_price='5.00',
        )
        _bom_line(
            db_session,
            mk_org,
            parent_id=self.output.id,
            child_id=ingredient.id,
            qty='1.0',
        )
        _quant(
            client,
            mk_auth_headers,
            db_session,
            ingredient,
            mk_input_loc.id,
            '5.000',
            unit_cost='2.00',
        )

        self._seed_and_complete_order(
            client,
            mk_auth_headers,
            mk_org,
            db_session,
            mk_input_loc,
            mk_output_loc,
            qty='2.000',
        )

        resp = client.get('/api/v1/maker/recipes', headers=mk_auth_headers)
        assert resp.status_code == 200
        item = next(i for i in resp.json()['items'] if i['name'] == 'Jam Recipe')
        # total_cost 4.00 / 2 units = 2.00 per unit.
        assert Decimal(item['unit_cost']) == Decimal('2.00')
        # result = reference_price - last_unit_cost = 5.00 - 2.00 = 3.00.
        assert Decimal(item['result']) == Decimal('3.00')
        assert item['reference_direction'] == 'MARGIN'
        assert item['last_produced_at'] is not None

    def test_catalog_latest_completed_order_wins(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: Any,
        mk_output_loc: Any,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Flour')
        self.output = _template(db_session, mk_org, name='Bread')
        # Recipe first so it becomes the default (see helper docstring note).
        _create_recipe(
            client,
            mk_auth_headers,
            self.output.id,
            name='Bread Recipe',
            reference_price='10.00',
        )
        _bom_line(
            db_session,
            mk_org,
            parent_id=self.output.id,
            child_id=ingredient.id,
            qty='1.0',
        )
        # Exactly what order 1 consumes, so this layer is drained by it — and
        # it now really is: a run posts an outgoing layer for what it ate,
        # which it never used to, so this layer stayed on the books with its
        # full quantity and kept dragging the rate down long after the flour
        # had been baked.
        _quant(
            client,
            mk_auth_headers,
            db_session,
            ingredient,
            mk_input_loc.id,
            '2.000',
            unit_cost='2.00',
        )

        # Order 1 at rate 2.00 → unit_cost 2.00.
        self._seed_and_complete_order(
            client,
            mk_auth_headers,
            mk_org,
            db_session,
            mk_input_loc,
            mk_output_loc,
            qty='2.000',
        )
        # A dearer delivery, and nothing older left to consume: order 1 took
        # the last of the 2.00 flour, so the second run eats the 4.00 flour
        # and costs what that flour cost. This used to read 3.67 — the average
        # of ten units at 4.00 and two at 2.00 that had already been baked.
        _quant(
            client,
            mk_auth_headers,
            db_session,
            ingredient,
            mk_input_loc.id,
            '10.000',
            unit_cost='4.00',
        )
        self._seed_and_complete_order(
            client,
            mk_auth_headers,
            mk_org,
            db_session,
            mk_input_loc,
            mk_output_loc,
            qty='1.000',
        )

        resp = client.get('/api/v1/maker/recipes', headers=mk_auth_headers)
        item = next(i for i in resp.json()['items'] if i['name'] == 'Bread Recipe')
        # Latest completed order wins: the second order's 4.00, not the
        # first order's 2.00.
        assert Decimal(item['unit_cost']) == Decimal('4.00')
        assert Decimal(item['result']) == Decimal('6.00')
        assert item['reference_direction'] == 'MARGIN'

    def test_catalog_result_null_without_reference_price(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: Any,
        mk_output_loc: Any,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Honey')
        self.output = _template(db_session, mk_org, name='Granola')
        # No reference_price on purpose. Recipe first so the BOM line and
        # the order resolve to it (default).
        _create_recipe(client, mk_auth_headers, self.output.id, name='Plain Granola')
        _bom_line(
            db_session,
            mk_org,
            parent_id=self.output.id,
            child_id=ingredient.id,
            qty='0.5',
        )
        _quant(
            client,
            mk_auth_headers,
            db_session,
            ingredient,
            mk_input_loc.id,
            '5.000',
            unit_cost='1.00',
        )

        self._seed_and_complete_order(
            client,
            mk_auth_headers,
            mk_org,
            db_session,
            mk_input_loc,
            mk_output_loc,
            qty='2.000',
        )

        resp = client.get('/api/v1/maker/recipes', headers=mk_auth_headers)
        item = next(i for i in resp.json()['items'] if i['name'] == 'Plain Granola')
        assert Decimal(item['unit_cost']) == Decimal('0.50')
        # No reference_price → no result (null, not zero).
        assert item['result'] is None
        assert item['reference_direction'] == 'MARGIN'


class TestSettingsOrgScoping:
    """Each org has an independent maker_module_settings row."""

    def test_settings_independent_per_org(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        h: ModuleTestHelper,
    ) -> None:
        # Org A switches to SAVINGS.
        resp = client.patch(
            '/api/v1/maker/settings',
            headers=mk_auth_headers,
            json={'reference_direction': 'SAVINGS'},
        )
        assert resp.status_code == 200
        assert resp.json()['reference_direction'] == 'SAVINGS'

        # Org B still gets the MARGIN default — no leakage between orgs.
        _, other_user = _other_org_user(db_session, h, email='org-b@example.com')
        resp = client.get(
            '/api/v1/maker/settings', headers=h.get_auth_headers(other_user)
        )
        assert resp.status_code == 200
        assert resp.json()['reference_direction'] == 'MARGIN'

        # Org A unchanged.
        resp = client.get('/api/v1/maker/settings', headers=mk_auth_headers)
        assert resp.json()['reference_direction'] == 'SAVINGS'


class TestOrderRecipeValidation:
    """POST /production/orders must reject a recipe of another product."""

    def test_create_order_with_mismatched_recipe_returns_400(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: Any,
        db_session: Session,
    ) -> None:
        product_a = _template(db_session, mk_org, name='Product A')
        product_b = _template(db_session, mk_org, name='Product B')
        recipe_a = _create_recipe(
            client, mk_auth_headers, product_a.id, name='Recipe A'
        )

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(product_b.id),
                'recipe_id': recipe_a['id'],
                'planned_qty': '5.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert resp.status_code == 400, resp.text
        detail = resp.json()['detail']
        detail_str = detail if isinstance(detail, str) else str(detail)
        assert 'bom' in detail_str.lower()
        assert 'product' in detail_str.lower()

    def test_create_order_with_matching_recipe_still_works(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: Any,
        db_session: Session,
    ) -> None:
        product = _template(db_session, mk_org, name='Product C')
        recipe = _create_recipe(client, mk_auth_headers, product.id, name='Recipe C')

        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(product.id),
                'recipe_id': recipe['id'],
                'planned_qty': '5.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()['recipe_id'] == recipe['id']


class TestNoOrganization403:
    """Endpoints must 403 when the user context has no organization."""

    def _orphan_headers(
        self, db_session: Session, h: ModuleTestHelper
    ) -> dict[str, str]:
        orphan = User(
            email='orphan@example.com',
            hashed_password='not-a-real-hash',
            full_name='Orphan',
            role='admin',
            is_active=True,
            organization_id=None,
        )
        db_session.add(orphan)
        db_session.commit()
        db_session.refresh(orphan)
        return h.get_auth_headers(orphan)

    def test_catalog_without_org_returns_403(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
    ) -> None:
        headers = self._orphan_headers(db_session, h)
        resp = client.get('/api/v1/maker/recipes', headers=headers)
        assert resp.status_code == 403

    def test_create_recipe_without_org_returns_403(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
    ) -> None:
        headers = self._orphan_headers(db_session, h)
        resp = client.post(
            '/api/v1/maker/recipes',
            headers=headers,
            json={
                'output_template_id': str(uuid.uuid4()),
                'name': 'No Org Recipe',
            },
        )
        assert resp.status_code == 403
