"""Integration tests for PATCH, duplicate, and stock-moves endpoints.

Covers bugs #4 (no PATCH), #5 (no duplicate), #11 (no stock-move audit
trail in the API).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, *, name: str = 'T') -> ProductTemplate:
    t = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
        removal_strategy='FIFO',
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _ensure_recipe(db: Session, org: Organization, template_id: UUID) -> MakerRecipe:
    """Get or create a default recipe for template_id."""
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
        batch_yield_qty=Decimal('1'),
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
    qty: str = '10.000',
) -> dict[str, Any]:
    """Put *qty* of *template* on the shelf as one record bought at *unit_cost*.

    The record's receipt writes the quant, the movement and the cost layer,
    the way a person's entry does.
    """
    return post_on_shelf(
        client, headers, template, location.id, qty, purchase_price=unit_cost
    )


class TestProductionUpdate:
    """PATCH /orders/{id} — edit DRAFT orders only."""

    def test_patch_draft_updates_qty_and_notes(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        output = _template(db_session, mk_org, name='Patchable')
        _ensure_recipe(db_session, mk_org, template_id=output.id)
        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1.000',
                'output_location_id': str(mk_output_loc.id),
                'notes': 'original note',
            },
        )
        assert create_resp.status_code == 201
        order_id = create_resp.json()['id']

        patch_resp = client.patch(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
            json={'planned_qty': '5.000', 'notes': 'updated note'},
        )
        assert patch_resp.status_code == 200, patch_resp.text
        body = patch_resp.json()
        assert Decimal(body['planned_qty']) == Decimal('5.000')
        assert body['notes'] == 'updated note'
        assert body['status'] == 'DRAFT'

    def test_patch_completed_rejected(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Ing')
        output = _template(db_session, mk_org, name='Out')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='0.5',
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, unit_cost='1.00')

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '2.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']
        client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )

        patch_resp = client.patch(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
            json={'planned_qty': '9.000'},
        )
        assert patch_resp.status_code == 400

    def test_patch_not_found_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        patch_resp = client.patch(
            f'/api/v1/maker/production/orders/{uuid.uuid4()}',
            headers=mk_auth_headers,
            json={'planned_qty': '5.000'},
        )
        assert patch_resp.status_code == 404


class TestProductionDuplicate:
    """POST /orders/{id}/duplicate — create a fresh DRAFT from an existing order."""

    def test_duplicate_creates_draft_copy(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        output = _template(db_session, mk_org, name='Duplicable')
        _ensure_recipe(db_session, mk_org, template_id=output.id)
        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '3.000',
                'output_location_id': str(mk_output_loc.id),
                'notes': 'batch A',
            },
        )
        assert create_resp.status_code == 201
        source_id = create_resp.json()['id']

        dup_resp = client.post(
            f'/api/v1/maker/production/orders/{source_id}/duplicate',
            headers=mk_auth_headers,
        )
        assert dup_resp.status_code == 201, dup_resp.text
        dup_body = dup_resp.json()

        # New order, different id, DRAFT status.
        assert dup_body['id'] != source_id
        assert dup_body['status'] == 'DRAFT'
        # Planning fields copied.
        assert dup_body['output_template_id'] == str(output.id)
        assert Decimal(dup_body['planned_qty']) == Decimal('3.000')
        # Notes prefixed with [duplicate].
        assert dup_body['notes'] == '[duplicate] batch A'
        # No produced item on a fresh draft.
        assert dup_body['produced_item_id'] is None
        assert dup_body['lines'] == []

    def test_duplicate_preserves_explicit_recipe_id(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """A duplicate must keep the source order's recipe (even non-default).

        Regression: the copy used to drop ``recipe_id``, so completing the
        duplicate exploded via the DEFAULT recipe instead of the source
        order's recipe.
        """
        output = _template(db_session, mk_org, name='MultiRecipe')
        default_recipe = _ensure_recipe(db_session, mk_org, template_id=output.id)
        variant = MakerRecipe(
            organization_id=mk_org.id,
            output_template_id=output.id,
            name='Variant',
            batch_yield_qty=Decimal('1'),
            is_default=False,
        )
        db_session.add(variant)
        db_session.commit()
        db_session.refresh(variant)

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'recipe_id': str(variant.id),
                'planned_qty': '3.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create_resp.status_code == 201
        source_id = create_resp.json()['id']

        dup_resp = client.post(
            f'/api/v1/maker/production/orders/{source_id}/duplicate',
            headers=mk_auth_headers,
        )
        assert dup_resp.status_code == 201, dup_resp.text
        dup_body = dup_resp.json()

        # The non-default recipe must survive the copy.
        assert dup_body['recipe_id'] == str(variant.id)
        assert dup_body['recipe_id'] != str(default_recipe.id)

    def test_duplicate_not_found_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        dup_resp = client.post(
            f'/api/v1/maker/production/orders/{uuid.uuid4()}/duplicate',
            headers=mk_auth_headers,
        )
        assert dup_resp.status_code == 404


class TestProductionStockMoves:
    """GET /orders/{id}/stock-moves — traceability audit trail."""

    def test_stock_moves_endpoint_returns_consumption_and_output(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Sugar')
        output = _template(db_session, mk_org, name='Candy')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='1.0',
        )
        _stock(client, mk_auth_headers, ingredient, mk_input_loc, unit_cost='2.00')

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '2.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']

        client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )

        moves_resp = client.get(
            f'/api/v1/maker/production/orders/{order_id}/stock-moves',
            headers=mk_auth_headers,
        )
        assert moves_resp.status_code == 200, moves_resp.text
        moves = moves_resp.json()['items']
        assert len(moves) >= 2

        directions = {(m['from_location_id'], m['to_location_id']) for m in moves}
        # Input move: from input location → None (consumption).
        assert (str(mk_input_loc.id), None) in directions
        # Output move: None → output location (receipt).
        assert (None, str(mk_output_loc.id)) in directions
