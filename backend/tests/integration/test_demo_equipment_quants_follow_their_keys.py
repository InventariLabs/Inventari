"""The demo seeder puts each equipment record's stock where the record stands.

``_create_equipment_items`` used to aggregate quantities into a dict keyed by
(template, location) and write one StockQuant per key. The write named
``loc`` — the loop variable leaked out of the item loop, the last location
any item happened to land on — so every equipment quant landed in one place
no matter what its key said, and the quant-uniqueness constraint turned that
silent corruption into a loud UniqueViolation mid-seed.

The seed no longer writes quants itself, and the quant table is gone:
``_open_the_shelves`` opens each record's stock through the core movement
call, on the record's own shelf, and the shelf is what the records hold.
The property this file guards is the same one — the stock sits where the
records do — measured on the path that now writes it: the opening
movements, and the records' view.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

import seed_demo_data
from app.core.testing import ShelfRow
from app.database import Base
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove, StockMoveReferenceType
from app.models.storage_location import StorageLocation
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.services.token_service import get_password_hash

pytestmark = pytest.mark.integration


class _CyclingRandom:
    """A stand-in for the seeder's ``random`` that answers 1 item per
    template and hands out locations in a fixed cycle, so the test proves
    the mapping instead of a dice roll."""

    def __init__(self, choices):
        self._choices = list(choices)
        self._i = 0
        self._n = 0

    def randint(self, a: int, b: int) -> int:
        if b <= 5:
            return 1  # the per-template item count
        self._n += 1
        return a + self._n  # serials stay unique within the org

    def choice(self, _seq):
        value = self._choices[self._i % len(self._choices)]
        self._i += 1
        return value


@pytest.fixture
def equip_org(db_session: Session) -> Generator[dict]:
    """An organization with two equipment templates and three leaf
    locations, deep enough for ``_get_equip_leaf_locations`` to see them."""
    org = Organization(id=uuid.uuid4(), name='Demo Equipment Org')
    db_session.add(org)
    db_session.commit()
    user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=f'demo-equip+{uuid.uuid4().hex[:8]}@example.com',
        full_name='Seed',
        hashed_password=get_password_hash('seed-test-password'),
    )
    uom_category = UomCategory(id=uuid.uuid4(), name='units')
    uom = Uom(
        id=uuid.uuid4(),
        organization_id=None,
        category_id=uom_category.id,
        name='Piece',
        symbol=seed_demo_data.UOM_PIECE,
        factor=Decimal('1'),
    )
    db_session.add_all([user, uom_category, uom])
    db_session.commit()

    cat_ids = {}
    for cat_key in ('laptop', 'projector'):
        cat = Category(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=cat_key.title(),
            code=cat_key,
        )
        db_session.add(cat)
        cat_ids[cat_key] = cat.id
    db_session.commit()

    root = StorageLocation(
        id=uuid.uuid4(),
        organization_id=org.id,
        name='HQ',
        context_tag=None,
        created_by=user.id,
    )
    db_session.add(root)
    db_session.commit()

    locations: dict[str, StorageLocation] = {'root': root}
    leaves = []
    for i in (1, 2, 3):
        parent = StorageLocation(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=f'Wing {i}',
            parent_id=root.id,
            context_tag='equipment',
            created_by=user.id,
        )
        db_session.add(parent)
        db_session.commit()
        leaf = StorageLocation(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=f'Room {i}',
            parent_id=parent.id,
            context_tag='equipment',
            created_by=user.id,
        )
        db_session.add(leaf)
        db_session.commit()
        locations[f'wing{i}'] = parent
        locations[f'leaf{i}'] = leaf
        leaves.append(leaf)

    templates = []
    for cat_key, name in (('laptop', 'Demo Laptop'), ('projector', 'Demo Projector')):
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=name,
            brand='DemoBrand',
            barcode=f'DEMO-{uuid.uuid4().hex[:10]}',
            uom_id=uom.id,
        )
        db_session.add(template)
        templates.append((template, cat_key))
    db_session.commit()

    yield {
        'org_id': org.id,
        'user_id': user.id,
        'templates': templates,
        'locations': locations,
        'leaves': leaves,
        'uom_ids': {seed_demo_data.UOM_PIECE: uom.id},
        'cat_ids': cat_ids,
    }

    for table in reversed(Base.metadata.sorted_tables):
        column = table.c.get('organization_id')
        if column is None or table.name in ('organizations', 'audit_log'):
            continue
        db_session.execute(table.delete().where(column == org.id))
    db_session.query(Organization).filter(Organization.id == org.id).delete(
        synchronize_session=False
    )
    db_session.commit()


class TestEquipmentStockFollowsItsKeys:
    def test_every_opening_lands_where_its_own_key_says(
        self, db_session: Session, equip_org: dict, monkeypatch
    ):
        """The opening's location is the record's own, not a leaked loop
        variable: the set of places the stock was opened on equals the set
        of item locations, and the shelves read the same."""
        org_id = equip_org['org_id']
        monkeypatch.setattr(
            seed_demo_data, 'random', _CyclingRandom(equip_org['leaves'])
        )

        created = seed_demo_data._create_equipment_items(
            db_session,
            org_id,
            equip_org['user_id'],
            equip_org['templates'],
            equip_org['locations'],
            equip_org['uom_ids'],
            equip_org['cat_ids'],
        )
        # The opening reads committed records on a connection of its own.
        db_session.commit()
        seed_demo_data._open_the_shelves(org_id, equip_org['user_id'])
        db_session.expire_all()

        assert created == 2

        item_places = {
            (row[0], row[1])
            for row in db_session.query(Item.template_id, Item.storage_location_id)
            .filter(Item.organization_id == org_id)
            .all()
        }
        openings = (
            db_session.query(StockMove)
            .filter(
                StockMove.organization_id == org_id,
                StockMove.reference_type == StockMoveReferenceType.OPENING_BALANCE,
            )
            .all()
        )
        assert len(openings) == 2

        # The two items were placed on two different leaves, so the stock
        # must be opened in two different places too — one per placement.
        assert len(item_places) == 2
        opened_on = {(m.product_template_id, m.to_location_id) for m in openings}
        assert opened_on == item_places
        shelves = {
            (row.product_template_id, row.storage_location_id)
            for row in db_session.query(ShelfRow)
            .filter(ShelfRow.organization_id == org_id)
            .all()
        }
        assert shelves == item_places
