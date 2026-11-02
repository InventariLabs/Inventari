"""
One-time migration for webhook module settings.

Moves ``org.settings['webhooks']`` (legacy flat key) into the
namespaced ``org.settings['module:webhooks']`` so the new
``core_api.settings.get_async(db, org_id, 'webhooks')`` API path
returns the values that operators configured before P1.4.

Idempotent — if the namespaced key already exists with values, the
flat key is left alone (the operator's current settings win).
"""

from __future__ import annotations

import copy
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_LEGACY_KEY = 'webhooks'
_NAMESPACED_KEY = 'module:webhooks'


def migrate_webhooks_settings(
    settings: dict[str, Any], organization_id: UUID | None = None
) -> dict[str, Any] | None:
    """Return settings with the legacy ``webhooks`` key merged into ``module:webhooks``.

    Pure transform on the *stored* settings dict (sensitive leaves stay in
    their stored/encrypted form — the copied values are never decrypted).
    Returns ``None`` when nothing needs migrating (idempotent).
    """
    legacy = settings.get(_LEGACY_KEY)
    if not isinstance(legacy, dict) or not legacy:
        return None
    if isinstance(settings.get(_NAMESPACED_KEY), dict) and settings[_NAMESPACED_KEY]:
        logger.debug(
            'Org %s already has module:webhooks — skipping flat-key migration',
            organization_id,
        )
        return None

    new_settings = copy.deepcopy(settings)
    new_settings[_NAMESPACED_KEY] = {
        **new_settings.get(_NAMESPACED_KEY, {}),
        **legacy,
    }
    logger.info(
        'Org %s: migrated %d legacy webhooks setting(s) to %s namespace',
        organization_id,
        len(legacy),
        _NAMESPACED_KEY,
    )
    return new_settings


async def migrate_all_orgs_webhooks_settings_async(db: AsyncSession) -> int:
    """Iterate every org and apply :func:`migrate_webhooks_settings`.

    Returns the count of orgs migrated. Safe to call multiple times.
    """
    from app.core.public_api import core_api

    migrated = 0
    orgs = await core_api.organizations.list_all_async(db)
    for org_dto in orgs:
        new_settings = migrate_webhooks_settings(org_dto.settings or {}, org_dto.id)
        if new_settings is None:
            continue
        await core_api.organizations.update_async(db, org_dto.id, settings=new_settings)
        migrated += 1
    if migrated:
        await db.commit()
    return migrated
