"""Reminders: once before the end, once per organization-local day when late."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.public_api import core_api
from app.modules.rentals._reminders import check_organization_reminders
from app.modules.rentals.models import RentalBooking
from app.modules.rentals.tests.conftest import booking_payload, make_overdue

pytestmark = pytest.mark.integration

RENTALS = '/api/v1/rentals'


class MailSpy:
    def __init__(self, configured: bool = True) -> None:
        self.configured = configured
        self.sent: list[dict] = []

    async def can_send(self, _db, _org_id) -> bool:
        return self.configured

    async def send(self, to_email, subject, html, *_args, **_kwargs) -> bool:
        self.sent.append({'to': to_email, 'subject': subject, 'html': html})
        return True


@pytest.fixture
def mail(monkeypatch) -> MailSpy:
    spy = MailSpy()
    monkeypatch.setattr(core_api.email, 'can_send_async', spy.can_send)
    monkeypatch.setattr(core_api.email, 'send_async', spy.send)
    return spy


def _create(client: TestClient, auth: dict[str, str], **kwargs):
    return client.post(
        f'{RENTALS}/bookings', headers=auth, json=booking_payload(**kwargs)
    )


def _picked_up(client: TestClient, auth: dict[str, str], item_id, **kwargs) -> dict:
    booking = _create(client, auth, item_id=item_id, **kwargs)
    assert booking.status_code == 201, booking.text
    response = client.post(
        f'{RENTALS}/bookings/{booking.json()["id"]}/pickup',
        headers=auth,
        json={'item_ids': [str(item_id)]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _run(engine, org_id, now: datetime) -> tuple[int, int]:
    """Run the worker on its own async session, as the scheduler does."""

    async def run() -> tuple[int, int]:
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as db:
            result = await check_organization_reminders(db, org_id, now)
            await db.commit()
            return result

    return asyncio.run(run())


def test_the_end_reminder_goes_once_inside_the_last_day(
    client: TestClient,
    rental_auth: dict[str, str],
    projectors,
    borrower,
    rental_org,
    mail: MailSpy,
    db_session: Session,
    async_engine_fixture,
) -> None:
    now = datetime.now(UTC)
    booking = _picked_up(
        client,
        rental_auth,
        projectors[0].id,
        partner_id=borrower.id,
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=12),
    )

    sent, late = _run(async_engine_fixture, rental_org.id, now)
    assert (sent, late) == (1, 0)
    assert len(mail.sent) == 1
    assert mail.sent[0]['to'] == borrower.email
    assert mail.sent[0]['subject']

    # The worker may run every few minutes; the borrower hears once.
    sent, late = _run(async_engine_fixture, rental_org.id, now + timedelta(minutes=15))
    assert (sent, late) == (0, 0)
    assert len(mail.sent) == 1

    db_session.expire_all()
    stored = db_session.get(RentalBooking, booking['id'])
    assert stored is not None
    assert stored.end_reminder_sent_at is not None


def test_a_booking_further_than_a_day_away_waits(
    client: TestClient,
    rental_auth: dict[str, str],
    projectors,
    borrower,
    rental_org,
    mail: MailSpy,
    async_engine_fixture,
) -> None:
    now = datetime.now(UTC)
    _picked_up(
        client,
        rental_auth,
        projectors[0].id,
        partner_id=borrower.id,
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=48),
    )
    sent, late = _run(async_engine_fixture, rental_org.id, now)
    assert (sent, late) == (0, 0)
    assert mail.sent == []


def test_the_late_reminder_is_daily_in_the_organization_day(
    client: TestClient,
    rental_auth: dict[str, str],
    projectors,
    borrower,
    rental_org,
    mail: MailSpy,
    db_session: Session,
    async_engine_fixture,
) -> None:
    now = datetime.now(UTC)
    booking = _picked_up(
        client,
        rental_auth,
        projectors[0].id,
        partner_id=borrower.id,
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=12),
    )
    make_overdue(db_session, booking['id'], now - timedelta(days=2))
    db_session.expire_all()

    sent, late = _run(async_engine_fixture, rental_org.id, now)
    assert (sent, late) == (0, 1)
    assert len(mail.sent) == 1
    assert mail.sent[0]['subject']

    sent, late = _run(async_engine_fixture, rental_org.id, now + timedelta(hours=1))
    assert (sent, late) == (0, 0)
    assert len(mail.sent) == 1

    # Tomorrow's pass nudges again; a booking still out a month later is not
    # forgotten.
    stored = db_session.get(RentalBooking, booking['id'])
    assert stored is not None
    stored.late_reminder_sent_on = (now - timedelta(days=1)).date()
    db_session.commit()
    sent, late = _run(async_engine_fixture, rental_org.id, now)
    assert (sent, late) == (0, 1)
    assert len(mail.sent) == 2


def test_no_mail_is_marked_sent_when_the_organization_cannot_send(
    client: TestClient,
    rental_auth: dict[str, str],
    projectors,
    borrower,
    rental_org,
    mail: MailSpy,
    db_session: Session,
    async_engine_fixture,
) -> None:
    mail.configured = False
    now = datetime.now(UTC)
    booking = _picked_up(
        client,
        rental_auth,
        projectors[0].id,
        partner_id=borrower.id,
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=12),
    )
    sent, late = _run(async_engine_fixture, rental_org.id, now)
    assert (sent, late) == (0, 0)
    assert mail.sent == []
    db_session.expire_all()
    stored = db_session.get(RentalBooking, booking['id'])
    assert stored is not None
    assert stored.end_reminder_sent_at is None
