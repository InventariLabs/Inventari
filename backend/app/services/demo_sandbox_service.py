"""The public demo's sandboxes: one organization per visitor, handed out from a pool.

On a demo instance (``INVENTARI_DEMO``) a visitor does not sign in to a shared
account. One click gives them an organization of their own, already seeded with
the demo data, and a temporary administrator account in it. Seeding one takes
several seconds (``docs/DEMO.md`` has the measurement) and runs code that opens
its own event loop, so it never runs inside a request: the ``demo-reset``
service seeds a few in advance (``manage.py demo fill-pool``) and a click only
takes one off the pool.

The pool lives in ``system_settings`` under one key, because nothing a visitor
can write reaches that table — an organization's own settings or its members
would let a hostile visitor put their spoiled copy back for the next one to
receive. The nightly reset drops the schema, and the key with it, so "claimed"
means claimed since the last reset: that count is what the daily cap limits.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services.audit_service import log_action_async

POOL_KEY = 'demo_sandbox_pool'


class SandboxPoolEmptyError(Exception):
    """Every seeded sandbox has been handed out; the next ones are being seeded."""


class SandboxCapReachedError(Exception):
    """The instance has handed out as many sandboxes as it will until the reset."""


@dataclass(frozen=True)
class PoolState:
    ready: int
    claimed: int


def _entries(value: dict[str, Any] | None, part: str) -> list[dict[str, str]]:
    return list((value or {}).get(part, []))


async def _pool_row(db: AsyncSession) -> SystemSetting:
    """The pool's row, locked for this transaction, created when missing."""
    row = await db.scalar(
        select(SystemSetting).where(SystemSetting.key == POOL_KEY).with_for_update()
    )
    if row is None:
        row = SystemSetting(key=POOL_KEY, value={'ready': [], 'claimed': []})
        db.add(row)
        await db.flush()
    return row


async def pool_state_async(db: AsyncSession) -> PoolState:
    value = await db.scalar(
        select(SystemSetting.value).where(SystemSetting.key == POOL_KEY)
    )
    return PoolState(
        ready=len(_entries(value, 'ready')), claimed=len(_entries(value, 'claimed'))
    )


async def add_to_pool_async(
    db: AsyncSession, organization_id: UUID, user_id: UUID
) -> None:
    """Offer a seeded organization and its administrator to the next visitor."""
    row = await _pool_row(db)
    ready = _entries(row.value, 'ready')
    ready.append({'organization_id': str(organization_id), 'user_id': str(user_id)})
    # A new dict, not an in-place edit: JSONB changes are detected by identity.
    row.value = {'ready': ready, 'claimed': _entries(row.value, 'claimed')}
    await db.flush()


async def claim_sandbox_async(
    db: AsyncSession, *, cap: int, preferred_language: str | None = None
) -> UUID:
    """Hand the oldest seeded sandbox to a visitor; return its administrator.

    The account stays inactive while it waits in the pool, so it cannot be
    signed in to before it is handed out; claiming it is what activates it.
    The row lock serialises two clicks arriving together, so neither the cap
    nor a sandbox is counted twice; it is held until the caller commits.
    """
    row = await _pool_row(db)
    ready = _entries(row.value, 'ready')
    claimed = _entries(row.value, 'claimed')
    if len(claimed) >= cap:
        raise SandboxCapReachedError
    if not ready:
        raise SandboxPoolEmptyError
    entry = ready.pop(0)
    user = await db.get(User, UUID(entry['user_id']))
    if user is None or user.organization_id is None:
        # The pool named an account that is gone; drop the entry, not the visitor.
        row.value = {'ready': ready, 'claimed': claimed}
        await db.flush()
        return await claim_sandbox_async(
            db, cap=cap, preferred_language=preferred_language
        )
    user.is_active = True
    if preferred_language is not None:
        user.preferred_language = preferred_language
    claimed.append({**entry, 'claimed_at': datetime.now(UTC).isoformat()})
    row.value = {'ready': ready, 'claimed': claimed}
    # The sandbox's own log opens with the visitor taking it.
    await log_action_async(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action=AuditAction.USE,
        target_type=AuditTargetType.ORGANIZATION,
        target_id=user.organization_id,
    )
    await db.flush()
    return user.id


async def is_claimed_sandbox_async(db: AsyncSession, user_id: UUID) -> bool:
    """Whether this account is a visitor's sandbox administrator, still standing.

    The way back into a sandbox is a cookie naming its administrator; it opens
    only an account the pool handed out, never the operator's or a stranger's.
    """
    value = await db.scalar(
        select(SystemSetting.value).where(SystemSetting.key == POOL_KEY)
    )
    if not any(e['user_id'] == str(user_id) for e in _entries(value, 'claimed')):
        return False
    user = await db.get(User, user_id)
    return user is not None and user.is_active
