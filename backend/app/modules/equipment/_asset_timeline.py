"""The asset timeline, assembled where the data lives.

The tab used to stitch its events in the browser from three reads — the
item's row, its assignments, its maintenance logs — and the history the
register already keeps in ``item_history`` was not among the sources, so a
status change had no way to appear on it. The timeline is now one
server-side read whose spine is that history: ``STATUS_CHANGED`` rows become
timeline entries directly, and the item's own creation opens the list so
every entry rides one ordering. The handover and maintenance records still
come along for the details only they carry — who handed the asset over, who
signed a return off, what a repair cost — none of which a history row
preserves.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, tzinfo
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.public_api import core_api

from ._assets_service import get_asset_async
from ._holder import holder_of_parts
from ._schemas_equipment import AssetTimelineEvent, AssetTimelineResponse
from .status_machine import resolve_previous_status

logger = get_logger(__name__)

# The kind the register's history contributes. A CREATED row is not among
# them: the opening entry is built from the item row itself, so an asset
# whose history begins later still has a first card, and the card cannot
# double with a history row. The mapping names this one action; the query
# tuple below is the optimization, deliberately derived from it — widening
# the query must not widen what the mapping pretends to know.
_TIMELINE_ACTION = 'STATUS_CHANGED'
_TIMELINE_ACTIONS = (_TIMELINE_ACTION,)


def _moment(value: datetime | date, timezone: tzinfo) -> datetime:
    """A stamp every entry sorts by, compared on the same terms.

    A maintenance log's ``performed_at`` arrives as a DATE and stays one
    through the payload: a naive-midnight datetime would bury a same-day
    repair under every timestamped event of that day. A day is not a
    moment — it sorts as the whole of the day it names.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.combine(value, time.max, tzinfo=timezone).astimezone(UTC)


async def get_asset_timeline_async(
    db: AsyncSession,
    organization_id: UUID,
    item_id: UUID,
    limit: int = 200,
) -> AssetTimelineResponse:
    """Compose the asset's timeline: created, history, handovers, maintenance."""
    # Imported in the body: the assignment/maintenance services and
    # services.py form an import cycle that only holds together in the
    # order the router package happens to import them.
    from ._assignment_service import get_item_assignment_history
    from ._maintenance_service import get_item_logs

    # The timeline is part of the card, and the card outlives the archive:
    # a soft-deleted asset is still linked from history and still renders
    # with Restore/Purge, so its record of what happened must answer too.
    item = await get_asset_async(db, organization_id, item_id, include_archived=True)
    if item is None:
        from app.core.exceptions import NotFoundException
        from app.i18n.service import get_current_lang

        raise NotFoundException('item', get_current_lang())

    events: list[AssetTimelineEvent] = [
        AssetTimelineEvent(
            kind='created', id=f'created:{item.id}', date=item.created_at
        )
    ]

    history = await core_api.item_history.list_for_item_async(
        db,
        item_id,
        organization_id,
        limit=limit,
        # The filter rides in the query: a 200-row cut applied before it
        # would hand a heavily-handled asset a timeline missing the very
        # status changes the tab exists for.
        actions=_TIMELINE_ACTIONS,
    )
    skipped: dict[str, int] = {}
    for entry in history:
        # The filter is an optimization, not the definition: the mapping is
        # what decides what a row is, so a row whose action the timeline
        # cannot name is skipped rather than dressed as a status change
        # with empty transitions. Widening the filter — the next action
        # somebody adds — must not manufacture lying cards.
        if entry.action != _TIMELINE_ACTION:
            skipped[entry.action] = skipped.get(entry.action, 0) + 1
            continue
        changes = entry.changes or {}
        events.append(
            AssetTimelineEvent(
                kind='status_changed',
                id=f'status_changed:{entry.id}',
                date=entry.created_at,
                # A sentinel is not a state: history rows written when the
                # asset had no status carry UNKNOWN as the old status, and
                # handing it on makes a screen print a word the interface
                # cannot translate where the machine itself reads absence.
                old_status=resolve_previous_status(changes.get('old_status')),
                new_status=changes.get('new_status'),
            )
        )

    if skipped:
        # Right for the screen, but a skip nobody can see is how a new kind
        # would disappear unnoticed: the operator's log says which kinds
        # were left out and how many rows each.
        logger.warning(
            'asset timeline for item %s skipped history rows it cannot name: %s',
            item_id,
            skipped,
        )

    for assignment in await get_item_assignment_history(
        db, organization_id, item_id, limit=limit
    ):
        # One answer to "who or what held it" — the same one the list, the
        # overdue row and the export read. A deployment's card names the
        # place; ``holder_kind`` lets the interface say so.
        holder = holder_of_parts(
            partner_name=assignment.partner_name,
            assigned_to_name=assignment.assigned_to_name,
            checkout_location_name=assignment.checkout_location_name,
        )
        holder_name = holder.name if holder is not None else None
        holder_kind = holder.kind if holder is not None else None
        events.append(
            AssetTimelineEvent(
                kind='checkout',
                id=f'checkout:{assignment.id}',
                date=assignment.checked_out_at,
                holder_name=holder_name,
                holder_kind=holder_kind,
                holder_email=assignment.assigned_to_email,
                issued_by_name=assignment.checked_out_by_name,
                expected_return_at=assignment.expected_return_at,
                notes=assignment.checkout_notes,
            )
        )
        if assignment.checked_in_at is not None:
            events.append(
                AssetTimelineEvent(
                    kind='checkin',
                    id=f'checkin:{assignment.id}',
                    date=assignment.checked_in_at,
                    holder_name=holder_name,
                    holder_kind=holder_kind,
                    operator_name=assignment.checked_in_by_name,
                    condition=assignment.checkin_condition,
                    notes=assignment.checkin_notes,
                )
            )

    org_timezone = await core_api.organizations.timezone_async(db, organization_id)
    maintenance_moments: dict[str, datetime] = {}
    for log in await get_item_logs(db, organization_id, item_id, limit=limit):
        created = _moment(log.created_at, org_timezone)
        if created.astimezone(org_timezone).date() == log.performed_at:
            maintenance_moments[f'maintenance:{log.id}'] = created
        events.append(
            AssetTimelineEvent(
                kind='maintenance',
                id=f'maintenance:{log.id}',
                date=log.performed_at,
                maintenance_type=log.maintenance_type,
                title=log.title,
                cost=log.cost,
                currency=log.currency,
                description=log.description,
                next_maintenance_at=log.next_maintenance_at,
                actor=log.performed_by,
            )
        )

    # A problem the holder reported in an attestation belongs to the asset's
    # story: it used to live on the campaign's response and nowhere else.
    from ._attestation_responses import disputes_for_item_async

    for line, response, campaign_name in await disputes_for_item_async(
        db, organization_id, item_id, limit=limit
    ):
        events.append(
            AssetTimelineEvent(
                kind='attestation_disputed',
                id=f'attestation_disputed:{line.id}',
                date=line.responded_at or response.responded_at or response.created_at,
                holder_name=response.assignee_name,
                holder_email=response.assignee_email,
                title=campaign_name,
                condition=line.dispute_type,
                notes=line.dispute_reason,
            )
        )

    events.sort(
        key=lambda event: (
            maintenance_moments.get(event.id or '') or _moment(event.date, org_timezone)
        ),
        reverse=True,
    )
    return AssetTimelineResponse(events=events)
