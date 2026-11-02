from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.async_utils import await_if_awaitable
from app.models.organization import Organization

#: Deferred Organization columns a reader must load before validating the
#: ORM row into a DTO — one list for every path that builds one (the
#: organizations API refresh, the identity context, the endpoints that
#: answer with the organization, this module's own eager loads). A name
#: missing here fails the request that reads it with a lazy-load crash
#: inside pydantic, so a new deferred column joins this list in the same
#: change. Lives in the service layer, next to the readers: the Public
#: API may import services but never models.
DEFERRED_DTO_COLUMNS: tuple[str, ...] = (
    'active_profile_id',
    'onboarding_completed',
    'print_page_size',
)


# Columns marked ``deferred`` on the model are excluded from the
# default column set; eager-load them here so DTO construction does not
# trigger one lazy SELECT per organization in list paths.
# NOTE: build the Load options at call time, not at module level — module-level
# construction forces configuration of ALL mappers at import time, before
# module models (e.g. StockTakeItem) are registered, which crashes app startup.
def _deferred_org_options() -> tuple:
    return (
        undefer(Organization.active_profile_id),
        undefer(Organization.onboarding_completed),
        undefer(Organization.print_page_size),
    )


async def get_by_id_async(db: AsyncSession, organization_id) -> Organization | None:
    """Get organization by id (async).

    The scalar is awaited only when it is awaitable, for the same reason
    ``is_module_enabled_async`` below does the same dance: the event bus
    hands a sync ``Session`` to subscribers written against this
    signature, and module settings reads (the circuit-breaker threshold
    rides one) go through here on that path.
    """
    result = await await_if_awaitable(
        db.scalar(select(Organization).where(Organization.id == organization_id))
    )
    return result


async def is_module_enabled_async(
    db: AsyncSession, organization_id, module_name: str
) -> bool:
    """Column-level module-enablement check (no full row load).

    Returns False for a missing organization. Logic shared with the ORM
    method via ``Organization.is_module_enabled_value``.

    The result is awaited only when it is awaitable: the event bus hands a sync
    ``Session`` to subscribers written against this signature — webhook dispatch
    already does the same dance for ``execute``, ``commit`` and ``flush`` — and
    a check whose answer decides whether an event leaves the installation has to
    work on both.
    """
    enabled_modules = await await_if_awaitable(
        db.scalar(
            select(Organization.enabled_modules).where(
                Organization.id == organization_id
            )
        )
    )
    if enabled_modules is None:
        return False
    return Organization.is_module_enabled_value(enabled_modules, module_name)


async def list_missing_short_id(db: AsyncSession) -> list[Organization]:
    result = await db.scalars(
        select(Organization)
        .options(*_deferred_org_options())
        .where(Organization.short_id.is_(None))
    )
    return list(result.all())


async def list_all_async(db: AsyncSession) -> list[Organization]:
    """Async: list all organizations (superadmin only)."""
    result = await db.scalars(select(Organization).options(*_deferred_org_options()))
    return list(result.all())


async def count(db: AsyncSession) -> int:
    result = await db.scalar(select(func.count(Organization.id)))
    return result or 0
