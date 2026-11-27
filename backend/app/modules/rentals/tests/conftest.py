"""Fixtures for the rentals module's integration tests.

One organization with the equipment register it needs: a category, a place,
three units of one model and one unit of another. The hand-out paths run
through the equipment module, so the fixtures build real assets — a booking
of an item that is not in the register is refused, and testing against a
stub would not see that.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.rentals.models import RentalBooking

# A window no clock reaches: a booking in it is always still to come.
START = datetime(2099, 12, 1, 9, 0, tzinfo=UTC)
END = datetime(2099, 12, 3, 16, 0, tzinfo=UTC)


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def rental_org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Rentals Test Org',
        ['core', 'items', 'locations', 'categories', 'equipment', 'rentals'],
    )


@pytest.fixture
def rental_user(h: ModuleTestHelper, rental_org: Organization) -> User:
    return h.create_user(rental_org, email='rentals@example.com')


@pytest.fixture
def rental_auth(h: ModuleTestHelper, rental_user: User) -> dict[str, str]:
    return h.get_auth_headers(rental_user)


@pytest.fixture
def rental_category(h: ModuleTestHelper, rental_org: Organization) -> Category:
    category = Category(
        name='Projector',
        code='PROJECTOR',
        context_tag='equipment',
        organization_id=rental_org.id,
        field_definitions=[],
    )
    h.db.add(category)
    h.db.commit()
    h.db.refresh(category)
    return category


@pytest.fixture
def rental_place(
    h: ModuleTestHelper, rental_org: Organization, rental_user: User
) -> StorageLocation:
    storage_type = h.create_storage_type('Equipment Store', 'EQ_STORE')
    return h.create_storage_location(
        rental_org, storage_type, rental_user, name='Store room'
    )


def make_asset(
    db: Session,
    org: Organization,
    place: StorageLocation,
    category: Category,
    name: str,
    *,
    model: str = 'Projektor 4K',
    serial: str | None = None,
    status: str = 'AVAILABLE',
) -> Item:
    item = Item(
        name=name,
        organization_id=org.id,
        storage_location_id=place.id,
        category_id=category.id,
        quantity=1,
        meta_data={
            'equipment': {
                'model': model,
                'serial_number': serial or name,
                'equipment_status': status,
            }
        },
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture
def projectors(
    db_session: Session,
    rental_org: Organization,
    rental_place: StorageLocation,
    rental_category: Category,
) -> list[Item]:
    return [
        make_asset(
            db_session,
            rental_org,
            rental_place,
            rental_category,
            f'Projektor 4K #{index}',
            serial=f'PRJ-{index}',
        )
        for index in range(1, 4)
    ]


@pytest.fixture
def screen(
    db_session: Session,
    rental_org: Organization,
    rental_place: StorageLocation,
    rental_category: Category,
) -> Item:
    return make_asset(
        db_session,
        rental_org,
        rental_place,
        rental_category,
        'Ekran 2 m #1',
        model='Ekran 2 m',
        serial='SN-1',
    )


@pytest.fixture
def racks(
    db_session: Session,
    rental_org: Organization,
    rental_place: StorageLocation,
    rental_category: Category,
) -> list[Item]:
    """Two units of one model: the smallest fleet a promise can leave short."""
    return [
        make_asset(
            db_session,
            rental_org,
            rental_place,
            rental_category,
            f'Rack 42U #{index}',
            model='Rack 42U',
            serial=f'RACK-{index}',
        )
        for index in (1, 2)
    ]


@pytest.fixture
def borrower(
    h: ModuleTestHelper, rental_org: Organization, rental_user: User
) -> Partner:
    return h.create_partner(
        rental_org,
        rental_user,
        name='Szkoła Podstawowa nr 3',
        type='CUSTOMER',
        email='szkola@example.com',
    )


def booking_payload(
    *,
    item_id: UUID | None = None,
    model: str | None = None,
    quantity: int = 1,
    starts_at: datetime = START,
    ends_at: datetime = END,
    partner_id: UUID | None = None,
    name: str | None = 'Jan Wiśniewski',
) -> dict:
    line: dict = {}
    if item_id is not None:
        line['item_id'] = str(item_id)
    if model is not None:
        line = {'model': model, 'quantity': quantity}
    payload: dict[str, object] = {
        'starts_at': starts_at.isoformat(),
        'ends_at': ends_at.isoformat(),
        'lines': [line],
    }
    if partner_id is not None:
        payload['borrower_partner_id'] = str(partner_id)
    else:
        payload['borrower_name'] = name
    return payload


def make_overdue(db: Session, booking_id: str, ends_at: datetime) -> None:
    """Put a handed-out booking's due time in the past, as waiting would."""
    booking = db.get(RentalBooking, UUID(booking_id))
    assert booking is not None and booking.status == 'PICKED_UP'
    booking.ends_at = ends_at
    db.commit()


@pytest.fixture
def window() -> tuple[datetime, datetime]:
    return START, START + timedelta(days=2)
