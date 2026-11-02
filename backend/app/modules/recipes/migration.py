"""
One-time migration for the recipes reader key.

The key's homes, newest first:

- the AI Connections registry — a ``jina`` connection bound to
  ``recipes.url_fetch``. Since 2026-09-28 a credential
  for an external provider lives where the administrator rotates and
  tests it, not on the screen a cook opens.
- ``module:recipes.jina.api_key`` — the module-settings schema home the
  registry replaces.
- ``modules.recipes.jina.api_key`` — the legacy plaintext path predating
  the schema, written straight through ``PATCH /organizations``.

This migrator moves a value found in either older home into the registry
— binding the organization's existing reader connection when one already
serves, creating one otherwise — and always deletes the older subtrees:
a value already living in the registry is a reason to drop the stale
copies, not to keep them. Idempotent: with nothing in the old homes and
a binding present, there is nothing to do.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_LEGACY_PLAIN_PATH = ('modules', 'recipes', 'jina', 'api_key')
_NAMESPACED_KEY = 'module:recipes'
_NAMESPACED_PATH = ('jina', 'api_key')
_PURPOSE_KEY = 'recipes.url_fetch'


async def migrate_all_orgs_recipes_jina_key_async(db: AsyncSession) -> int:
    """Move every organization's reader key into the connections registry.

    Owns its transaction (startup migrator, no request scope — see the
    transaction-owner allowlist): one commit for the whole sweep, so a
    failure re-runs cleanly from the homes that still hold a key.
    """
    from app.core.public_api import core_api

    migrated = 0
    orgs = await core_api.organizations.list_all_async(db)
    for org_dto in orgs:
        if await _migrate_org_async(db, org_dto.id, org_dto.settings or {}):
            migrated += 1
    if migrated:
        await db.commit()
    return migrated


async def _migrate_org_async(
    db: AsyncSession, org_id: UUID, settings: dict[str, Any]
) -> bool:
    """One organization: move the key, drop the old homes. True when changed."""
    import copy

    from app.core.public_api import core_api

    namespaced = _read_path(settings, (_NAMESPACED_KEY, *_NAMESPACED_PATH))
    legacy_plain = _read_path(settings, _LEGACY_PLAIN_PATH)
    if not namespaced and not legacy_plain:
        return False

    # The key is decrypted through the settings door the schema owned —
    # the one read path that already speaks both its stored shapes.
    plaintext = None
    if namespaced:
        plaintext = await core_api.settings.get_decrypted_async(
            db, org_id, 'recipes', 'jina.api_key'
        )
    elif legacy_plain:
        plaintext = legacy_plain

    # Deep copy: nested dicts are shared with the ORM-tracked value, and
    # the single write below has to compare unequal to what it replaced —
    # a shallow copy that mutates them in place records no change.
    new_settings = copy.deepcopy(settings)
    _drop_path(new_settings, (_NAMESPACED_KEY, 'jina'))
    _drop_path(new_settings, _LEGACY_PLAIN_PATH[:-1])

    # The binding is written into the same dict and persisted by the same
    # call as the dropped homes: a second write that re-reads settings
    # would race this one and erase it.
    if plaintext:
        bound_id = await _ensure_reader_connection_async(db, org_id, plaintext)
        if bound_id is not None:
            defaults = new_settings.setdefault('ai', {}).setdefault('defaults', {})
            defaults[_PURPOSE_KEY] = str(bound_id)

    await core_api.organizations.update_async(db, org_id, settings=new_settings)
    logger.info('Org %s: reader key moved to the connections registry', org_id)
    return True


async def _ensure_reader_connection_async(
    db: AsyncSession, org_id: UUID, plaintext: str
) -> UUID | None:
    """The org's reader connection — the serving one when it exists, a new
    row carrying the key otherwise.

    The connection is created through CoreAPI like every other write to a
    core table; the name is what the registry screen shows. A failure
    propagates: the org's old homes are dropped only after this returns,
    so a failed sweep leaves the key where the next start can retry from.
    """
    from app.core.contracts import AiConnectionCreateDTO
    from app.core.public_api import core_api

    for conn in await core_api.ai_connections.list_async(db, org_id):
        if conn.provider == 'jina' and 'url_fetch' in conn.capabilities:
            return conn.id

    conn = await core_api.ai_connections.create_async(
        db,
        org_id,
        AiConnectionCreateDTO(
            name='Jina Reader',
            provider='jina',
            api_key=plaintext,
            capabilities=['url_fetch'],
        ),
    )
    return conn.id


def _read_path(data: dict[str, object], path: tuple[str, ...]) -> str | None:
    cur: object = data
    for segment in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(segment)
        if cur is None:
            return None
    return cur if isinstance(cur, str) else None


def _drop_path(data: dict[str, object], path: tuple[str, ...]) -> None:
    """Remove the leaf at *path*, leaving the parent dicts in place."""
    cur: object = data
    for segment in path[:-1]:
        if not isinstance(cur, dict):
            return
        cur = cur.get(segment)
    if isinstance(cur, dict):
        cur.pop(path[-1], None)
