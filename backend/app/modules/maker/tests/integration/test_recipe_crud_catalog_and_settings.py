"""Integration tests for recipe CRUD, catalog, settings and recipe resolution.

Test contract:
  - CRUD happy path + 404/409
  - Org-scoping
  - Catalog sorting/last_unit_cost
  - GET/PATCH /maker/settings round-trip (default reference_direction=MARGIN)
  - POST /production/orders without recipe_id → lookup default
  - POST /production/orders without recipe → 400
  - Old /bom POST adapter still works
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User

from .conftest import post_bom_line

pytestmark = pytest.mark.integration


class TestRecipeCrud:
    """POST/PATCH/DELETE /maker/recipes/{id}."""

    def test_create_recipe_returns_201(
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

        resp = client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'name': 'Soy Candle',
                'batch_yield_qty': '12',
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body['name'] == 'Soy Candle'
        assert body['is_default'] is True  # first recipe → auto default
        assert body['output_template_name'] == 'Candle'
        assert body['batch_yield_qty'] == '12.0000'

    def test_get_recipe_returns_detail(
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

        created = client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'name': 'Lavender Soap',
                'process_steps': ['Melt', 'Pour', 'Cure 4 weeks'],
            },
        )
        recipe_id = created.json()['id']

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe_id}',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['name'] == 'Lavender Soap'
        assert body['process_steps'] == ['Melt', 'Pour', 'Cure 4 weeks']

    def test_get_recipe_not_found_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            f'/api/v1/maker/recipes/{uuid.uuid4()}',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 404

    def test_patch_recipe_updates_fields(
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

        created = client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'name': 'Original',
                'batch_yield_qty': '1',
            },
        )
        recipe_id = created.json()['id']

        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe_id}',
            headers=mk_auth_headers,
            json={
                'name': 'Renamed',
                'batch_yield_qty': '6',
                'reference_price': '25.00',
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['name'] == 'Renamed'
        assert body['batch_yield_qty'] == '6.0000'
        assert body['reference_price'] == '25.00'

    def test_delete_recipe_returns_204(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Temp')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        created = client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'name': 'To Delete',
            },
        )
        recipe_id = created.json()['id']

        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe_id}',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 204

        # Verify gone.
        get_resp = client.get(
            f'/api/v1/maker/recipes/{recipe_id}',
            headers=mk_auth_headers,
        )
        assert get_resp.status_code == 404

    def test_delete_recipe_referenced_by_order_returns_409(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: Any,  # StorageLocation fixture from conftest
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Referenced')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        created = client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'name': 'Referenced Recipe',
            },
        )
        recipe_id = created.json()['id']

        order = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert order.status_code == 201, order.text

        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe_id}',
            headers=mk_auth_headers,
        )
        # Referenced by a production order — conflict, not a raw 500.
        assert resp.status_code == 409, resp.text

    def test_create_duplicate_name_same_template_returns_409(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Widget')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        payload = {
            'output_template_id': str(template.id),
            'name': 'Same Name',
        }
        first = client.post(
            '/api/v1/maker/recipes', headers=mk_auth_headers, json=payload
        )
        assert first.status_code == 201

        second = client.post(
            '/api/v1/maker/recipes', headers=mk_auth_headers, json=payload
        )
        assert second.status_code == 409

    def test_other_org_cannot_see_recipe(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Secret')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        created = client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'name': 'Secret Recipe',
            },
        )
        recipe_id = created.json()['id']

        # Create second org user.
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        other_org = h.create_org(
            'Other', ['core', 'items', 'locations', 'categories', 'maker']
        )
        other_user = h.create_user(other_org, email='other@example.com')
        other_headers = h.get_auth_headers(other_user)

        resp = client.get(
            f'/api/v1/maker/recipes/{recipe_id}',
            headers=other_headers,
        )
        assert resp.status_code == 404


class TestRecipeCatalog:
    """GET /maker/recipes — catalog cards."""

    def test_empty_catalog(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get('/api/v1/maker/recipes', headers=mk_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body['items'] == []
        assert body['total'] == 0

    def test_catalog_lists_recipes(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        for name in ('Cherry Jam', 'Apple Butter'):
            template = ProductTemplate(organization_id=mk_org.id, name=name)
            db_session.add(template)
            db_session.commit()
            db_session.refresh(template)
            create_resp = client.post(
                '/api/v1/maker/recipes',
                headers=mk_auth_headers,
                json={
                    'output_template_id': str(template.id),
                    'name': name,
                },
            )
            assert create_resp.status_code == 201, create_resp.text

        resp = client.get('/api/v1/maker/recipes', headers=mk_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body['total'] == 2
        names = {item['name'] for item in body['items']}
        assert names == {'Cherry Jam', 'Apple Butter'}

    def test_catalog_filters_by_output_template(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """A product with several formulas is reachable from the product alone."""
        templates = {}
        for name in ('Rye Loaf', 'Wheat Loaf'):
            template = ProductTemplate(organization_id=mk_org.id, name=name)
            db_session.add(template)
            db_session.commit()
            db_session.refresh(template)
            templates[name] = template

        # Two formulas on the rye, one on the wheat.
        for template_name, recipe_name in (
            ('Rye Loaf', 'Rye — overnight'),
            ('Rye Loaf', 'Rye — same day'),
            ('Wheat Loaf', 'Wheat — standard'),
        ):
            resp = client.post(
                '/api/v1/maker/recipes',
                headers=mk_auth_headers,
                json={
                    'output_template_id': str(templates[template_name].id),
                    'name': recipe_name,
                },
            )
            assert resp.status_code == 201, resp.text

        resp = client.get(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            params={'output_template_id': str(templates['Rye Loaf'].id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['total'] == 2
        assert {item['name'] for item in body['items']} == {
            'Rye — overnight',
            'Rye — same day',
        }

    def test_catalog_filter_by_unknown_template_is_empty(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            params={'output_template_id': str(uuid.uuid4())},
        )
        assert resp.status_code == 200
        assert resp.json()['total'] == 0

    def test_catalog_unit_cost_null_without_history(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='No History')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)
        client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'name': 'No History Recipe',
            },
        )

        resp = client.get('/api/v1/maker/recipes', headers=mk_auth_headers)
        body = resp.json()
        assert body['total'] == 1
        assert body['items'][0]['unit_cost'] is None
        assert body['items'][0]['last_produced_at'] is None
        assert body['items'][0]['ingredient_count'] == 0


class TestMakerSettings:
    """GET/PATCH /maker/settings."""

    def test_get_settings_creates_defaults(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get('/api/v1/maker/settings', headers=mk_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # A new organization reads the result as a margin: a small workshop
        # sells what it makes, and the shop-price comparison is the choice
        # it opts into.
        assert body['reference_direction'] == 'MARGIN'

    def test_patch_settings_round_trip(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        # Default
        resp = client.get('/api/v1/maker/settings', headers=mk_auth_headers)
        assert resp.json()['reference_direction'] == 'MARGIN'

        # Update to SAVINGS
        resp = client.patch(
            '/api/v1/maker/settings',
            headers=mk_auth_headers,
            json={'reference_direction': 'SAVINGS'},
        )
        assert resp.status_code == 200
        assert resp.json()['reference_direction'] == 'SAVINGS'

        # Verify persisted
        resp = client.get('/api/v1/maker/settings', headers=mk_auth_headers)
        assert resp.json()['reference_direction'] == 'SAVINGS'

    def test_a_change_reaches_the_log_and_a_resave_does_not(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        db_session: Session,
    ) -> None:
        """Blocking production on a shortage is a rule, and who set it is asked."""
        for _ in range(2):
            resp = client.patch(
                '/api/v1/maker/settings',
                headers=mk_auth_headers,
                json={'create_on_shortage_strategy': 'BLOCK'},
            )
            assert resp.status_code == 200, resp.text

        db_session.expire_all()
        entries = [
            row
            for row in db_session.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == mk_org.id,
                    AuditLog.target_type == 'module',
                )
            ).all()
            if (row.snapshot or {}).get('name') == 'maker'
        ]
        assert len(entries) == 1
        assert entries[0].user_id == mk_user.id
        assert entries[0].snapshot is not None
        assert entries[0].snapshot['after'] == {'create_on_shortage_strategy': 'BLOCK'}

    def test_patch_invalid_direction_returns_422(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        resp = client.patch(
            '/api/v1/maker/settings',
            headers=mk_auth_headers,
            json={'reference_direction': 'INVALID'},
        )
        assert resp.status_code == 422

    def test_the_contract_names_the_finite_setting_values(self) -> None:
        """The generated types must carry the members, so no screen casts a string."""
        from app.main import app

        schemas = app.openapi()['components']['schemas']
        expected = {
            'reference_direction': ['SAVINGS', 'MARGIN'],
            'availability_check_scope': ['GLOBAL', 'PER_LOCATION'],
            'create_on_shortage_strategy': ['ALLOW', 'WARN', 'BLOCK'],
        }
        for name, members in expected.items():
            read = schemas['MakerSettingsRead']['properties'][name]
            assert read['enum'] == members, name
            update = next(
                part
                for part in schemas['MakerSettingsUpdate']['properties'][name]['anyOf']
                if part.get('type') != 'null'
            )
            assert update['enum'] == members, name


class TestProductionOrderRecipeResolution:
    """POST /production/orders resolves recipe."""

    def test_create_order_without_recipe_id_looks_up_default(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: Any,  # StorageLocation fixture from conftest
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Product')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        # Create a recipe (auto-default).
        client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'name': 'Recipe',
            },
        )

        # Create order without recipe_id — should auto-resolve.
        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'planned_qty': '5',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body['recipe_id'] is not None

    def test_create_order_without_recipe_returns_400(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: Any,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='No Recipe Product')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        # No recipe created — should fail.
        resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(template.id),
                'planned_qty': '5',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert resp.status_code == 400
        detail = resp.json()['detail']
        detail_str = detail if isinstance(detail, str) else str(detail)
        assert 'bom' in detail_str.lower()


class TestBomAdapterStillWorks:
    """The old /bom/* adapter auto-resolves recipe_id from parent_template_id."""

    def test_post_bom_creates_line_with_auto_recipe(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = ProductTemplate(organization_id=mk_org.id, name='Adapter Parent')
        child = ProductTemplate(organization_id=mk_org.id, name='Adapter Child')
        db_session.add_all([parent, child])
        db_session.commit()
        db_session.refresh(parent)
        db_session.refresh(child)

        resp = post_bom_line(
            client,
            mk_auth_headers,
            db_session,
            mk_org.id,
            {
                'parent_template_id': str(parent.id),
                'child_template_id': str(child.id),
                'qty_per_batch': '1.5',
                'unit': 'kg',
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body['qty_per_batch'] == '1.5000'
