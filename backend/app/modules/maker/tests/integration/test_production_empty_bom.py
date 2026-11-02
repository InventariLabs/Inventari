"""Completing a run whose recipe lists no ingredients must be refused.

A DRAFT for an ingredient-less recipe used to complete happily: nothing was
consumed, yet the output item was created and stood on the shelf — goods out
of thin air. The rule is now explicit: no bill of materials, no production.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.i18n.service import get_error_message
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe, ProductionOrder
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, *, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _recipe(
    db: Session,
    org: Organization,
    template_id: UUID,
    *,
    name: str = 'Empty Recipe',
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=template_id,
        name=name,
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


def _create_draft(
    client: TestClient,
    headers: dict[str, str],
    *,
    output: ProductTemplate,
    location: StorageLocation,
    qty: str = '7',
) -> str:
    resp = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'planned_qty': qty,
            'output_location_id': str(location.id),
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()['id'])


class TestCompleteWithoutBom:
    """``complete_production`` refuses an order that would consume nothing."""

    def test_complete_recipe_without_lines_returns_422(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='NoBomOutput')
        recipe = _recipe(db_session, mk_org, output.id, name='Ingredient-less')
        order_id = _create_draft(
            client, mk_auth_headers, output=output, location=mk_output_loc
        )

        resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 422
        detail = resp.json()['detail']
        assert detail['error'] == 'empty_bom'
        assert detail['recipe_id'] == str(recipe.id)
        assert detail['recipe_name'] == 'Ingredient-less'

    def test_the_refusal_is_the_shared_envelope_around_what_the_toast_reads(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='EnvelopeOutput')
        recipe = _recipe(db_session, mk_org, output.id, name='Envelope recipe')
        order_id = _create_draft(
            client, mk_auth_headers, output=output, location=mk_output_loc
        )

        resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 422
        assert resp.json()['detail'] == {
            'code': 'empty_bom',
            'message': get_error_message('production_no_recipe', 'en'),
            'error': 'empty_bom',
            'recipe_id': str(recipe.id),
            'recipe_name': 'Envelope recipe',
        }

    def test_complete_recipe_without_lines_produces_no_stock(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        output = _template(db_session, mk_org, name='NoBomNoStock')
        _recipe(db_session, mk_org, output.id)
        order_id = _create_draft(
            client, mk_auth_headers, output=output, location=mk_output_loc
        )

        client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )

        on_shelf = (
            db_session.query(ShelfRow)
            .filter(
                ShelfRow.organization_id == mk_org.id,
                ShelfRow.product_template_id == output.id,
            )
            .all()
        )
        assert on_shelf == []

        order = (
            db_session.query(ProductionOrder)
            .filter(ProductionOrder.id == UUID(order_id))
            .one()
        )
        assert order.status == 'DRAFT'
        assert order.produced_item_id is None

    def test_complete_legacy_order_without_default_recipe_returns_422(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_user: User,
        mk_output_loc: StorageLocation,
    ) -> None:
        """``recipe_id=None`` explodes the default recipe — which may not exist."""
        output = _template(db_session, mk_org, name='LegacyNoBom')
        order = ProductionOrder(
            organization_id=mk_org.id,
            output_template_id=output.id,
            recipe_id=None,
            planned_qty=Decimal('3'),
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

        assert resp.status_code == 422
        detail = resp.json()['detail']
        assert detail['error'] == 'empty_bom'
        assert detail['recipe_id'] is None

    def test_complete_with_one_line_still_succeeds(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        mk_input_loc: StorageLocation,
    ) -> None:
        """The guard must not touch a recipe that actually lists ingredients."""
        output = _template(db_session, mk_org, name='HasBomOutput')
        ingredient = _template(db_session, mk_org, name='HasBomIngredient')
        recipe = _recipe(db_session, mk_org, output.id, name='One-liner')
        db_session.add(
            BoMLine(
                organization_id=mk_org.id,
                recipe_id=recipe.id,
                parent_template_id=output.id,
                child_template_id=ingredient.id,
                qty_per_batch=Decimal('1'),
                unit='szt',
            )
        )
        db_session.commit()
        post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, 50)

        order_id = _create_draft(
            client, mk_auth_headers, output=output, location=mk_output_loc, qty='2'
        )
        resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 200
        assert resp.json()['status'] == 'COMPLETED'
