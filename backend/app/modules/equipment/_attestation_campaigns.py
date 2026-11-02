# module_writes: AttestationCampaign, AttestationResponse (module-local tables)
"""Campaign CRUD + launch + reminders.

Module-local table writes (AttestationCampaign, AttestationResponse) are
allowed by default per the architecture linter.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.exceptions import ConflictException, ServiceRejectionError
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_module_error_message
from app.modules.equipment._attestation_email import (
    _build_email_html,
    _get_email_label,
)
from app.modules.equipment.models import (
    AuditCampaign,
    AuditResponse,
    AuditResponseItem,
    EquipmentAssignment,
)

from ._org_day import pin_org_day_end
from ._serial import serial_of

logger = get_logger(__name__)

_TOKEN_BYTES = 64
_DEFAULT_TOKEN_TTL_DAYS = 30


def _campaign_snapshot(campaign: AuditCampaign) -> dict[str, Any]:
    """A campaign as the organization log names it."""
    return {
        'name': campaign.name,
        'scope_type': campaign.scope_type,
        'deadline': campaign.deadline.isoformat() if campaign.deadline else None,
        'status': campaign.status,
    }


async def _log_campaign_async(
    db: AsyncSession,
    campaign: AuditCampaign,
    *,
    org_id: UUID,
    user_id: UUID | None,
    action: AuditAction,
    snapshot: dict[str, Any] | None = None,
) -> None:
    """Record what was done to a campaign.

    An attestation asks every holder to confirm they still have what the
    register says they have, so launching one puts a question to the whole
    organization and cancelling one voids every link already in somebody's
    inbox. Both were acts nothing outside this module could see.
    """
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=action,
        target_type=AuditTargetType.EQUIPMENT_ATTESTATION,
        target_id=campaign.id,
        snapshot=snapshot if snapshot is not None else _campaign_snapshot(campaign),
    )


async def create_campaign(
    db: AsyncSession,
    data: Any,
    org_id: UUID,
    user_id: UUID,
) -> AuditCampaign:
    # a deadline is a day, not a moment — the scheduler counts
    # `(deadline - now).days`, the e-mail prints `%Y-%m-%d`, and nobody ever
    # shows the clock half. A client that sends midnight ("end of day D" read
    # as "start of day D") would expire every token the moment day D begins.
    # The service pins the contract: store the end of the deadline's own day,
    # in the deadline's own timezone. "Own timezone" is the organization's,
    # so the incoming instant is read through its clock first — .replace() on
    # the UTC-normalized value pinned 23:59:59 onto UTC and moved the
    # deadline into the next calendar day for everyone east of Greenwich.
    from datetime import datetime

    tz = await core_api.organizations.timezone_async(db, org_id)
    deadline = pin_org_day_end(data.deadline, tz)
    # The future test belongs after the re-pin, against the org's clock: the
    # arrival is noon of the picked day, and comparing that instant with
    # "now" refused a legitimately picked "today" for the whole afternoon of
    # the organization's day. The stored value is the day's own end — it is
    # in the future exactly while the picked day is not over for this org.
    if deadline <= datetime.now(UTC):
        raise ServiceRejectionError('campaign_deadline_past')
    campaign = AuditCampaign(
        organization_id=org_id,
        name=data.name,
        description=data.description,
        scope_type=data.scope_type,
        scope_filter_id=data.scope_filter_id,
        deadline=deadline,
        reminder_days_before=data.reminder_days_before,
        email_subject=data.email_subject,
        email_body=data.email_body,
        created_by=user_id,
    )
    db.add(campaign)
    await db.flush()
    await _log_campaign_async(
        db, campaign, org_id=org_id, user_id=user_id, action=AuditAction.CREATE
    )
    await db.flush()
    await db.refresh(campaign)
    return campaign


async def _get_campaign(
    db: AsyncSession, campaign_id: UUID, org_id: UUID
) -> AuditCampaign | None:
    result = await db.execute(
        select(AuditCampaign).where(
            AuditCampaign.id == campaign_id,
            AuditCampaign.organization_id == org_id,
        )
    )
    return result.scalars().first()


async def list_campaigns(db: AsyncSession, org_id: UUID) -> list[AuditCampaign]:
    result = await db.execute(
        select(AuditCampaign)
        .where(AuditCampaign.organization_id == org_id)
        .order_by(AuditCampaign.created_at.desc())
    )
    return list(result.scalars().all())


async def get_campaign(
    db: AsyncSession, campaign_id: UUID, org_id: UUID
) -> AuditCampaign | None:
    return await _get_campaign(db, campaign_id, org_id)


def _calc_stats(responses: list[AuditResponse]) -> dict[str, Any]:
    total = len(responses)
    confirmed = sum(1 for r in responses if r.status == 'CONFIRMED')
    disputed = sum(1 for r in responses if r.status == 'DISPUTED')
    # A response nobody answered because the assets came back first is
    # closed, not pending: counting it as waiting kept the campaign short
    # of 100% forever and put the person back on the reminder list.
    returned = sum(1 for r in responses if r.status == 'PENDING' and r.assets_returned)
    pending = sum(1 for r in responses if r.status == 'PENDING') - returned
    expired = sum(1 for r in responses if r.status == 'EXPIRED')
    return {
        'total': total,
        'confirmed': confirmed,
        'disputed': disputed,
        'pending': pending,
        'expired': expired,
        'returned': returned,
    }


async def get_campaign_detail(
    db: AsyncSession, campaign_id: UUID, org_id: UUID
) -> tuple[AuditCampaign, dict[str, Any]] | None:
    campaign = await _get_campaign(db, campaign_id, org_id)
    if not campaign:
        return None
    _ = campaign.responses
    stats = _calc_stats(campaign.responses)
    return campaign, stats


_SCOPE_FETCH_LIMIT = 10000


async def _scope_item_ids(
    db: AsyncSession,
    organization_id: UUID,
    scope_type: str,
    scope_filter_id: UUID | None,
) -> list[UUID]:
    """Resolve all item IDs in a scope via CoreAPI.

    Fails loud if the scope exceeds ``_SCOPE_FETCH_LIMIT`` items to avoid
    silent truncation of attestation campaigns for very large storage
    locations / categories.
    """
    if scope_type == 'STORAGE':
        items = await core_api.items.list_async(
            db,
            organization_id,
            storage_location_id=scope_filter_id,
            limit=_SCOPE_FETCH_LIMIT,
        )
    elif scope_type == 'CATEGORY':
        items = await core_api.items.list_async(
            db,
            organization_id,
            category_id=scope_filter_id,
            limit=_SCOPE_FETCH_LIMIT,
        )
    else:
        items = []
    if len(items) >= _SCOPE_FETCH_LIMIT:
        raise ServiceRejectionError(
            'attestation_scope_exceeds_limit', limit=_SCOPE_FETCH_LIMIT
        )
    return [item.id for item in items]


async def _active_assignments_query(
    db: AsyncSession,
    organization_id: UUID,
    scope_type: str,
    scope_filter_id: UUID | None,
) -> Any:
    q = select(EquipmentAssignment).where(
        EquipmentAssignment.organization_id == organization_id,
        EquipmentAssignment.checked_in_at.is_(None),
    )
    if scope_type in ('STORAGE', 'CATEGORY'):
        item_ids = await _scope_item_ids(
            db, organization_id, scope_type, scope_filter_id
        )
        if not item_ids:
            return q.where(false())
        q = q.where(EquipmentAssignment.item_id.in_(item_ids))
    return q


async def _build_active_assignments_query(
    db: AsyncSession, campaign: AuditCampaign
) -> Any:
    return await _active_assignments_query(
        db, campaign.organization_id, campaign.scope_type, campaign.scope_filter_id
    )


async def scope_preview_async(
    db: AsyncSession,
    organization_id: UUID,
    scope_type: str,
    scope_filter_id: UUID | None = None,
) -> dict[str, Any]:
    """How much work a scope holds, before anybody commits to it.

    The creation screen offered "Wszystkie zasoby" without saying how many
    that is, and the confirmation offered an irreversible send without saying
    to how many people — so the first honest number arrived with the refusal
    that followed the click. A scope that covers nobody is the case worth
    knowing about early: the reader has to assign the equipment first, and
    telling them after they have walked through the irreversible gate sends
    them to a screen they now have to find.
    """
    result = await db.execute(
        await _active_assignments_query(
            db, organization_id, scope_type, scope_filter_id
        )
    )
    assignments = list(result.scalars().all())
    emails = {
        a.assigned_to_email.strip().lower()
        for a in assignments
        if a.assigned_to_email and a.assigned_to_email.strip()
    }
    return {
        'assets': len(assignments),
        'people': len(emails),
        'without_email': sum(
            1 for a in assignments if not (a.assigned_to_email or '').strip()
        ),
        'holders': sorted(
            {
                a.assigned_to_name.strip()
                for a in assignments
                if a.assigned_to_name.strip()
            },
            key=str.casefold,
        ),
    }


def _serial_of_assignment(assignment: EquipmentAssignment) -> str | None:
    item = assignment.item
    return serial_of(item) if item is not None else None


def _group_by_person(
    assignments: list[EquipmentAssignment],
) -> tuple[dict[str, list[EquipmentAssignment]], list[str], int]:
    """One envelope per person (by case-insensitive e-mail), one item row per
    asset — and who could not be asked at all, by name: a count alone left
    the person who launched it with nobody to go and ask in person."""
    grouped: dict[str, list[EquipmentAssignment]] = {}
    skipped_people: list[str] = []
    skipped_no_email = 0
    for assignment in assignments:
        if not assignment.assigned_to_email:
            skipped_no_email += 1
            name = (assignment.assigned_to_name or '').strip()
            if name and name not in skipped_people:
                skipped_people.append(name)
            continue
        grouped.setdefault(assignment.assigned_to_email.lower(), []).append(assignment)
    return grouped, skipped_people, skipped_no_email


async def launch_campaign(
    db: AsyncSession,
    campaign_id: UUID,
    org_id: UUID,
    frontend_url: str = 'http://localhost:5173',
    lang: str = 'en',
    *,
    user_id: UUID,
) -> dict[str, Any]:
    campaign = await _get_campaign(db, campaign_id, org_id)
    if not campaign:
        raise ServiceRejectionError('campaign_not_found')
    if campaign.status != 'DRAFT':
        raise ServiceRejectionError('attestation_not_draft', status=campaign.status)

    result = await db.execute(await _build_active_assignments_query(db, campaign))
    assignments = list(result.scalars().all())
    if not assignments:
        raise ServiceRejectionError('attestation_no_active_assignments')

    now = datetime.now(UTC)
    token_expires = max(campaign.deadline, now + timedelta(hours=1))

    email_subject = campaign.email_subject or _get_email_label(lang, 'subject')

    grouped, skipped_people, skipped_no_email = _group_by_person(assignments)

    # Without a mail server the links are still made — each person's can be
    # copied from the campaign page and handed over — but nothing is queued
    # that could never leave, and the answer says so.
    email_unavailable = not core_api.email.is_configured()

    created_count = 0
    email_sent = 0
    email_failed = 0

    # The invitation prints the deadline as a day — the organization's day,
    # not UTC's (see _build_email_html).
    deadline_tz = await core_api.organizations.timezone_async(db, org_id)

    for email_key, group in grouped.items():
        first = group[0]
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        response = AuditResponse(
            campaign_id=campaign.id,
            organization_id=org_id,
            assignment_id=None,
            # the grouping key is the lowercase email — store that
            # form so "my assets" style lookups stay consistent.
            assignee_email=email_key,
            assignee_name=first.assigned_to_name,
            token=token,
            token_expires_at=token_expires,
        )
        db.add(response)
        await db.flush()

        item_names: list[str] = []
        for assignment in group:
            item_name = getattr(assignment.item, 'name', '') or 'your assigned item'
            item_names.append(item_name)
            db.add(
                AuditResponseItem(
                    response_id=response.id,
                    assignment_id=assignment.id,
                    item_id=assignment.item_id,
                    item_name=item_name,
                    serial_number=_serial_of_assignment(assignment),
                    status='PENDING',
                )
            )
        await db.flush()

        attestation_url = f'{frontend_url.rstrip("/")}/public/attestation/{token}'

        html = _build_email_html(
            assignee_name=first.assigned_to_name,
            item_name=item_names[0],
            item_names=item_names,
            attestation_url=attestation_url,
            deadline=campaign.deadline,
            custom_body=campaign.email_body,
            lang=lang,
            deadline_tz=deadline_tz,
        )

        sent = not email_unavailable and await core_api.email.send_async(
            to_email=email_key,
            subject=email_subject,
            html_content=html,
            organization_id=org_id,
        )
        if sent:
            response.email_sent_at = now
            email_sent += 1
        elif not email_unavailable:
            logger.warning(
                '[attestation] Email delivery failed to %s (campaign %s)',
                first.assigned_to_email,
                campaign_id,
            )
            email_failed += 1

        created_count += 1

    campaign.status = 'ACTIVE'
    campaign.launched_at = now
    await _log_campaign_async(
        db,
        campaign,
        org_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        snapshot={
            **_campaign_snapshot(campaign),
            'old_status': 'DRAFT',
            'new_status': campaign.status,
            'responses_created': created_count,
            'emails_sent': email_sent,
            'skipped_no_email': skipped_no_email,
        },
    )
    await db.flush()

    return {
        'responses_created': created_count,
        'skipped_no_email': skipped_no_email,
        'skipped_people': skipped_people,
        'emails_sent': email_sent,
        'emails_failed': email_failed,
        'email_unavailable': email_unavailable,
    }


async def send_reminders(
    db: AsyncSession,
    campaign_id: UUID,
    org_id: UUID,
    frontend_url: str = 'http://localhost:5173',
    lang: str = 'en',
    *,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    """Chase the people who have not answered, and say what came of it.

    The answer carries the reason a run sent nothing — no mail server, nobody
    left to ask, everyone reminded within the day — because a bare zero left
    the person who pressed the button believing the people had been chased.
    """
    campaign = await _get_campaign(db, campaign_id, org_id)
    if not campaign:
        raise ServiceRejectionError('campaign_not_found')
    if campaign.status != 'ACTIVE':
        raise ServiceRejectionError('attestation_reminders_not_active')

    now = datetime.now(UTC)
    sent_count = 0
    reminded_recently = 0
    not_delivered = 0
    # The queue accepts a message whether or not anything can deliver it.
    email_unavailable = not core_api.email.is_configured()

    # Same clock as the invitation: the reminder prints the organization's
    # deadline day, not UTC's.
    deadline_tz = await core_api.organizations.timezone_async(db, org_id)

    awaiting = []
    for response in campaign.responses:
        if response.status != 'PENDING' or response.assets_returned:
            continue
        if response.token_expires_at < now:
            response.status = 'EXPIRED'
            continue
        awaiting.append(response)

    for response in awaiting:
        if response.reminder_sent_at and (now - response.reminder_sent_at) < timedelta(
            hours=24
        ):
            reminded_recently += 1
            continue
        if email_unavailable:
            continue

        attestation_url = (
            f'{frontend_url.rstrip("/")}/public/attestation/{response.token}'
        )
        item_names = [item.item_name for item in response.items]
        html = _build_email_html(
            assignee_name=response.assignee_name,
            item_name=item_names[0] if item_names else 'your assigned item',
            item_names=item_names,
            attestation_url=attestation_url,
            deadline=campaign.deadline,
            custom_body=None,
            lang=lang,
            deadline_tz=deadline_tz,
        )
        prefix = _get_email_label(lang, 'reminder_prefix')
        subject = (
            f'{prefix}{campaign.email_subject or _get_email_label(lang, "subject")}'
        )
        sent = await core_api.email.send_async(
            to_email=response.assignee_email,
            subject=subject,
            html_content=html,
            organization_id=org_id,
        )
        if sent:
            response.reminder_sent_at = now
            sent_count += 1
        else:
            not_delivered += 1

    campaign.last_reminder_sent_at = now
    # The scheduler chases people too, and nobody pressed a button for it —
    # ``user_id`` is None there, which the log renders as the system acting.
    await _log_campaign_async(
        db,
        campaign,
        org_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        snapshot={**_campaign_snapshot(campaign), 'reminders_sent': sent_count},
    )
    return {
        'reminders_sent': sent_count,
        'awaiting_reply': len(awaiting),
        'reminded_recently': reminded_recently,
        'not_delivered': not_delivered,
        'email_unavailable': email_unavailable,
    }


async def response_link_async(
    db: AsyncSession,
    campaign_id: UUID,
    response_id: UUID,
    org_id: UUID,
    frontend_url: str,
) -> str | None:
    """The public link of one response, for handing over in person.

    A person without an e-mail address, or an organization that sends no
    mail, gets no invitation; the warning used to say requests "will have to
    be delivered by hand" while no screen gave out the link to deliver.
    """
    result = await db.execute(
        select(AuditResponse).where(
            AuditResponse.id == response_id,
            AuditResponse.campaign_id == campaign_id,
            AuditResponse.organization_id == org_id,
        )
    )
    response = result.scalars().first()
    if response is None:
        return None
    return f'{frontend_url.rstrip("/")}/public/attestation/{response.token}'


async def complete_campaign(
    db: AsyncSession, campaign_id: UUID, org_id: UUID, *, user_id: UUID
) -> AuditCampaign:
    campaign = await _get_campaign(db, campaign_id, org_id)
    if not campaign:
        raise ServiceRejectionError('campaign_not_found')
    if campaign.status not in ('ACTIVE', 'DRAFT'):
        raise ServiceRejectionError(
            'attestation_complete_not_allowed', status=campaign.status
        )
    old_status = campaign.status
    campaign.status = 'COMPLETED'
    await _log_campaign_async(
        db,
        campaign,
        org_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        snapshot={
            **_campaign_snapshot(campaign),
            'old_status': old_status,
            'new_status': 'COMPLETED',
        },
    )
    await db.flush()
    await db.refresh(campaign)
    return campaign


async def delete_campaign(
    db: AsyncSession, campaign_id: UUID, org_id: UUID, *, user_id: UUID
) -> None:
    """Remove a campaign that never went out.

    Only a draft. Once launched there is something to preserve:
    ``audit_responses.campaign_id`` cascades, so deleting would take the
    confirmations with it — ``responded_at``, the address they came from, and
    every report of a missing or damaged unit. That is the only trace an
    attestation produces, and no mistake in a campaign's setup is worth it.
    Cancelling is the way out of a launched one.
    """
    campaign = await _get_campaign(db, campaign_id, org_id)
    if not campaign:
        raise ServiceRejectionError('campaign_not_found')
    if campaign.launched_at is not None:
        raise ConflictException(
            code='CAMPAIGN_ALREADY_LAUNCHED',
            message=get_module_error_message(
                'equipment', 'campaign_cannot_delete_launched'
            ),
            details={'lang': get_current_lang()},
        )
    await _log_campaign_async(
        db, campaign, org_id=org_id, user_id=user_id, action=AuditAction.HARD_DELETE
    )
    await db.delete(campaign)
    await db.flush()


async def cancel_campaign(
    db: AsyncSession, campaign_id: UUID, org_id: UUID, *, user_id: UUID
) -> AuditCampaign:
    """Call off a campaign that is out there, without erasing what came back.

    The status has been declared on the model since the beginning and nothing
    ever wrote it, while the response path has always refused a campaign that
    is not ACTIVE — so setting it is all that was missing, and it voids every
    link already in somebody's inbox the moment it is set.

    Distinct from completing: a campaign that was called off did not finish,
    and its stats should not be read as though it had.
    """
    campaign = await _get_campaign(db, campaign_id, org_id)
    if not campaign:
        raise ServiceRejectionError('campaign_not_found')
    if campaign.status in ('COMPLETED', 'CANCELLED'):
        raise ConflictException(
            code='CAMPAIGN_ALREADY_CLOSED',
            message=get_module_error_message(
                'equipment', f'campaign_already_{campaign.status.lower()}'
            ),
            details={'lang': get_current_lang()},
        )
    old_status = campaign.status
    campaign.status = 'CANCELLED'
    await _log_campaign_async(
        db,
        campaign,
        org_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        snapshot={
            **_campaign_snapshot(campaign),
            'old_status': old_status,
            'new_status': 'CANCELLED',
        },
    )
    await db.flush()
    await db.refresh(campaign)
    return campaign
