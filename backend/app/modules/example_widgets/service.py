"""Example Widgets — service layer.

What a module service is allowed to touch, demonstrated rather than
described. This file reaches its own table directly, which is what a module
may do with the tables it owns. It reads nothing from Core — and that is the
point worth copying: CoreAPI is the door to *other people's* data, not a
wrapper to route your own reads through. The moment this module needed a
product or a location, it would go through ``core_api`` and never through
``app.models``.

The one Core service it does call is the organization's journal: every
write leaves an entry, in the same transaction, naming who made it. A module
made by ``make new-module`` is a copy of this file, and the architecture gate
refuses a module whose writes journal nothing.

Every query is scoped by ``organization_id``. A module-local table is still
tenant data.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction
from app.core.public_api import core_api
from app.modules.example_widgets.models import Widget
from app.modules.example_widgets.schemas import WidgetCreate, WidgetUpdate

#: What the journal calls this module's records: the module's own name, so a
#: copy made by ``make new-module`` names its records after itself.
_JOURNAL_TARGET = 'example_widgets'


async def _journal(
    db: AsyncSession, widget: Widget, action: AuditAction, user_id: UUID | None
) -> None:
    await core_api.audit_log.log_action_async(
        db,
        organization_id=widget.organization_id,
        user_id=user_id,
        action=action,
        target_type=_JOURNAL_TARGET,
        target_id=widget.id,
        snapshot={
            'name': widget.name,
            'color': widget.color,
            'quantity': widget.quantity,
        },
    )


async def list_widgets(
    db: AsyncSession,
    organization_id: UUID,
    *,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Widget], int]:
    """One page of an organization's active widgets, and how many there are.

    The count is taken in the database, under the same filter as the page: a
    list a module owns can grow, and reading it whole to count it is the cost
    the pagination envelope exists to avoid.
    """
    active = (Widget.organization_id == organization_id, Widget.is_active.is_(True))
    total = await db.scalar(select(func.count()).select_from(Widget).where(*active))
    stmt = (
        select(Widget)
        .where(*active)
        .order_by(Widget.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total or 0


async def get_widget(
    db: AsyncSession,
    organization_id: UUID,
    widget_id: UUID,
) -> Widget | None:
    """Get a single widget by ID, scoped to organization."""
    stmt = select(Widget).where(
        Widget.id == widget_id,
        Widget.organization_id == organization_id,
        Widget.is_active.is_(True),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_widget(
    db: AsyncSession,
    organization_id: UUID,
    data: WidgetCreate,
    user_id: UUID | None,
) -> Widget:
    """Create a new widget."""
    widget = Widget(
        organization_id=organization_id,
        name=data.name,
        color=data.color,
        quantity=data.quantity,
    )
    db.add(widget)
    await db.flush()
    await _journal(db, widget, AuditAction.CREATE, user_id)
    return widget


async def update_widget(
    db: AsyncSession,
    organization_id: UUID,
    widget_id: UUID,
    data: WidgetUpdate,
    user_id: UUID | None,
) -> Widget | None:
    """Update an existing widget."""
    widget = await get_widget(db, organization_id, widget_id)
    if widget is None:
        return None

    if data.name is not None:
        widget.name = data.name
    if data.color is not None:
        widget.color = data.color
    if data.quantity is not None:
        widget.quantity = data.quantity

    await db.flush()
    # The flush expires ``updated_at``, which the database sets; read it back
    # here, because the response schema reading it later would be lazy IO the
    # async session refuses — every PATCH answered 400 until this line.
    await db.refresh(widget)
    await _journal(db, widget, AuditAction.UPDATE, user_id)
    return widget


async def delete_widget(
    db: AsyncSession,
    organization_id: UUID,
    widget_id: UUID,
    user_id: UUID | None,
) -> bool:
    """Soft-delete a widget."""
    widget = await get_widget(db, organization_id, widget_id)
    if widget is None:
        return False

    widget.is_active = False
    await db.flush()
    await _journal(db, widget, AuditAction.SOFT_DELETE, user_id)
    return True
