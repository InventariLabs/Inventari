"""Where a module's settings live inside ``organization.settings``.

Each module owns one namespaced key (``module:<name>``) of the organization's
settings blob, and core's own jobs keep theirs under ``module:core``. The
public ``core_api.settings`` namespace adds what a caller outside Core needs on
top — the module-identity check, secret masking and decryption — and leaves
the plain read and write of the blob to this module, so a core service can use
them without going back through the facade meant for modules.
"""

from __future__ import annotations

import copy
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.settings_validator import SCHEMA_VERSION_KEY, settings_schema_version
from app.services._org_reads import get_by_id_async

logger = get_logger(__name__)

#: Namespace prefix used for all module settings keys.
NAMESPACE_PREFIX = 'module'


def namespace(module_name: str) -> str:
    return f'{NAMESPACE_PREFIX}:{module_name}'


def schema_version_for(module_name: str) -> int:
    """The settings-schema version *module_name* declares, default 1.

    A module that is missing or whose schema refuses to load reads as the base
    version — a broken module must not stop settings from being written.
    """
    try:
        from app.core.module_registry import module_registry
    except ImportError:
        return 1
    instance = module_registry.get(module_name)
    if instance is None:
        return 1
    try:
        schema = instance.get_settings_schema()
    except Exception:  # a module's own code; logged, the version reads as 1
        logger.exception('Failed to load settings schema for %s', module_name)
        return 1
    return settings_schema_version(schema)


def without_stamp(module_settings: dict[str, Any]) -> dict[str, Any]:
    """The stored blob without core's schema-version stamp.

    Every read goes through here so the stamp never reaches a module or the
    frontend, and the per-organization pass hands ``migrate`` the module's
    data only.
    """
    if not module_settings or SCHEMA_VERSION_KEY not in module_settings:
        return module_settings
    return {
        key: value
        for key, value in module_settings.items()
        if key != SCHEMA_VERSION_KEY
    }


async def write_module_settings_async(
    db: AsyncSession,
    organization_id: UUID,
    module_name: str,
    values: dict[str, Any],
) -> None:
    """Shallow-merge *values* into the module's namespace and flush.

    The stored blob is stamped with the version of the settings schema it was
    written against, so a later shape change can tell what each organization
    actually saved. The caller owns the transaction.
    """
    org = await get_by_id_async(db, organization_id)
    if not org:
        raise ServiceRejectionError('organization_not_found')

    settings = copy.deepcopy(org.settings or {})
    ns = namespace(module_name)
    if ns not in settings:
        settings[ns] = {}
    settings[ns].update(values)
    # The stamp is core's metadata about the blob, not module data: written
    # last so it always records the shape this write produced, whatever the
    # caller passed in.
    settings[ns][SCHEMA_VERSION_KEY] = schema_version_for(module_name)
    org.settings = settings
    await db.flush()


async def read_module_setting_async(
    db: AsyncSession,
    organization_id: UUID,
    module_name: str,
    key: str,
    default: Any = None,
) -> Any:
    """One top-level value of the module's namespace, exactly as stored.

    Not masked: this is for core's own namespace, where nothing is a secret.
    A module's settings, secrets included, are read through
    ``core_api.settings``, which masks them.
    """
    org = await get_by_id_async(db, organization_id)
    if not org or not org.settings:
        return default
    module_settings = without_stamp(org.settings.get(namespace(module_name), {}))
    value = module_settings.get(key)
    return default if value is None else value
