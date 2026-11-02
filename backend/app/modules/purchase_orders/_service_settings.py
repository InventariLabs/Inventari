"""PO settings service — per-org approval configuration (POSettings).

Writes use ``db.flush()`` only (no commit) — the caller commits.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import POSettings


async def get_po_settings(
    db: AsyncSession,
    org_id: UUID,
) -> POSettings | None:
    """Return the org's PO settings row, or ``None`` if never created."""
    settings = await db.scalar(
        select(POSettings).where(POSettings.organization_id == org_id)
    )
    if not isinstance(settings, POSettings):
        return None
    return settings


async def get_or_create_po_settings(
    db: AsyncSession,
    org_id: UUID,
) -> POSettings:
    """Return the org's PO settings, creating a defaults row if absent.

    Defaults: no approval threshold, no forced approval.
    """
    settings = await get_po_settings(db, org_id)
    if settings is None:
        settings = POSettings(organization_id=org_id)
        db.add(settings)
        await db.flush()
        await db.refresh(settings)
    return settings


class _Unset:
    """Sentinel for "the payload did not name this field".

    ``None`` is a real answer here — an emptied threshold field means "no
    threshold", which is a state the organization must be able to return
    to. Reading that ``None`` as "leave unchanged" made the threshold
    un-removable once set.
    """


UNSET: Final = _Unset()


async def upsert_po_settings(
    db: AsyncSession,
    org_id: UUID,
    *,
    approval_threshold: Decimal | None | _Unset = UNSET,
    approval_required: bool | None = None,
) -> POSettings:
    """Get-or-create the org's PO settings and apply the given fields.

    The threshold answers three ways: absent (``UNSET`` — leave as is),
    present and ``None`` (clear it — no threshold), present with a value
    (set it; 0.00 names a threshold and is not the cleared state).
    ``approval_required`` keeps its old two-way reading: ``None`` leaves
    it unchanged.
    """
    settings = await get_or_create_po_settings(db, org_id)
    if not isinstance(approval_threshold, _Unset):
        settings.approval_threshold = approval_threshold
    if approval_required is not None:
        settings.approval_required = approval_required
    await db.flush()
    await db.refresh(settings)
    return settings
