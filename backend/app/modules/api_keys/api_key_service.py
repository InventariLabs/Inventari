"""Business logic for API key lifecycle management."""

import hashlib
import secrets
from collections.abc import Callable, Collection
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_key_auth import (
    api_key_permission_catalog,
    api_key_scope_permissions,
    api_key_scopes,
)
from app.core.contracts import (
    API_KEY_DEFAULT_PERMISSIONS,
    API_KEY_PREFIX,
    API_KEY_WITHHELD_PERMISSIONS,
)
from app.core.db_utils import acquire_advisory_lock
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.logging import get_logger
from app.core.module_sdk import paginate_async
from app.core.public_api import core_api
from app.i18n.service import get_current_lang
from app.modules.api_keys.models import ApiKey

logger = get_logger(__name__)

# Maximum number of active API keys per organisation (prevents abuse)
MAX_KEYS_PER_ORG = 10

# Debounce interval for last_used_at updates (seconds)
LAST_USED_DEBOUNCE_SECONDS = 300


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def permission_catalog_async(
    db: AsyncSession, organization_id: UUID
) -> list[dict[str, object]]:
    """Every permission a key in this organization could name, labelled.

    The system permissions and those of the modules the organization has
    switched on — the same catalogue the roles editor offers, so a key and a
    role name a permission alike.
    """
    catalog = api_key_permission_catalog()
    entries = list(cast(list[dict[str, Any]], catalog['system']))
    for group in cast(list[dict[str, Any]], catalog['modules']):
        if await core_api.organizations.is_module_enabled_async(
            db, organization_id, group['module']
        ):
            entries.extend(group['permissions'])
    return [
        {
            'key': entry['key'],
            'label_key': entry['label_key'],
            'description_key': entry.get('description_key'),
        }
        for entry in entries
    ]


def resolve_key_permissions(
    *,
    grantable: Collection[str],
    permissions: Collection[str] | None,
    scopes: Collection[str],
) -> list[str]:
    """The permission list a new key gets, or ``ValueError`` saying why not.

    ``grantable`` is what the creator may hand on — their own permissions,
    minus the ones no key carries. A scoped key may hold only its scopes'
    permissions. Naming none takes the default: the scopes' permissions for a
    scoped key, ``API_KEY_DEFAULT_PERMISSIONS`` (read only) for an ordinary one — each limited to
    what the creator holds, so a default never refuses.
    """
    registered = api_key_scopes()
    for scope in scopes:
        if scope not in registered:
            raise ServiceRejectionError('api_key_scope_unknown', scope=scope)
    allowed = set(grantable) - {p.value for p in API_KEY_WITHHELD_PERMISSIONS}
    ceiling = api_key_scope_permissions(scopes) if scopes else None
    if permissions is None:
        default = (
            ceiling
            if ceiling is not None
            else {p.value for p in API_KEY_DEFAULT_PERMISSIONS}
        )
        return sorted(default & allowed)
    for permission in permissions:
        if permission not in allowed:
            raise ServiceRejectionError(
                'api_key_permission_not_grantable', permission=permission
            )
        if ceiling is not None and permission not in ceiling:
            raise ServiceRejectionError(
                'api_key_permission_outside_scope', permission=permission
            )
    return sorted(set(permissions))


async def create_api_key_async(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    name: str,
    *,
    permissions: Collection[str],
    expires_at: datetime | None = None,
    scopes: Collection[str] = (),
) -> tuple['ApiKey', str]:
    """Issue a key with an already resolved permission list.

    ``permissions`` comes from ``resolve_key_permissions``, which checks it
    against what the creator may grant; this function stores it.
    """
    # Advisory lock to prevent TOCTOU race on key limit
    await acquire_advisory_lock(db, f'api_keys:{organization_id}')

    result = await db.execute(
        select(func.count(ApiKey.id)).where(
            ApiKey.organization_id == organization_id,
            ApiKey.is_active.is_(True),  # noqa: E712
        )
    )
    active_count = result.scalar() or 0
    if active_count >= MAX_KEYS_PER_ORG:
        raise ServiceRejectionError('api_keys_limit_reached', count=MAX_KEYS_PER_ORG)

    raw_key = f'{API_KEY_PREFIX}{secrets.token_hex(16)}'
    hashed = _hash_key(raw_key)
    prefix = raw_key[:20]  # e.g. "inv_live_a1b2c3d4e5f"

    api_key = ApiKey(
        organization_id=organization_id,
        user_id=user_id,
        name=name,
        hashed_key=hashed,
        key_prefix=prefix,
        expires_at=expires_at,
        permissions=list(permissions),
        scope_names=sorted(set(scopes)),
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)

    logger.info(
        'API key created: id=%s org=%s',
        api_key.id,
        organization_id,
    )
    return api_key, raw_key


async def _still_belongs_to_its_owner_async(
    db: AsyncSession, api_key: 'ApiKey', key_org_id: UUID
) -> bool:
    """True while the key's owner is still who and where the key was issued for.

    A key row names an organization *and* a user, but validation used the
    organization for one thing only — whether the module was enabled — and
    the request context was then built from the user's *current*
    organization. So a key issued in organization A kept working after its
    owner moved to organization B, and worked there as B; leaving an
    organization or being removed from one revoked nothing.

    A key that outlives its own membership is revoked outright rather than
    merely refused, so re-inviting the person later does not quietly bring
    their old credential back with them. The revocation is flushed; the
    request ends in a 401 that rolls its own session back, so the resolver
    checks keys in a session of its own and commits that
    (``module._resolve_api_key``).

    The credential-change marker is honoured here too. The JWT path has read
    it since the password-reset work; the key path had not, so a reset ended
    every session and left the machine credential answering.
    """
    from app.core.token_blacklist import token_blacklist

    # Scoped to the key's own organization: the profile comes back only while
    # its owner is still a member of it.
    owner = await core_api.users.get_async(db, key_org_id, cast(UUID, api_key.user_id))
    if owner is None:
        setattr(api_key, 'is_active', False)  # noqa: B010
        await db.flush()
        logger.warning(
            'API key %s revoked: its owner is no longer a member of org %s.',
            api_key.id,
            key_org_id,
        )
        return False

    created_at = cast(datetime, api_key.created_at)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    if await token_blacklist.is_issued_before_credential_change(
        str(api_key.user_id), created_at.timestamp()
    ):
        return False

    return True


async def issued_key_check_async(db: AsyncSession) -> Callable[[str], bool]:
    """A check telling an active key from any other raw value, in one query.

    What it passes may still be refused by :func:`validate_api_key` — expired,
    its owner gone — but nothing outside it can be accepted, which is all the
    rate limiter asks of it (``app.core.api_key_auth``).
    """
    result = await db.execute(
        select(ApiKey.hashed_key).where(ApiKey.is_active.is_(True))
    )
    hashes = frozenset(result.scalars())
    return lambda raw_key: _hash_key(raw_key) in hashes


async def validate_api_key(db: AsyncSession, raw_key: str) -> 'ApiKey | None':
    """Look up an API key by its raw value. Updates last_used_at with debounce.

    Returns the ApiKey ORM object or None if invalid/expired/revoked, or if the
    organization no longer has the module that issues keys.

    That last one is the point of the check below. The gate lived on the router
    alone, so switching the module off took away the screen for managing keys
    and left every issued key authenticating: an admin who suspected a leak
    reached for the largest lever visible to them and ended up unable to see the
    key, unable to revoke it, and unable to stop it. The purpose card promises
    the opposite — "existing keys stop working ... anything depending on a key
    must fail loudly, not quietly stop" — which is also what removing an app
    does everywhere else: the token dies with it.
    """
    hashed = _hash_key(raw_key)
    result = await db.execute(
        select(ApiKey)
        .where(
            ApiKey.hashed_key == hashed,
            ApiKey.is_active.is_(True),  # noqa: E712
        )
        .with_for_update()
    )
    api_key = result.scalars().first()
    if api_key is None:
        return None

    # The model predates ``Mapped[...]``, so the column types as Column[UUID]
    # even though every row carries a real one.
    key_org_id = cast(UUID, api_key.organization_id)
    if not await core_api.organizations.is_module_enabled_async(
        db, key_org_id, 'api_keys'
    ):
        return None

    if not await _still_belongs_to_its_owner_async(db, api_key, key_org_id):
        return None

    now = datetime.now(UTC)

    # Check expiry
    if api_key.expires_at is not None:
        expires = api_key.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if now > expires:
            return None

    # Debounced last_used_at update
    should_update = (
        api_key.last_used_at is None
        or (
            now
            - (
                api_key.last_used_at
                if api_key.last_used_at.tzinfo
                else api_key.last_used_at.replace(tzinfo=UTC)
            )
        ).total_seconds()
        > LAST_USED_DEBOUNCE_SECONDS
    )

    if should_update:
        setattr(api_key, 'last_used_at', now)  # noqa: B010
        await db.flush()

    return api_key


async def list_api_keys(
    db: AsyncSession, organization_id: UUID, offset: int = 0, limit: int = 50
) -> tuple[list['ApiKey'], int]:
    """One page of an organisation's active API keys and how many there are.

    Revoked keys are hidden from the UI. The id breaks a tie on the creation
    time, so a page boundary cannot repeat or drop a key.
    """
    return await paginate_async(
        db,
        select(ApiKey)
        .where(
            ApiKey.organization_id == organization_id,
            ApiKey.is_active.is_(True),  # noqa: E712
        )
        .order_by(ApiKey.created_at.desc(), ApiKey.id),
        limit=limit,
        offset=offset,
    )


async def revoke_api_key(
    db: AsyncSession, organization_id: UUID, key_id: UUID
) -> 'ApiKey':
    """Soft-delete an API key by setting is_active=False.

    Returns the revoked key so the caller can record what was revoked — the
    row leaves the list, so the audit entry is the only place its name
    survives.

    Raises ValueError if the key does not exist in the given organisation.
    """
    result = await db.execute(
        select(ApiKey)
        .where(
            ApiKey.id == key_id,
            ApiKey.organization_id == organization_id,
        )
        .with_for_update()
    )
    api_key = result.scalars().first()
    if api_key is None:
        raise NotFoundException('api_key', get_current_lang())

    setattr(api_key, 'is_active', False)  # noqa: B010
    await db.flush()
    logger.info('API key revoked: id=%s org=%s', key_id, organization_id)
    return api_key
