"""What the demo seed hands an organization follows the modules it runs.

Two failures sat in the one function this pins. Volume could only be seeded
into an organization whose profile declares food categories, because the seed
asked for them unconditionally — under a warehouse profile the run stopped on
"no category for canned_goods, cheese, dairy, …" and the fixture for a
screen-by-screen pass could not be built at all. And under the food profile it
produced a long list of products with no document, no order and no partner
behind them, because those steps were simply not in the copy the fixture used.

So: the catalogue a product is filed under is seeded whatever the profile, and
the records that belong to a module are written only where that module runs.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from app.database import Base
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import ProductionOrder, ProductionOrderLine
from app.modules.purchase_orders.models import PurchaseOrder
from app.modules.warehouse.models import Document
from app.services.token_service import get_password_hash
from seed_demo_data import seed_organization

pytestmark = pytest.mark.integration


@pytest.fixture
def seed_org(db_session: Session) -> Generator[tuple[uuid.UUID, uuid.UUID]]:
    """A bare organization, and everything the seed leaves in it taken away.

    Torn down the way the wipe does it — children before parents, by walking
    the metadata backwards — because a seeded organization holds rows in a
    dozen tables and half of them refuse to go in any other order.
    """
    org = Organization(id=uuid.uuid4(), name='Seed Modules Org')
    user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=f'seed-modules+{uuid.uuid4().hex[:8]}@example.com',
        full_name='Seed',
        hashed_password=get_password_hash('seed-test-password'),
    )
    db_session.add(org)
    db_session.commit()
    db_session.add(user)
    db_session.commit()

    yield org.id, user.id

    for table in reversed(Base.metadata.sorted_tables):
        column = table.c.get('organization_id')
        if column is None or table.name in ('organizations', 'audit_log'):
            continue
        db_session.execute(table.delete().where(column == org.id))
    db_session.query(Organization).filter(Organization.id == org.id).delete(
        synchronize_session=False
    )
    db_session.commit()


class TestTheSeedFollowsTheModules:
    def test_home_starting_locations_do_not_replace_the_demo_workshop(
        self, db_session: Session, seed_org: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """An organization may already have a root called Cold Storage.

        Reusing it as the demo's zone loses the workshop's plum shelf and
        the production run aborts with zero available Damson stock.
        """
        org_id, user_id = seed_org
        starting = [
            StorageLocation(
                id=uuid.uuid4(),
                organization_id=org_id,
                name=name,
                created_by=user_id,
            )
            for name in ('Cold Storage', 'Fridge A')
        ]
        db_session.add_all(starting)
        db_session.commit()

        first = seed_organization(
            db_session, org_id, user_id, items=3, modules={'maker'}
        )

        assert first['production_runs'] == 1
        run = db_session.query(ProductionOrder).filter_by(organization_id=org_id).one()
        assert run.status == 'COMPLETED'
        assert (
            db_session.query(ProductionOrderLine)
            .filter_by(production_order_id=run.id)
            .count()
            == 3
        )
        assert all(location.parent_id is None for location in starting)
        location_count = (
            db_session.query(StorageLocation).filter_by(organization_id=org_id).count()
        )

        second = seed_organization(
            db_session, org_id, user_id, items=3, modules={'maker'}
        )

        assert second['production_runs'] == 0
        assert second['items_added'] == 0
        assert (
            db_session.query(StorageLocation).filter_by(organization_id=org_id).count()
            == location_count
        )

    def test_products_are_seeded_into_an_organization_with_no_catalogue_of_its_own(
        self, db_session: Session, seed_org: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """The crash: a warehouse organization declares no food categories.

        Nothing here declares any, which is the same starting point — so if the
        seed did not bring the catalogue it files products under, this raises
        ``SeedCategoriesMissingError`` instead of seeding three products.
        """
        org_id, user_id = seed_org

        summary = seed_organization(db_session, org_id, user_id, items=3, modules=set())

        assert summary['items_added'] == 3
        assert (
            db_session.query(Item).filter(Item.organization_id == org_id).count() == 3
        )

    def test_a_warehouse_organization_gets_documents_and_orders(
        self, db_session: Session, seed_org: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_id, user_id = seed_org

        summary = seed_organization(
            db_session,
            org_id,
            user_id,
            items=1,
            modules={'partners', 'warehouse', 'purchase_orders'},
        )

        assert summary['partners'] > 0
        assert summary['documents'] > 0
        assert summary['purchase_orders'] > 0
        assert (
            db_session.query(Document)
            .filter(Document.organization_id == org_id)
            .count()
            > 0
        )
        assert (
            db_session.query(PurchaseOrder)
            .filter(PurchaseOrder.organization_id == org_id)
            .count()
            > 0
        )

    def test_an_organization_without_those_modules_gets_none_of_their_rows(
        self, db_session: Session, seed_org: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Rows in a module that is off are invisible in the product.

        They are not harmless: whoever reads the database next has to explain
        an order nobody could have placed.
        """
        org_id, user_id = seed_org

        summary = seed_organization(
            db_session, org_id, user_id, items=1, modules={'recipes'}
        )

        assert summary['documents'] == 0
        assert summary['purchase_orders'] == 0
        assert summary['partners'] == 0
        assert (
            db_session.query(Document)
            .filter(Document.organization_id == org_id)
            .count()
            == 0
        )
        assert (
            db_session.query(PurchaseOrder)
            .filter(PurchaseOrder.organization_id == org_id)
            .count()
            == 0
        )

    def test_volume_is_topped_up_to_the_target_not_added_to_it(
        self, db_session: Session, seed_org: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_id, user_id = seed_org

        seed_organization(db_session, org_id, user_id, items=3, modules=set())
        second = seed_organization(db_session, org_id, user_id, items=3, modules=set())

        assert second['items_added'] == 0
        assert second['items_total'] == 3
