"""A correction posted by a count says which count posted it.

Finalizing a stock take writes the difference back through the per-item
bridge, and the bridge stamped every movement it produced with the id of the
item that changed. For a correction that is the one thing already known: the
movement sits on the product's own history. What it could not say is on
whose instruction the stock moved — so a correction posted by Monday's count
of the cold store and a quantity somebody typed into the product form read
the same in the ledger, and the only trace of the count lived in the item
history and the organization log, neither of which the movement register
reads.

The reference now names the stock take. Every other path keeps pointing at
the item, because for them that is still the honest answer.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus
from tests.integration._shelf import post_on_shelf


@pytest.fixture
def ref_org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Correction Reference Org',
        ['core', 'items', 'locations', 'categories', 'stock_takes'],
    )


@pytest.fixture
def ref_user(db_session: Session, ref_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        ref_org, email='reference-counter@example.com'
    )


@pytest.fixture
def ref_headers(db_session: Session, ref_user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(ref_user)


@pytest.fixture
def ref_location(
    db_session: Session, ref_org: Organization, ref_user: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Warehouse', 'WAREHOUSE', organization_id=ref_org.id
    )
    return h.create_storage_location(
        ref_org, storage_type, ref_user, name='Referenced Warehouse'
    )


@pytest.fixture
def ref_template(db_session: Session, ref_org: Organization) -> ProductTemplate:
    return ModuleTestHelper(db_session).create_template(ref_org, name='Counted Goods')


@pytest.fixture
def ref_item(
    client: TestClient,
    ref_headers: dict[str, str],
    db_session: Session,
    ref_template: ProductTemplate,
    ref_location: StorageLocation,
) -> Item:
    record = post_on_shelf(client, ref_headers, ref_template, ref_location.id, 10)
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


def _adjustment_moves(db_session: Session, template_id: UUID) -> list[StockMove]:
    """What left the shelf since the record put the goods on it.

    The record's arrival is on the books too, and it is not a correction:
    both corrections below take stock off the shelf.
    """
    return list(
        db_session.execute(
            select(StockMove).where(
                StockMove.product_template_id == template_id,
                StockMove.from_location_id.is_not(None),
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.integration
class TestACorrectionNamesItsCount:
    def test_the_movement_points_at_the_stock_take(
        self,
        client: TestClient,
        ref_headers: dict[str, str],
        db_session: Session,
        ref_org: Organization,
        ref_user: User,
        ref_location: StorageLocation,
        ref_template: ProductTemplate,
        ref_item: Item,
    ) -> None:
        stock_take = StockTake(
            user_id=ref_user.id,
            organization_id=ref_org.id,
            storage_location_id=ref_location.id,
            name='Monday cold store',
            status=StockTakeStatus.IN_PROGRESS,
        )
        db_session.add(stock_take)
        db_session.flush()
        db_session.add(
            StockTakeItem(
                stock_take_id=stock_take.id,
                item_id=ref_item.id,
                item_name=ref_item.name,
                system_quantity=Decimal('10'),
                counted_quantity=Decimal('8'),
            )
        )
        db_session.commit()
        take_id = stock_take.id

        resp = client.post(
            f'/api/v1/stock-takes/{take_id}/complete',
            headers=ref_headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        moves = _adjustment_moves(db_session, ref_template.id)
        assert len(moves) == 1
        assert moves[0].reference_type == 'adjustment'
        assert moves[0].reference_id == take_id
        assert moves[0].reference_id != ref_item.id

    def test_a_quantity_typed_in_by_hand_still_points_at_the_item(
        self,
        client: TestClient,
        ref_headers: dict[str, str],
        db_session: Session,
        ref_template: ProductTemplate,
        ref_item: Item,
    ) -> None:
        # The control. Only the count knows a count happened; every other
        # path has nothing to name but the record it changed, and must keep
        # saying so.
        resp = client.patch(
            f'/api/v1/items/{ref_item.id}/quantity',
            headers=ref_headers,
            json={'quantity': 7},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        moves = _adjustment_moves(db_session, ref_template.id)
        assert len(moves) == 1
        assert moves[0].reference_type == 'item'
        assert moves[0].reference_id == ref_item.id
