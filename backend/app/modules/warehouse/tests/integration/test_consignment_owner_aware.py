"""
Tests for consignment / owner-aware stock operations.

A record's owner_id links stock to a Partner (consignor), and the records'
view keeps each owner's stock in a group of its own. Owner-aware
operations ensure own stock (owner_id=NULL) and consignment stock
(owner_id=partner) are never accidentally mixed during consumption or picking.

Use cases: 3PL (third-party logistics), consignment stock, multi-owner
warehouse.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import sow as _sow


@pytest.mark.integration
class TestConsignmentOwnerAwareStock:
    """Owner-aware stock operations: own stock vs consignment stock."""

    def test_own_stock_consumed_by_default(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Consumption without owner_id only touches own stock (owner_id IS NULL)."""
        # Create own stock (owner_id=NULL) and partner stock

        # This test verifies the filter logic at the DB level
        _sow(
            db_session,
            async_engine_fixture,
            doc_target_location.organization_id,
            doc_template,
            doc_target_location.id,
            10,
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_target_location.organization_id,
            doc_template,
            doc_target_location.id,
            5,
            owner_id=doc_partner.id,
        )

        # Verify both groups exist
        groups = (
            db_session.execute(
                select(ShelfRow).where(
                    ShelfRow.product_template_id == doc_template.id,
                    ShelfRow.storage_location_id == doc_target_location.id,
                )
            )
            .scalars()
            .all()
        )
        assert len(groups) == 2

        # The default filter (owner_id=None → IS NULL) should only see own stock
        own_only = (
            db_session.execute(
                select(ShelfRow).where(
                    ShelfRow.product_template_id == doc_template.id,
                    ShelfRow.storage_location_id == doc_target_location.id,
                    ShelfRow.quantity > ShelfRow.reserved_quantity,
                    ShelfRow.owner_id.is_(None),
                )
            )
            .scalars()
            .all()
        )
        assert len(own_only) == 1
        assert own_only[0].quantity == 10

    def test_partner_stock_filterable(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Groups can be filtered by owner_id to find consignment stock."""
        _sow(
            db_session,
            async_engine_fixture,
            doc_target_location.organization_id,
            doc_template,
            doc_target_location.id,
            10,
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_target_location.organization_id,
            doc_template,
            doc_target_location.id,
            5,
            owner_id=doc_partner.id,
        )
        # Filter for partner stock
        partner_groups = (
            db_session.execute(
                select(ShelfRow).where(
                    ShelfRow.product_template_id == doc_template.id,
                    ShelfRow.storage_location_id == doc_target_location.id,
                    ShelfRow.owner_id == doc_partner.id,
                )
            )
            .scalars()
            .all()
        )
        assert len(partner_groups) == 1
        assert partner_groups[0].quantity == 5

    def test_consume_does_not_touch_partner_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Consuming via API must not reduce partner-owned stock."""
        # Own stock through the service; consignment stock in the partner's name.
        item = _sow(
            db_session,
            async_engine_fixture,
            doc_target_location.organization_id,
            doc_template,
            doc_target_location.id,
            10,
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_target_location.organization_id,
            doc_template,
            doc_target_location.id,
            5,
            owner_id=doc_partner.id,
        )

        # Consume 3 — should only touch own stock (owner_id IS NULL filter)
        resp = client.patch(
            f'/api/v1/items/{item.id}/consume',
            headers=doc_auth_headers,
            json={'quantity': 3},
        )
        assert resp.status_code == 200, resp.text

        # Reload the groups — own reduced, partner untouched
        db_session.expire_all()
        own_after = db_session.execute(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template.id,
                ShelfRow.storage_location_id == doc_target_location.id,
                ShelfRow.owner_id.is_(None),
            )
        ).scalar_one()
        partner_after = db_session.execute(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template.id,
                ShelfRow.storage_location_id == doc_target_location.id,
                ShelfRow.owner_id == doc_partner.id,
            )
        ).scalar_one()

        assert own_after.quantity == 7  # reduced by 3
        assert partner_after.quantity == 5  # untouched
