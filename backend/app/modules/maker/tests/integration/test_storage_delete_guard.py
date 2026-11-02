"""Deleting a storage location used by production orders is vetoed cleanly.

the RESTRICT FK on ``maker_production_orders.output_storage_location_id``
used to surface as a misleading "concurrent transaction created stock
movements" 409. The ``ProductionOrderStorageGuard`` interceptor now answers
with a domain message before any DELETE is attempted.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import ProductionOrder, ProductionOrderLine

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name='Test Output',
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _order(
    db: Session,
    org: Organization,
    template: ProductTemplate,
    location: StorageLocation,
) -> ProductionOrder:
    order = ProductionOrder(
        organization_id=org.id,
        output_template_id=template.id,
        planned_qty=Decimal('1'),
        output_storage_location_id=location.id,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


class TestStorageDeleteGuard:
    """Storage deletion is vetoed while production orders reference it."""

    def test_delete_location_used_as_order_output_returns_409(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_output_loc: StorageLocation,
    ) -> None:
        _order(db_session, mk_org, _template(db_session, mk_org), mk_output_loc)

        resp = client.delete(
            f'/api/v1/locations/{mk_output_loc.id}', headers=mk_auth_headers
        )

        assert resp.status_code == 409, resp.text
        detail = resp.json()['detail']
        assert detail['code'] == 'STORAGE_HAS_PRODUCTION_ORDERS'
        assert 'production order' in detail['message']
        assert detail['production_orders'] == 1
        assert db_session.get(StorageLocation, mk_output_loc.id) is not None

    def test_delete_location_used_as_line_source_returns_409(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
    ) -> None:
        template = _template(db_session, mk_org)
        order = _order(db_session, mk_org, template, mk_output_loc)
        line = ProductionOrderLine(
            production_order_id=order.id,
            child_template_id=template.id,
            consumed_qty=Decimal('1'),
            unit='pcs',
            source_storage_location_id=mk_input_loc.id,
        )
        db_session.add(line)
        db_session.commit()

        resp = client.delete(
            f'/api/v1/locations/{mk_input_loc.id}', headers=mk_auth_headers
        )

        assert resp.status_code == 409, resp.text
        detail = resp.json()['detail']
        assert detail['code'] == 'STORAGE_HAS_PRODUCTION_ORDERS'
        assert detail['production_order_lines'] == 1
        assert db_session.get(StorageLocation, mk_input_loc.id) is not None

    def test_delete_unreferenced_location_succeeds(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_output_loc: StorageLocation,
    ) -> None:
        location_id = mk_output_loc.id
        resp = client.delete(
            f'/api/v1/locations/{location_id}', headers=mk_auth_headers
        )

        assert resp.status_code == 204, resp.text
        # Column query — the row was deleted through the async request session,
        # so touching the expired ORM instance (or reloading it) would raise
        # ObjectDeletedError.
        assert (
            db_session.query(StorageLocation.id).filter_by(id=location_id).first()
            is None
        )
