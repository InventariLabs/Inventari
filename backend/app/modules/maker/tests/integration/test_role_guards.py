"""Role guards: the manager/floor split the purpose card promises.

``docs/purpose/maker.md`` gives the decision about what production consumes
to the manager — "a BOM decides what gets consumed" — so writing a formula,
changing module settings and cancelling a run sit behind ``maker:manage``,
while running orders (create, complete, duplicate) stays with ``maker:write``,
which the ordinary member holds. The same split the warehouse module draws
between executing a document and cancelling one.

The gap that prompted these tests: a plain member could create a
BOM, rewrite a foreign line from 0.2 kg to 99 kg, delete it and flip the
organization's shortage strategy — all without leaving a trace in the audit
log.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, *, name: str) -> ProductTemplate:
    t = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _recipe_with_stock(
    db: Session,
    client: TestClient,
    org: Organization,
    headers: dict[str, str],
    input_loc: StorageLocation,
    output_loc: StorageLocation,
    *,
    ingredient_name: str = 'Soy wax',
    output_name: str = 'Candle',
    ingredient_qty: str = '10.000',
) -> str:
    """Create a formula through the API and stock it, the way an
    organization would; returns the production order id."""
    ingredient = _template(db, org, name=ingredient_name)
    output = _template(db, org, name=output_name)

    create_resp = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'name': 'Candle formula',
            'batch_yield_qty': '1',
            'is_default': True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    recipe_id = create_resp.json()['id']

    line_resp = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(ingredient.id),
            'qty_per_batch': '0.2',
            'unit': 'kg',
        },
    )
    assert line_resp.status_code == 201, line_resp.text

    post_on_shelf(client, headers, ingredient, input_loc.id, ingredient_qty)

    order_resp = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'planned_qty': '1.000',
            'output_location_id': str(output_loc.id),
        },
    )
    assert order_resp.status_code == 201, order_resp.text
    return str(order_resp.json()['id'])


class TestMakerRoleGuards:
    """Writing the formula is the manager's; running orders is everybody's."""

    def test_user_cannot_create_recipe(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        output = _template(db_session, mk_org, name='Candle')
        user = h.create_user(mk_org, email='maker-user@example.com', role='user')
        resp = client.post(
            '/api/v1/maker/recipes',
            headers=h.get_auth_headers(user),
            json={
                'output_template_id': str(output.id),
                'name': 'Member formula',
                'batch_yield_qty': '1',
            },
        )
        assert resp.status_code == 403

    def test_user_cannot_edit_a_foreign_bom_line(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Soy wax')
        output = _template(db_session, mk_org, name='Candle')
        create_resp = client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'name': 'Candle formula',
                'batch_yield_qty': '1',
            },
        )
        assert create_resp.status_code == 201
        recipe_id = create_resp.json()['id']
        line_resp = client.post(
            f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
            headers=mk_auth_headers,
            json={
                'child_template_id': str(ingredient.id),
                'qty_per_batch': '0.2',
                'unit': 'kg',
            },
        )
        assert line_resp.status_code == 201
        line_id = line_resp.json()['id']

        user = h.create_user(mk_org, email='line-editor@example.com', role='user')
        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe_id}/bom-lines/{line_id}',
            headers=h.get_auth_headers(user),
            json={'qty_per_batch': '99.0'},
        )
        assert resp.status_code == 403

    def test_user_cannot_delete_recipe(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        output = _template(db_session, mk_org, name='Candle')
        create_resp = client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'name': 'Doomed formula',
                'batch_yield_qty': '1',
            },
        )
        assert create_resp.status_code == 201
        recipe_id = create_resp.json()['id']

        user = h.create_user(mk_org, email='deleter@example.com', role='user')
        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe_id}',
            headers=h.get_auth_headers(user),
        )
        assert resp.status_code == 403

    def test_user_cannot_change_module_settings(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        user = h.create_user(mk_org, email='settings-flipper@example.com', role='user')
        resp = client.patch(
            '/api/v1/maker/settings',
            headers=h.get_auth_headers(user),
            json={'create_on_shortage_strategy': 'BLOCK'},
        )
        assert resp.status_code == 403

    def test_user_cannot_cancel_a_run(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        order_id = _recipe_with_stock(
            db_session,
            client,
            mk_org,
            mk_auth_headers,
            mk_input_loc,
            mk_output_loc,
        )
        user = h.create_user(mk_org, email='canceller@example.com', role='user')
        resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/cancel',
            headers=h.get_auth_headers(user),
            json={},
        )
        assert resp.status_code == 403

    def test_user_runs_and_completes_production(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Running orders is the floor's job: create, complete — 200."""
        user = h.create_user(mk_org, email='floor@example.com', role='user')
        headers = h.get_auth_headers(user)

        order_id = _recipe_with_stock(
            db_session,
            client,
            mk_org,
            mk_auth_headers,
            mk_input_loc,
            mk_output_loc,
        )
        # The member completes the run the manager stocked.
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text
        assert complete_resp.json()['status'] == 'COMPLETED'

    def test_completing_a_run_asks_for_items_write(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Completing opens a core Item for the output — items work.

        A caller carrying maker:write but no items:write (the shape a custom
        role can produce) used to open that record through this door.
        """
        order_id = _recipe_with_stock(
            db_session,
            client,
            mk_org,
            mk_auth_headers,
            mk_input_loc,
            mk_output_loc,
        )
        user = h.create_user(mk_org, email='maker-only@example.com', role='user')
        h.grant_permissions(user, ['maker:read', 'maker:write'])

        resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=h.get_auth_headers(user),
        )
        assert resp.status_code == 403, resp.text

    def test_writing_a_margin_asks_for_items_write(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """The margin lands in the product template's metadata."""
        output = _template(db_session, mk_org, name='Priced candle')
        user = h.create_user(mk_org, email='pricer@example.com', role='user')
        h.grant_permissions(user, ['maker:read', 'maker:write'])

        resp = client.put(
            f'/api/v1/maker/pricing/margin/{output.id}',
            headers=h.get_auth_headers(user),
            json={'target_margin_pct': '40'},
        )
        assert resp.status_code == 403, resp.text

    def test_manager_can_cancel_a_run(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        order_id = _recipe_with_stock(
            db_session,
            client,
            mk_org,
            mk_auth_headers,
            mk_input_loc,
            mk_output_loc,
        )
        manager = h.create_user(
            mk_org, email='maker-manager@example.com', role='manager'
        )
        resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/cancel',
            headers=h.get_auth_headers(manager),
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()['status'] == 'CANCELLED'

    def test_manager_can_change_module_settings(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
    ) -> None:
        manager = h.create_user(
            mk_org, email='settings-manager@example.com', role='manager'
        )
        resp = client.patch(
            '/api/v1/maker/settings',
            headers=h.get_auth_headers(manager),
            json={'create_on_shortage_strategy': 'BLOCK'},
        )
        assert resp.status_code == 200
        assert resp.json()['create_on_shortage_strategy'] == 'BLOCK'


class TestMakerManageIsAPermission:
    """The guard checks maker:manage, not the role name — the same contract
    the warehouse module tests. A custom role holding the key acts like a
    manager; one holding only read+write is refused like a member."""

    @staticmethod
    def _custom_role_user(
        h: Any,
        org: Organization,
        email: str,
        permissions: list[str],
    ) -> Any:
        from app.models.role import Role, UserRole

        user = h.create_user(org, email=email, role='user')
        role = Role(
            organization_id=org.id,
            name=f'Custom {email}',
            permissions=permissions,
            is_system=False,
        )
        h.db.add(role)
        h.db.flush()
        h.db.add(UserRole(user_id=user.id, role_id=role.id))
        h.db.commit()
        return user

    def test_custom_role_with_manage_cancels(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        order_id = _recipe_with_stock(
            db_session,
            client,
            mk_org,
            mk_auth_headers,
            mk_input_loc,
            mk_output_loc,
        )
        # read+write pass the module router gate; manage is what the cancel
        # endpoint itself demands.
        user = self._custom_role_user(
            h,
            mk_org,
            'maker-cancel-custom@example.com',
            ['maker:read', 'maker:write', 'maker:manage'],
        )
        resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/cancel',
            headers=h.get_auth_headers(user),
            json={},
        )
        assert resp.status_code == 200

    def test_custom_role_without_manage_cannot_cancel(
        self,
        client: TestClient,
        h: Any,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        order_id = _recipe_with_stock(
            db_session,
            client,
            mk_org,
            mk_auth_headers,
            mk_input_loc,
            mk_output_loc,
        )
        # read+write pass the module router gate, so the 403 must come from
        # the endpoint's own maker:manage guard.
        user = self._custom_role_user(
            h,
            mk_org,
            'maker-cancel-noperm@example.com',
            ['maker:read', 'maker:write'],
        )
        resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/cancel',
            headers=h.get_auth_headers(user),
            json={},
        )
        assert resp.status_code == 403
