"""A difference beyond the stock take's tolerance waits for somebody.

The tolerance was a label. It decided whether a row was called a
discrepancy and nothing else: finalize posted every counted row the same
way, and the only thing that ever held a posting back was the hard cap at
five times the system quantity — a guard against a typed "200" for "20",
not against a real difference.

Every warehouse system treats the number as a gate instead. SAP gives each
user group a limit and refuses the posting to anyone under it; Dynamics
blocks the line; the WMS floor sends it back. Inside the tolerance is
measurement noise and posts itself. Outside it, two things have to be true
before the stock moves: somebody has said what happened, and somebody who
may accept that has accepted it.

Without a tolerance configured there is no "beyond" to speak of, and the
count posts as it always has.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.contracts import AuditTargetType
from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus
from tests.integration._shelf import post_on_shelf


@pytest.fixture
def tol_org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Tolerance Org', ['core', 'items', 'locations', 'categories', 'stock_takes']
    )


@pytest.fixture
def tol_manager(db_session: Session, tol_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        tol_org, email='tol-manager@example.com', role='manager'
    )


@pytest.fixture
def tol_counter(db_session: Session, tol_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        tol_org, email='tol-counter@example.com', role='user'
    )


@pytest.fixture
def manager_headers(db_session: Session, tol_manager: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(tol_manager)


@pytest.fixture
def counter_headers(db_session: Session, tol_counter: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(tol_counter)


@pytest.fixture
def tol_location(
    db_session: Session, tol_org: Organization, tol_manager: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Warehouse', 'WAREHOUSE', organization_id=tol_org.id
    )
    return h.create_storage_location(
        tol_org, storage_type, tol_manager, name='Tolerant shelf'
    )


@pytest.fixture
def tol_item(
    client: TestClient,
    manager_headers: dict[str, str],
    db_session: Session,
    tol_org: Organization,
    tol_location: StorageLocation,
) -> Item:
    template: ProductTemplate = ModuleTestHelper(db_session).create_template(
        tol_org, name='Bulk Goods'
    )
    db_session.commit()
    record = post_on_shelf(client, manager_headers, template, tol_location.id, 100)
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


def _count(
    db_session: Session,
    org: Organization,
    user: User,
    location: StorageLocation,
    item: Item,
    *,
    counted: Decimal,
    tolerance: Decimal | None,
    reason_code: str | None = None,
) -> StockTake:
    """A stock take already counted, ready to be finished."""
    stock_take = StockTake(
        user_id=user.id,
        organization_id=org.id,
        storage_location_id=location.id,
        name='Tolerance count',
        status=StockTakeStatus.IN_PROGRESS,
        tolerance_percent=tolerance,
    )
    db_session.add(stock_take)
    db_session.flush()
    over = tolerance is not None and abs(counted - Decimal('100')) > tolerance
    db_session.add(
        StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name,
            system_quantity=Decimal('100'),
            counted_quantity=counted,
            discrepancy_reason_code=reason_code,
            is_discrepancy=1 if (over or tolerance is None) else 0,
        )
    )
    db_session.commit()
    db_session.refresh(stock_take)
    return stock_take


def _quantity(db_session: Session, item_id: UUID) -> Decimal:
    db_session.expire_all()
    return db_session.execute(
        select(Item.quantity).where(Item.id == item_id)
    ).scalar_one()


@pytest.mark.integration
class TestADifferenceBeyondTheTolerance:
    def test_it_is_refused_until_it_says_why(
        self,
        client: TestClient,
        manager_headers: dict[str, str],
        db_session: Session,
        tol_org: Organization,
        tol_manager: User,
        tol_location: StorageLocation,
        tol_item: Item,
    ) -> None:
        take = _count(
            db_session,
            tol_org,
            tol_manager,
            tol_location,
            tol_item,
            counted=Decimal('60'),
            tolerance=Decimal('5'),
        )
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=manager_headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert 'unexplained_items' in str(resp.json())
        # Nothing reached the stock: a refusal that half-posts is worse than
        # no refusal at all.
        assert _quantity(db_session, tol_item.id) == Decimal('100')

    def test_it_is_refused_until_somebody_accepts_it(
        self,
        client: TestClient,
        manager_headers: dict[str, str],
        db_session: Session,
        tol_org: Organization,
        tol_manager: User,
        tol_location: StorageLocation,
        tol_item: Item,
    ) -> None:
        take = _count(
            db_session,
            tol_org,
            tol_manager,
            tol_location,
            tol_item,
            counted=Decimal('60'),
            tolerance=Decimal('5'),
            reason_code='LOSS',
        )
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=manager_headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert 'over_tolerance_items' in str(resp.json())
        assert _quantity(db_session, tol_item.id) == Decimal('100')

    def test_a_counter_may_not_accept_it(
        self,
        client: TestClient,
        counter_headers: dict[str, str],
        db_session: Session,
        tol_org: Organization,
        tol_counter: User,
        tol_location: StorageLocation,
        tol_item: Item,
    ) -> None:
        take = _count(
            db_session,
            tol_org,
            tol_counter,
            tol_location,
            tol_item,
            counted=Decimal('60'),
            tolerance=Decimal('5'),
            reason_code='LOSS',
        )
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=counter_headers,
            json={'apply_adjustments': True, 'force_over_tolerance': True},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text
        assert _quantity(db_session, tol_item.id) == Decimal('100')

    def test_a_manager_accepts_it_and_the_log_says_so(
        self,
        client: TestClient,
        manager_headers: dict[str, str],
        db_session: Session,
        tol_org: Organization,
        tol_manager: User,
        tol_location: StorageLocation,
        tol_item: Item,
    ) -> None:
        take = _count(
            db_session,
            tol_org,
            tol_manager,
            tol_location,
            tol_item,
            counted=Decimal('60'),
            tolerance=Decimal('5'),
            reason_code='LOSS',
        )
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=manager_headers,
            json={'apply_adjustments': True, 'force_over_tolerance': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert _quantity(db_session, tol_item.id) == Decimal('60')

        entry = db_session.execute(
            select(AuditLog).where(
                AuditLog.target_type == AuditTargetType.STOCK_TAKE,
                AuditLog.target_id == take.id,
            )
        ).scalar_one()
        assert entry.snapshot is not None
        assert entry.snapshot['over_tolerance_accepted'] == 1
        assert entry.user_id == tol_manager.id

    def test_a_difference_inside_the_tolerance_posts_itself(
        self,
        client: TestClient,
        manager_headers: dict[str, str],
        db_session: Session,
        tol_org: Organization,
        tol_manager: User,
        tol_location: StorageLocation,
        tol_item: Item,
    ) -> None:
        # The control. 97 against 100 under a 5% tolerance is measurement
        # noise: nobody is asked anything and the stock follows the count.
        take = _count(
            db_session,
            tol_org,
            tol_manager,
            tol_location,
            tol_item,
            counted=Decimal('97'),
            tolerance=Decimal('5'),
        )
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=manager_headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert _quantity(db_session, tol_item.id) == Decimal('97')

    def test_a_count_without_a_tolerance_behaves_as_before(
        self,
        client: TestClient,
        manager_headers: dict[str, str],
        db_session: Session,
        tol_org: Organization,
        tol_manager: User,
        tol_location: StorageLocation,
        tol_item: Item,
    ) -> None:
        # The second control. A tolerance nobody set is not a tolerance of
        # zero — the rule cannot be stricter than the number the organization
        # declined to give.
        take = _count(
            db_session,
            tol_org,
            tol_manager,
            tol_location,
            tol_item,
            counted=Decimal('60'),
            tolerance=None,
        )
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=manager_headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert _quantity(db_session, tol_item.id) == Decimal('60')
