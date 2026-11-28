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


def test_the_reminder_names_the_units_still_to_bring_back(
    client: TestClient,
    rental_auth: dict[str, str],
    projectors,
    borrower,
    rental_org,
    mail: MailSpy,
    async_engine_fixture,
) -> None:
    now = datetime.now(UTC)
    payload = booking_payload(
        partner_id=borrower.id,
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=12),
    )
    payload['lines'] = [{'item_id': str(item.id)} for item in projectors[:2]]
    booking = client.post(
        f'{RENTALS}/bookings', headers=rental_auth, json=payload
    ).json()
    picked = client.post(
        f'{RENTALS}/bookings/{booking["id"]}/pickup',
        headers=rental_auth,
        json={'item_ids': [str(item.id) for item in projectors[:2]]},
    ).json()
    returned = next(
        unit
        for line in picked['lines']
        for unit in line['units']
        if unit['item_id'] == str(projectors[0].id)
    )
    response = client.post(
        f'{RENTALS}/bookings/{booking["id"]}/return',
        headers=rental_auth,
        json={'units': [{'unit_id': returned['id'], 'condition': 'GOOD'}]},
    )
    assert response.status_code == 200, response.text

    assert _run(async_engine_fixture, rental_org.id, now) == (1, 0)
    html = mail.sent[0]['html']
    assert projectors[1].name in html
    assert projectors[0].name not in html


@pytest.mark.parametrize(
    ('language', 'late_for_one', 'late_for_three'),
    [
        ('en', '<b>1 day</b>', '<b>3 days</b>'),
        ('pl', '<b>1 dzień</b>', '<b>3 dni</b>'),
        ('de', '<b>1 Tag</b>', '<b>3 Tage</b>'),
        ('fr', '<b>1 jour</b>', '<b>3 jours</b>'),
        ('es', '<b>1 día</b>', '<b>3 días</b>'),
        ('pt', '<b>1 dia</b>', '<b>3 dias</b>'),
    ],
)
def test_the_late_reminder_counts_in_days(
    client: TestClient,
    rental_auth: dict[str, str],
    rental_user,
    projectors,
    borrower,
    rental_org,
    mail: MailSpy,
    db_session: Session,
    async_engine_fixture,
    language: str,
    late_for_one: str,
    late_for_three: str,
) -> None:
    rental_user.preferred_language = language
    db_session.commit()
    now = datetime.now(UTC)
    booking = _picked_up(
        client,
        rental_auth,
        projectors[0].id,
        partner_id=borrower.id,
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=12),
    )
    make_overdue(db_session, booking['id'], now - timedelta(days=1))
    db_session.expire_all()
    assert _run(async_engine_fixture, rental_org.id, now) == (0, 1)
    assert late_for_one in mail.sent[-1]['html']

    stored = db_session.get(RentalBooking, booking['id'])
    assert stored is not None
    stored.late_reminder_sent_on = None
    stored.ends_at = now - timedelta(days=3)
    db_session.commit()
    assert _run(async_engine_fixture, rental_org.id, now) == (0, 1)
    assert late_for_three in mail.sent[-1]['html']


def test_an_extended_loan_is_reminded_before_its_new_end(
    client: TestClient,
    rental_auth: dict[str, str],
    projectors,
    borrower,
    rental_org,
    mail: MailSpy,
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
    assert _run(async_engine_fixture, rental_org.id, now) == (1, 0)

    new_end = now + timedelta(days=3)
    extended = client.post(
        f'{RENTALS}/bookings/{booking["id"]}/extend',
        headers=rental_auth,
        json={'ends_at': new_end.isoformat()},
    )
    assert extended.status_code == 200, extended.text

    before_new_end = new_end - timedelta(hours=2)
    assert _run(async_engine_fixture, rental_org.id, before_new_end) == (1, 0)
    assert len(mail.sent) == 2
