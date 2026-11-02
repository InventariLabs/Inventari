"""
Tests for a record's posting across module sets.

The posting (``_post_the_change_async``, the bridge to the quant table while
there was one) used to be conditional: active only for orgs with a
stock-consuming module enabled (documents, purchase_orders, stock_takes),
skipped for home-only orgs, whose Item.quantity was their sole stock truth.
It is now active for every org — a home org keeps
the same register, and only the screens that show it stay behind the module
list. The register is the records themselves, their
movements and their cost layers: a record change writes its movement, and
the records' view shows the shelf.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation


def _register(
    db_session: Session, template_id: UUID, location_id: UUID
) -> tuple[list[Decimal], list[Decimal]]:
    """What the shelf holds by the records' view, and the movements into it."""
    shelf = [
        row.quantity
        for row in db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == template_id,
                ShelfRow.storage_location_id == location_id,
            )
        )
    ]
    moves = [
        move.quantity
        for move in db_session.scalars(
            select(StockMove).where(
                StockMove.product_template_id == template_id,
                StockMove.to_location_id == location_id,
            )
        )
    ]
    return shelf, moves


@pytest.mark.integration
class TestConditionalBridge:
    """Bridge active for WMS orgs and home-only orgs alike."""

    def test_home_only_org_keeps_its_register_too(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
    ) -> None:
        """Org without WMS modules: the create writes its movement all the same."""
        # Create a home-only org (no documents, no purchase_orders, no stock_takes)
        org = h.create_org(
            'Home Only Org',
            ['core', 'items', 'locations', 'categories'],
        )
        user = h.create_user(org, email='home@example.com')
        headers = h.get_auth_headers(user)
        loc = h.create_storage_location(
            org, h.create_storage_type('Home', 'PANTRY'), user, name='Pantry'
        )
        template = h.create_template(org, name='Home Milk')

        # Create an item with template + location (triggers _post_the_change_async)
        resp = client.post(
            '/api/v1/items',
            headers=headers,
            json={
                'name': 'Home Milk',
                'location_id': str(loc.id),
                'quantity': 5,
                'template_id': str(template.id),
            },
        )
        assert resp.status_code == 201, resp.text

        # The movement exists — the bridge no longer asks about modules
        shelf, moves = _register(db_session, UUID(resp.json()['template_id']), loc.id)
        assert shelf == [5], shelf
        assert moves == [5], 'no movement for a home-only org — the bridge skipped it'

    def test_wms_org_writes_its_movement(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Org with documents enabled: bridge active, the movement written on create.

        The home-only test proves the bridge runs for orgs without WMS
        modules too. This one proves it for a WMS org: the record lands, the
        view shows the shelf, and the ledger holds the one movement into it.
        """
        # doc_org has 'warehouse' in enabled_modules (from conftest)
        resp = client.post(
            '/api/v1/items',
            headers=doc_auth_headers,
            json={
                'name': 'WMS Item',
                'location_id': str(doc_target_location.id),
                'quantity': 5,
                'template_id': str(doc_template.id),
            },
        )
        assert resp.status_code == 201, resp.text
        # The record finds its card by name, the way a typed one does; the
        # response names the card it landed on.
        shelf, moves = _register(
            db_session, UUID(resp.json()['template_id']), doc_target_location.id
        )
        assert shelf == [5], shelf
        assert moves == [5], 'no movement for a WMS org — the bridge skipped it'
