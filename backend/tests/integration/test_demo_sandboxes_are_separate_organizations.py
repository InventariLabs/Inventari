"""Two demo visitors, two organizations, and neither sees the other's.

A demo visitor gets an organization of their own, seeded with the same demo
data as every other visitor's (``manage.py demo fill-pool``). The seed was
written for one organization per instance, and in two places it read the
whole instance where it meant its own organization: the storage types its
shelves are built on, and the colleagues its showcase hires. With a second
organization on the instance, the second visitor's shelves stood on the first
one's storage types and the first one's colleagues decided the second one's
purchase orders.

Each sandbox here is opened by the function the pool uses, seeded and dressed
as the pool seeds it, and read through the API as its own administrator.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli.commands_demo import open_sandbox_account
from app.database import Base
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.warehouse.models import Document
from app.services.token_service import create_access_token
from tests.integration._demo_world import ids, pooled_sandboxes

pytestmark = pytest.mark.integration


def _remove(db: Session, org_id: uuid.UUID) -> None:
    # The organization names its creator; let go of the account before it goes.
    db.query(Organization).filter(Organization.id == org_id).update(
        {Organization.created_by: None}, synchronize_session=False
    )
    for table in reversed(Base.metadata.sorted_tables):
        column = table.c.get('organization_id')
        if column is None or table.name in ('organizations', 'audit_log'):
            continue
        db.execute(table.delete().where(column == org_id))
    db.query(Organization).filter(Organization.id == org_id).delete(
        synchronize_session=False
    )
    db.commit()


@pytest.fixture
def two_sandboxes(
    demo_world, async_engine_fixture, db_session: Session
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Two visitors' organizations, each with its administrator, seeded and dressed."""
    payload = demo_world('pooled-sandboxes', pooled_sandboxes(async_engine_fixture))
    opened = [ids(pair) for pair in payload]
    for _org_id, user_id in opened:
        admin = db_session.get(User, user_id)
        assert admin is not None
        admin.is_active = True  # what handing it to a visitor does
    db_session.commit()
    return opened


def _as(user_id: uuid.UUID) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user_id)})}'
    }


def _ids(body: Any) -> set[str]:
    """The ids a list answered with, whichever envelope it uses."""
    if isinstance(body, list):
        rows = body
    else:
        rows = body['items']
    return {row['id'] for row in rows}


def _one_of(db: Session, model: Any, org_id: uuid.UUID) -> str:
    row = db.scalar(select(model.id).where(model.organization_id == org_id).limit(1))
    assert row is not None, f'the sandbox has no {model.__tablename__}'
    return str(row)


#: (what, the list a visitor reads, where one record of it answers, its model)
_SURFACES = [
    ('items', '/api/v1/items', '/api/v1/items/{}', Item),
    (
        'documents',
        '/api/v1/warehouse/documents',
        '/api/v1/warehouse/documents/{}',
        Document,
    ),
    ('partners', '/api/v1/partners', '/api/v1/partners/{}', Partner),
    ('members', '/api/v1/organizations/my/members', None, User),
]


class TestNeitherVisitorSeesTheOther:
    def test_lists_and_records_stay_in_their_own_organization(
        self, client, db_session: Session, two_sandboxes
    ) -> None:
        """One test over every surface: each sandbox costs a seed to open."""
        for what, listing, record, model in _SURFACES:
            for (_mine, me), (theirs, _them) in (
                (two_sandboxes[0], two_sandboxes[1]),
                (two_sandboxes[1], two_sandboxes[0]),
            ):
                response = client.get(listing, headers=_as(me))
                assert response.status_code == 200, (what, response.text)
                seen = _ids(response.json())
                assert seen, f'a visitor sees no {what} of their own'
                other = set(
                    map(
                        str,
                        db_session.scalars(
                            select(model.id).where(model.organization_id == theirs)
                        ),
                    )
                )
                assert not seen & other, f"a visitor sees the other sandbox's {what}"
                if record is not None:
                    foreign = _one_of(db_session, model, theirs)
                    opened = client.get(record.format(foreign), headers=_as(me))
                    assert opened.status_code == 404, (what, opened.status_code)


class TestTheSeedStaysInsideItsOrganization:
    def test_the_storage_type_map_names_this_organizations_own_types(
        self, db_session: Session
    ) -> None:
        """Every organization has a SHELF of its own; the map asked for one names its.

        The map used to be read across the instance, so a code two
        organizations share resolved to whichever row came back last — the
        newest organization's, on a fresh table — and the older one's shelves
        were built on the newer one's types.
        """
        from seed_demo_data import _ensure_storage_types

        older, _user, _email = open_sandbox_account(db_session)
        newer, _user, _email = open_sandbox_account(db_session)
        try:
            type_ids = _ensure_storage_types(db_session, older)
            owners = set(
                db_session.scalars(
                    select(StorageType.organization_id).where(
                        StorageType.id.in_(type_ids.values())
                    )
                )
            )
            assert owners <= {older, None}, owners
        finally:
            db_session.rollback()
            _remove(db_session, older)
            _remove(db_session, newer)

    def test_every_shelf_stands_on_a_storage_type_of_its_own_organization(
        self, db_session: Session, two_sandboxes
    ) -> None:
        for org_id, _user_id in two_sandboxes:
            foreign = db_session.scalars(
                select(StorageType.type_code)
                .join(
                    StorageLocation, StorageLocation.storage_type_id == StorageType.id
                )
                .where(
                    StorageLocation.organization_id == org_id,
                    StorageType.organization_id.is_not(None),
                    StorageType.organization_id != org_id,
                )
            ).all()
            assert not foreign, f"shelves stand on another org's types: {foreign}"

    def test_each_organization_hires_colleagues_of_its_own(
        self, db_session: Session, two_sandboxes
    ) -> None:
        for org_id, user_id in two_sandboxes:
            colleagues = db_session.scalars(
                select(User.full_name).where(
                    User.organization_id == org_id, User.id != user_id
                )
            ).all()
            assert sorted(colleagues) == ['Ava Brennan', 'Marcus Webb'], colleagues
