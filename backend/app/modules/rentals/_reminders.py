"""Rental reminders: before the window ends, and once a day while late.

Both moments are read from the booking and the organization's clock, never
stored as a status. A marker on the booking makes the send idempotent: the
worker may run every few minutes, the borrower still receives one mail for
the approaching end and at most one for each organization-local day a loan
stays out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import markupsafe
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.module_sdk import format_datetime_for, get_logger
from app.core.public_api import core_api

from .models import RentalBooking, RentalBookingLine

logger = get_logger(__name__)

#: How long before the promised end the borrower hears about it.
REMINDER_WINDOW = timedelta(hours=24)
#: How often the scheduler asks whether anything is due.
CHECK_INTERVAL = timedelta(minutes=15)
DEFAULT_LANG = 'en'

LABELS: dict[str, dict[str, str]] = {
    'en': {
        'greeting': 'Hello',
        'end_subject': 'Your rental ends soon',
        'end_heading': 'Return reminder',
        'end_body': (
            'The rental of <b>{what}</b> ends on <b>{until}</b>. '
            'Please return it on time so the next borrower finds it ready.'
        ),
        'late_subject': 'Your rental is overdue',
        'late_heading': 'Overdue rental',
        'late_body': (
            'The rental of <b>{what}</b> was due on <b>{due}</b> and is '
            '<b>{days}</b> late. Please return it as soon as possible.'
        ),
        'footer': 'This is an automated message from Inventari.',
    },
    'pl': {
        'greeting': 'Witaj',
        'end_subject': 'Twoje wypożyczenie wkrótce się kończy',
        'end_heading': 'Przypomnienie o zwrocie',
        'end_body': (
            'Wypożyczenie <b>{what}</b> kończy się <b>{until}</b>. '
            'Zwróć sprzęt na czas, aby następny biorca zastał go gotowym.'
        ),
        'late_subject': 'Twoje wypożyczenie jest przeterminowane',
        'late_heading': 'Przeterminowane wypożyczenie',
        'late_body': (
            'Wypożyczenie <b>{what}</b> miało zostać zwrócone <b>{due}</b> '
            'i jest spóźnione o <b>{days}</b>. Zwróć je jak najszybciej.'
        ),
        'footer': 'To jest automatyczna wiadomość z systemu Inventari.',
    },
    'de': {
        'greeting': 'Hallo',
        'end_subject': 'Ihre Ausleihe endet bald',
        'end_heading': 'Rückgabeerinnerung',
        'end_body': (
            'Die Ausleihe von <b>{what}</b> endet am <b>{until}</b>. '
            'Bitte geben Sie sie rechtzeitig zurück, damit die nächste '
            'Person sie einsatzbereit vorfindet.'
        ),
        'late_subject': 'Ihre Ausleihe ist überfällig',
        'late_heading': 'Überfällige Ausleihe',
        'late_body': (
            'Die Ausleihe von <b>{what}</b> war am <b>{due}</b> fällig und '
            'ist <b>{days}</b> überfällig. Bitte geben Sie sie so bald wie '
            'möglich zurück.'
        ),
        'footer': 'Dies ist eine automatische Nachricht von Inventari.',
    },
    'fr': {
        'greeting': 'Bonjour',
        'end_subject': 'Votre location se termine bientôt',
        'end_heading': 'Rappel de retour',
        'end_body': (
            'La location de <b>{what}</b> se termine le <b>{until}</b>. '
            'Veuillez la rapporter à temps pour que la personne suivante '
            'la trouve prête.'
        ),
        'late_subject': 'Votre location est en retard',
        'late_heading': 'Location en retard',
        'late_body': (
            'La location de <b>{what}</b> devait être rendue le <b>{due}</b> '
            'et a <b>{days}</b> de retard. Veuillez la rapporter dès que possible.'
        ),
        'footer': "Ceci est un message automatique d'Inventari.",
    },
    'es': {
        'greeting': 'Hola',
        'end_subject': 'Su alquiler termina pronto',
        'end_heading': 'Recordatorio de devolución',
        'end_body': (
            'El alquiler de <b>{what}</b> termina el <b>{until}</b>. '
            'Devuélvalo a tiempo para que la siguiente persona lo encuentre listo.'
        ),
        'late_subject': 'Su alquiler está atrasado',
        'late_heading': 'Alquiler atrasado',
        'late_body': (
            'El alquiler de <b>{what}</b> debía devolverse el <b>{due}</b> y '
            'lleva <b>{days}</b> de retraso. Devuélvalo lo antes posible.'
        ),
        'footer': 'Este es un mensaje automático de Inventari.',
    },
    'pt': {
        'greeting': 'Olá',
        'end_subject': 'O seu aluguer termina em breve',
        'end_heading': 'Lembrete de devolução',
        'end_body': (
            'O aluguer de <b>{what}</b> termina a <b>{until}</b>. '
            'Devolva-o a tempo para que a próxima pessoa o encontre pronto.'
        ),
        'late_subject': 'O seu aluguer está atrasado',
        'late_heading': 'Aluguer atrasado',
        'late_body': (
            'O aluguer de <b>{what}</b> devia ser devolvido a <b>{due}</b> e '
            'está <b>{days}</b> atrasado. Devolva-o o mais depressa possível.'
        ),
        'footer': 'Esta é uma mensagem automática do Inventari.',
    },
}


def _labels(lang: str) -> dict[str, str]:
    return LABELS.get(lang, LABELS[DEFAULT_LANG])


def _late_days(ends_at: datetime, now: datetime) -> int:
    if now <= ends_at:
        return 0
    return max(1, (now.date() - ends_at.date()).days)


def _what(booking: RentalBooking) -> str:
    parts: list[str] = []
    seen_kits: set[UUID] = set()
    for line in booking.lines:
        if line.kit_id is not None:
            if line.kit_id in seen_kits:
                continue
            seen_kits.add(line.kit_id)
            parts.append(line.kit_name or '')
            continue
        if line.model:
            parts.append(line.model)
    return ', '.join(part for part in parts if part) or '—'


def _html(
    lang: str,
    heading: str,
    body: str,
    name: str,
) -> str:
    labels = _labels(lang)
    display = markupsafe.escape(name)
    return core_api.email.render_shell(
        heading,
        (f'<p>{labels["greeting"]} {display},</p><p>{body}</p>'),
        labels['footer'],
    )


async def _language_of_creator(db: AsyncSession, booking: RentalBooking) -> str:
    if booking.created_by is None:
        return DEFAULT_LANG
    user = await core_api.users.get_async(
        db, booking.organization_id, booking.created_by
    )
    language = getattr(user, 'preferred_language', None) if user is not None else None
    return language if language in LABELS else DEFAULT_LANG


async def _send_end_reminder(
    db: AsyncSession, booking: RentalBooking, now: datetime
) -> bool:
    lang = await _language_of_creator(db, booking)
    labels = _labels(lang)
    until = format_datetime_for(
        lang, booking.ends_at.astimezone(await _timezone(db, booking.organization_id))
    )
    body = labels['end_body'].format(
        what=markupsafe.escape(_what(booking)),
        until=markupsafe.escape(until),
    )
    sent = await core_api.email.send_async(
        booking.borrower_email or '',
        labels['end_subject'],
        _html(lang, labels['end_heading'], body, booking.borrower_name),
        organization_id=booking.organization_id,
    )
    if sent:
        booking.end_reminder_sent_at = now
    return sent


async def _send_late_reminder(
    db: AsyncSession, booking: RentalBooking, now: datetime
) -> bool:
    lang = await _language_of_creator(db, booking)
    labels = _labels(lang)
    tz = await _timezone(db, booking.organization_id)
    due = format_datetime_for(lang, booking.ends_at.astimezone(tz))
    body = labels['late_body'].format(
        what=markupsafe.escape(_what(booking)),
        due=markupsafe.escape(due),
        days=_late_days(booking.ends_at, now),
    )
    sent = await core_api.email.send_async(
        booking.borrower_email or '',
        labels['late_subject'],
        _html(lang, labels['late_heading'], body, booking.borrower_name),
        organization_id=booking.organization_id,
    )
    if sent:
        booking.late_reminder_sent_on = now.astimezone(tz).date()
    return sent


async def _timezone(db: AsyncSession, org_id: UUID):
    return await core_api.organizations.timezone_async(db, org_id)


async def _outstanding_bookings(
    db: AsyncSession, org_id: UUID, condition
) -> list[RentalBooking]:
    return list(
        (
            await db.execute(
                select(RentalBooking)
                .options(
                    selectinload(RentalBooking.lines).selectinload(
                        RentalBookingLine.units
                    )
                )
                .where(
                    RentalBooking.organization_id == org_id,
                    RentalBooking.status == 'PICKED_UP',
                    RentalBooking.borrower_email.is_not(None),
                    condition,
                )
            )
        )
        .unique()
        .scalars()
        .all()
    )


async def check_organization_reminders(
    db: AsyncSession, org_id: UUID, now: datetime | None = None
) -> tuple[int, int]:
    """Send what this organization owes now; answer (end, late) counts."""
    now = now or datetime.now(UTC)
    if not await core_api.email.can_send_async(db, org_id):
        return 0, 0
    tz = await core_api.organizations.timezone_async(db, org_id)
    local_today = now.astimezone(tz).date()

    due_end = await _outstanding_bookings(
        db,
        org_id,
        and_(
            RentalBooking.ends_at > now,
            RentalBooking.ends_at <= now + REMINDER_WINDOW,
            RentalBooking.end_reminder_sent_at.is_(None),
        ),
    )
    late = await _outstanding_bookings(
        db,
        org_id,
        and_(
            RentalBooking.ends_at < now,
            or_(
                RentalBooking.late_reminder_sent_on.is_(None),
                RentalBooking.late_reminder_sent_on != local_today,
            ),
        ),
    )
    end_sent = 0
    late_sent = 0
    for booking in due_end:
        try:
            if await _send_end_reminder(db, booking, now):
                end_sent += 1
        except Exception:
            logger.exception('[rentals] end reminder failed for %s', booking.id)
    for booking in late:
        try:
            if await _send_late_reminder(db, booking, now):
                late_sent += 1
        except Exception:
            logger.exception('[rentals] late reminder failed for %s', booking.id)
    await db.flush()
    return end_sent, late_sent


async def run_rental_reminder_check_async(db: AsyncSession) -> None:
    """The scheduled pass: every organization that has the module enabled."""
    now = datetime.now(UTC)
    organizations = await core_api.organizations.list_all_async(db)
    for organization in organizations:
        if not await core_api.organizations.is_module_enabled_async(
            db, organization.id, 'rentals'
        ):
            continue
        try:
            end_sent, late_sent = await check_organization_reminders(
                db, organization.id, now
            )
            if end_sent or late_sent:
                logger.info(
                    '[rentals] reminders for %s: %d ending, %d late',
                    organization.id,
                    end_sent,
                    late_sent,
                )
        except Exception:
            logger.exception('[rentals] reminder pass failed for %s', organization.id)
    await db.flush()
