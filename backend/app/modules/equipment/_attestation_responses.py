"""Public token flow — confirm/dispute responses via signed token URL."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.public_api import core_api
from app.modules.equipment.models import (
    AuditCampaign,
    AuditResponse,
    AuditResponseItem,
)

from .schemas import AuditResponseSchema


async def get_response_by_token(db: AsyncSession, token: str) -> AuditResponse | None:
    result = await db.execute(select(AuditResponse).where(AuditResponse.token == token))
    return result.scalars().first()


async def _load_for_reading(db: AsyncSession, token: str) -> AuditResponse | None:
    """The response with everything its public view reads, loaded fresh.

    The view asks every item whether its asset came back; after a write the
    instances in the session may hold expired relationships, and an async
    session cannot lazy-load them on attribute access.
    """
    result = await db.execute(
        select(AuditResponse)
        .where(AuditResponse.token == token)
        .options(
            selectinload(AuditResponse.items).selectinload(
                AuditResponseItem.assignment
            ),
            selectinload(AuditResponse.assignment),
            selectinload(AuditResponse.campaign),
        )
        .execution_options(populate_existing=True)
    )
    return result.scalars().first()


def closure_reason(response: AuditResponse) -> str | None:
    """Why the link can no longer take an answer — or ``None`` while it can.

    The vocabulary the confirm/dispute refusals raise, answerable without
    raising: the public GET carries it so the page can say it before the
    click, and ``_guard_response`` raises it after. Read-only by design —
    a GET must not flip ``PENDING`` to ``EXPIRED`` behind the reader's
    back. Neither does a refused write: the refusal rolls the request back,
    so the flip belongs to the reminder scheduler and the reminder run.
    """
    now = datetime.now(UTC)
    if response.token_expires_at < now:
        return 'expired'

    # Closed only when everything it asks about is back. One returned laptop
    # used to close the whole envelope, and the holder could not confirm the
    # phone they still had: the link said "already returned" and the
    # response stayed unanswered for good.
    if response.assets_returned:
        return 'assignment_already_returned'

    if response.campaign and response.campaign.status != 'ACTIVE':
        return 'campaign_closed'

    return None


async def get_public_response(
    db: AsyncSession, token: str
) -> AuditResponseSchema | None:
    """The public view: the response plus its closure reason, if any."""
    response = await _load_for_reading(db, token)
    if response is None:
        return None
    view = AuditResponseSchema.model_validate(response)
    org_id = response.organization_id
    # The deadline is the end of a day on the organization's own clock; the
    # day is what the page prints, so it is read through that clock here
    # rather than through whatever zone the reader's browser happens to be in.
    tz = await core_api.organizations.timezone_async(db, org_id)
    return view.model_copy(
        update={
            'closed_reason': closure_reason(response),
            'organization_name': await core_api.organizations.get_name_async(
                db, org_id
            ),
            'deadline_day': response.campaign.deadline.astimezone(tz).date(),
        }
    )


async def _guard_response(db: AsyncSession, response: AuditResponse) -> None:
    """Raise ValueError for expired tokens, returned assets, closed campaigns."""
    reason = closure_reason(response)
    if reason:
        raise ValueError(reason)


async def confirm_response(
    db: AsyncSession,
    token: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuditResponse:
    response = await get_response_by_token(db, token)
    if not response:
        raise ValueError('not_found')

    await _guard_response(db, response)

    if response.status in ('CONFIRMED', 'DISPUTED'):
        return response

    response.response_ip = ip
    response.response_user_agent = user_agent
    # confirming the envelope confirms every item still out and unanswered at
    # once; one already returned is not the holder's to confirm, and one
    # already reported keeps its report.
    now = datetime.now(UTC)
    for item in response.items:
        if item.status == 'PENDING' and not item.returned:
            item.status = 'CONFIRMED'
            item.responded_at = now
    _settle(response, answered_without_items='CONFIRMED')
    await db.flush()
    await db.refresh(response)
    return response


def _settle(response: AuditResponse, answered_without_items: str) -> None:
    """Close the response once nothing it asks about is left to answer.

    One holder can confirm the assets they have and report the one that is
    wrong in the same visit, so a report on one of several assets leaves the
    response open for the rest. It settles when no item still out is
    unanswered: ``DISPUTED`` if any item was reported, ``CONFIRMED`` otherwise.
    A legacy envelope without items is settled by the answer itself.
    """
    if response.items:
        if any(i.status == 'PENDING' and not i.returned for i in response.items):
            return
        disputed = any(i.status == 'DISPUTED' for i in response.items)
        response.status = 'DISPUTED' if disputed else 'CONFIRMED'
    else:
        response.status = answered_without_items
    response.responded_at = datetime.now(UTC)


async def dispute_response(
    db: AsyncSession,
    token: str,
    dispute_type: str,
    reason: str,
    ip: str | None = None,
    user_agent: str | None = None,
    assignment_id: UUID | None = None,
) -> AuditResponse:
    response = await get_response_by_token(db, token)
    if not response:
        raise ValueError('not_found')

    await _guard_response(db, response)

    if response.status in ('CONFIRMED', 'DISPUTED'):
        return response

    # with several assets the dispute names one of them; with a
    # single item (or a legacy envelope) the whole response is the target.
    if assignment_id is not None:
        target = next(
            (item for item in response.items if item.assignment_id == assignment_id),
            None,
        )
        if target is None:
            raise ValueError('assignment_not_found')
        if target.returned:
            raise ValueError('assignment_already_returned')
        if target.status != 'PENDING':
            return response
    elif len(response.items) == 1:
        target = response.items[0]
    elif response.assignment_id is not None:
        target = None
    else:
        raise ValueError('assignment_required')

    response.response_ip = ip
    response.response_user_agent = user_agent
    if target is not None:
        target.status = 'DISPUTED'
        target.dispute_type = dispute_type
        target.dispute_reason = reason
        target.responded_at = datetime.now(UTC)
    # Envelope copies keep the legacy display contract (public page summary)
    # working without joining items. With several assets the note names the
    # one it is about, so a reader of the envelope alone is not left guessing.
    response.dispute_type = dispute_type
    response.dispute_reason = (
        f'{_asset_label(target)} — {reason}'
        if target is not None and len(response.items) > 1
        else reason
    )
    _settle(response, answered_without_items='DISPUTED')

    await db.flush()
    await _tell_the_admins(db, response, target, reason)
    await db.refresh(response)
    return response


def _asset_label(target: AuditResponseItem) -> str:
    """The asset as a note names it: three laptops can share one name."""
    if target.serial_number:
        return f'{target.item_name} ({target.serial_number})'
    return target.item_name


async def _tell_the_admins(
    db: AsyncSession,
    response: AuditResponse,
    target: AuditResponseItem | None,
    reason: str,
) -> None:
    """A reported problem reaches the people who can act on it.

    It used to be written on the response and nowhere else: nobody was told,
    and the asset's page said nothing. The administrators get a notification
    that opens the asset, whose timeline now carries the report.
    """
    from app.core.public_api import core_api

    from . import _notification_labels as labels

    item_id = target.item_id if target is not None else None
    item_name = target.item_name if target is not None else response.item_name
    campaign = response.campaign.name if response.campaign else ''
    notifications = await core_api.notifications.notify_org_admins_async(
        db,
        response.organization_id,
        title=core_api.notifications.localize(labels.DISPUTE_TITLE, item=item_name),
        content=core_api.notifications.localize(
            labels.DISPUTE_CONTENT,
            holder=response.assignee_name,
            campaign=campaign,
            item=item_name,
            reason=reason,
        ),
        notification_type='warning',
        link=f'/equipment/{item_id}'
        if item_id
        else f'/equipment/campaigns/{response.campaign_id}',
        meta_data={
            'type': 'equipment_attestation_dispute',
            'response_id': str(response.id),
            'item_id': str(item_id) if item_id else None,
        },
    )
    await core_api.notifications.publish_async(db, notifications)


def _answered_at() -> ColumnElement[datetime]:
    """When a reported asset was answered: its own time, else its envelope's
    (rows from before items were stamped)."""
    return func.coalesce(
        AuditResponseItem.responded_at,
        AuditResponse.responded_at,
        AuditResponse.created_at,
    )


async def disputes_for_item_async(
    db: AsyncSession, org_id: UUID, item_id: UUID, limit: int = 200
) -> list[tuple[AuditResponseItem, AuditResponse, str]]:
    """Every problem an attestation reported about this asset, newest first,
    with the response it came in and the campaign's name — the asset's
    timeline shows them."""
    result = await db.execute(
        select(AuditResponseItem, AuditResponse, AuditCampaign.name)
        .join(AuditResponse, AuditResponseItem.response_id == AuditResponse.id)
        .join(AuditCampaign, AuditResponse.campaign_id == AuditCampaign.id)
        .where(
            AuditResponse.organization_id == org_id,
            AuditResponseItem.item_id == item_id,
            AuditResponseItem.status == 'DISPUTED',
        )
        .order_by(_answered_at().desc())
        .limit(limit)
    )
    return [(row[0], row[1], row[2]) for row in result.all()]
