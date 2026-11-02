from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core._base_module import BaseModule
from app.core._module_declarations import (
    ALWAYS_ENABLED_MODULES,
    CORE_MODULES,
    CategoryDeclaration,
    LocalizedText,
    ModuleMetadata,
    StorageLocationDeclaration,
    StorageTypeDeclaration,
)
from app.core._require_module import require_module


async def is_module_enabled_async(
    db: AsyncSession, org_id: UUID, module_name: str
) -> bool:
    """Is *module_name* enabled for *org_id*?

    Exposed so cross-module APIs (e.g. ``shopping_lists_api``) can guard
    their writes against a disabled module without importing a private
    symbol. It reads the column, which is the same answer
    ``core_api.organizations`` gives — the two used to be one name over two
    freshnesses, and for a minute after a toggle a module was on or off
    depending on which of them an endpoint happened to call.

    ``_check_module_enabled`` keeps its cache, because it answers a
    different question: a per-request HTTP guard that would otherwise put a
    query in front of every routed call. Its cache is invalidated wherever
    the enabled set is written.
    """
    from app.services._org_reads import is_module_enabled_async as read_column

    return await read_column(db, org_id, module_name)


__all__ = [
    'CORE_MODULES',
    'ALWAYS_ENABLED_MODULES',
    'CategoryDeclaration',
    'LocalizedText',
    'StorageLocationDeclaration',
    'StorageTypeDeclaration',
    'ModuleMetadata',
    'BaseModule',
    'require_module',
    'is_module_enabled_async',
]
