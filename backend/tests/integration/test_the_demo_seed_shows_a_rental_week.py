"""The rentals demo has to read like a lending week, not like four rows.

The seed writes one late loan, one pickup for today, one return due today,
one loan that came back last week and one unit in service. The "Today" screen
reads those five states from the clock, so a seed that loses the day boundary
— a pickup six hours from midnight is tomorrow's — leaves the module's first
screen empty on a demo that reports every count as written.

The rows a reader sees also carry no seed marker: a note that says
``SEED-pickup today`` reaches the booking card in the product.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.modules.rentals.models import (
    RentalBlock,
    RentalBooking,
    RentalBufferRule,
)
from seed_demo_data import clean_seed_data
from tests.integration._demo_world import ids, seeded_organization

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(demo_world) -> uuid.UUID:
    """An organization seeded with every module."""
    payload = demo_world('org-120', seeded_organization(items=120))
    return ids(payload)[0]


def _bookings(db: Session, org_id: uuid.UUID, status: str) -> list[RentalBooking]:
    return (
        db.query(RentalBooking)
        .filter(
            RentalBooking.organization_id == org_id,
            RentalBooking.status == status,
        )
        .all()
    )


class TestTheRentalWeek:
    def test_a_late_loan_is_waiting_on_the_first_screen(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        now = datetime.now(UTC)
        late = [
            booking
            for booking in _bookings(db_session, seeded, 'PICKED_UP')
            if booking.ends_at < now and booking.note == 'late loan'
        ]
        assert len(late) == 1
        # Due yesterday, so the row says "1 day late", not "2".
        assert late[0].ends_at.date() == now.date() - timedelta(days=1)

    def test_a_pickup_and_a_return_are_on_today(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        pickups = [
            booking
            for booking in _bookings(db_session, seeded, 'RESERVED')
            if day_start <= booking.starts_at < day_end
        ]
        assert len(pickups) == 1, 'no pickup is dated today'
        assert pickups[0].note == 'pickup today'

        returns = [
            booking
            for booking in _bookings(db_session, seeded, 'PICKED_UP')
            if day_start <= booking.ends_at < day_end
        ]
        assert len(returns) == 1, 'no return is due today'
        assert returns[0].note == 'return today'

    def test_a_service_block_keeps_a_unit_off_the_calendar(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        now = datetime.now(UTC)
        blocks = (
            db_session.query(RentalBlock)
            .filter(RentalBlock.organization_id == seeded)
            .all()
        )
        assert len(blocks) == 1
        assert blocks[0].source == 'SERVICE'
        assert blocks[0].starts_at <= now < blocks[0].ends_at
        assert 'SEED-' not in blocks[0].reason

        rules = (
            db_session.query(RentalBufferRule)
            .filter(RentalBufferRule.organization_id == seeded)
            .all()
        )
        assert len(rules) == 1
        assert rules[0].hours_before == 2
        assert rules[0].hours_after == 4

    def test_no_reader_visible_field_carries_the_seed_marker(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        for booking in (
            db_session.query(RentalBooking)
            .filter(RentalBooking.organization_id == seeded)
            .all()
        ):
            assert not (booking.note or '').startswith('SEED-'), booking.note


class TestCleanLeavesNoRentalsBehind:
    def test_cleaning_removes_bookings_blocks_and_buffer_rules(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        clean_seed_data(db_session, seeded)
        db_session.commit()

        for model in (RentalBooking, RentalBlock, RentalBufferRule):
            left = (
                db_session.query(model).filter(model.organization_id == seeded).count()
            )
            assert left == 0, f'{model.__tablename__} left {left} row(s)'
