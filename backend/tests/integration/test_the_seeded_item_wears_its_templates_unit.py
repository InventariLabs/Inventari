"""The demo seed obeys the rule it demonstrates.

The equipment seeder wrote ``pcs`` onto every record it made and ignored the
unit the template it was handed declares, while the food seeder beside it
used ``uom_id=template.uom_id``. Two seeders, two answers to "a quantity of
what", and the demo data shipped the very contradiction the item guard exists
to refuse: a record that disagrees with its own catalogue row about the unit.

The template's unit is the reference (see the item unit guard), so the seeder
follows it — pieces remain only as the stand-in for a template that has no
unit of its own. Every equipment template happens to declare pieces today, so
the difference is invisible until a template says something else, which is
the state an organization reaches by editing a product's unit.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.services.token_service import get_password_hash
from seed_demo_data import _create_equipment_items

pytestmark = pytest.mark.integration

#: The category the equipment templates are filed under, as the seeder names
#: it — the direct call below hands it the same map the full run builds.
_CATEGORY_CODE = 'laptop'


@pytest.fixture
def seed_org(db_session: Session) -> Generator[tuple[uuid.UUID, uuid.UUID]]:
    """A bare organization and its author, taken away the way the wipe does."""
    org = Organization(id=uuid.uuid4(), name='Seed Unit Org')
    user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=f'seed-unit+{uuid.uuid4().hex[:8]}@example.com',
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


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f"'{symbol}' is not in the seeded catalogue"
    return uom


def _equipment_locations(db: Session, org_id: uuid.UUID, created_by: uuid.UUID) -> dict:
    """A shelf deep enough for the seeder: area → room → shelf, tagged.

    The seeder reads the shelf's parents out of the same map it is handed, so
    all three levels travel — an area with no room under it is not a leaf.
    """
    area = StorageLocation(
        organization_id=org_id,
        created_by=created_by,
        name='Office Building',
        usage='internal',
        context_tag='equipment',
    )
    db.add(area)
    db.flush()
    room = StorageLocation(
        organization_id=org_id,
        created_by=created_by,
        parent_id=area.id,
        name='Server Room',
        usage='stock',
        context_tag='equipment',
    )
    db.add(room)
    db.flush()
    shelf = StorageLocation(
        organization_id=org_id,
        created_by=created_by,
        parent_id=room.id,
        name='Server Rack A',
        usage='stock',
        context_tag='equipment',
    )
    db.add(shelf)
    db.commit()
    return {str(area.id): area, str(room.id): room, str(shelf.id): shelf}


def _category_id(db: Session, org_id: uuid.UUID, *, code: str) -> uuid.UUID:
    """The category the seeder's templates are filed under.

    The seeder stops rather than filing a template under a category that is
    not there, so this one exists before the call.
    """
    from app.models.category import Category

    category = db.scalars(
        select(Category).where(
            Category.organization_id == org_id, Category.code == code
        )
    ).first()
    if category is None:
        category = Category(organization_id=org_id, name='Laptops', code=code)
        db.add(category)
        db.commit()
    return category.id


def _recorded_unit(db: Session, org_id: uuid.UUID, template_id: uuid.UUID) -> set:
    db.expire_all()
    return {
        record.uom_id
        for record in db.scalars(
            select(Item).where(
                Item.organization_id == org_id, Item.template_id == template_id
            )
        ).all()
    }


class TestTheSeededItemWearsItsTemplatesUnit:
    def test_a_template_kept_in_another_unit_is_followed_by_its_record(
        self, db_session: Session, seed_org: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """The differential: a template whose unit is not pieces.

        The seeder that hard-codes pieces looks correct only while every
        template it ever meets says pieces. This one says grams — the state an
        organization reaches by editing a product's unit — and the record
        written for it has to follow.
        """
        org_id, user_id = seed_org
        grams = _uom(db_session, 'g')
        pieces = _uom(db_session, 'pcs')
        template = ProductTemplate(
            organization_id=org_id,
            name='Bench power supply',
            uom_id=grams.id,
        )
        db_session.add(template)
        db_session.commit()

        written = _create_equipment_items(
            db_session,
            org_id,
            user_id,
            [(template, _CATEGORY_CODE)],
            _equipment_locations(db_session, org_id, user_id),
            {'pcs': pieces.id, 'g': grams.id},
            {_CATEGORY_CODE: _category_id(db_session, org_id, code=_CATEGORY_CODE)},
        )

        assert written > 0, 'the seeder wrote no record for the template'
        assert _recorded_unit(db_session, org_id, template.id) == {grams.id}

    def test_a_template_without_a_unit_still_gets_pieces(
        self, db_session: Session, seed_org: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """The control: the fallback the hard-coded unit was standing in for.

        A template born before the unit world has no unit of its own, and the
        seeder still has to give its records something to be counted in.
        """
        org_id, user_id = seed_org
        pieces = _uom(db_session, 'pcs')
        template = ProductTemplate(
            organization_id=org_id,
            name='Uncatalogued bench supply',
            uom_id=None,
        )
        db_session.add(template)
        db_session.commit()

        _create_equipment_items(
            db_session,
            org_id,
            user_id,
            [(template, _CATEGORY_CODE)],
            _equipment_locations(db_session, org_id, user_id),
            {'pcs': pieces.id},
            {_CATEGORY_CODE: _category_id(db_session, org_id, code=_CATEGORY_CODE)},
        )

        assert _recorded_unit(db_session, org_id, template.id) == {pieces.id}
