from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.api_key_auth import (
    ApiKeyIdentity,
    register_api_key_resolver,
    register_issued_api_keys,
)
from app.core.define_module import define_module

from .api_key_service import issued_key_check_async
from .router import router


async def _resolve_api_key(db: AsyncSession, raw_key: str) -> ApiKeyIdentity | None:
    """Resolve a raw API key for Core authentication.

    Hands back the owner's id, the key's prefix and what the key may do —
    what Core needs to authenticate the request, act with the key's rights
    and record which key made it — and keeps the ApiKey ORM object on this
    side of the boundary so it never becomes an implicit contract.
    """
    from .api_key_service import validate_api_key

    # The key is checked in a session of its own, on the request session's
    # engine, and committed there. Refusing a key can revoke it (its owner left
    # the organization), and the 401 that follows rolls the request's session
    # back — the revocation has to outlast it without this function committing
    # a session it was only lent. The row lock the check takes goes with that
    # commit too, instead of holding every other request on the same key until
    # this one ends. Authentication runs before the request session has
    # queried anything, so the two never hold a pooled connection at once.
    bind = db.bind
    if not isinstance(bind, AsyncEngine):
        raise RuntimeError(
            'the request session is not engine-bound, so an API key cannot '
            'be checked in a session of its own'
        )
    async with async_sessionmaker(bind=bind, expire_on_commit=False)() as own_db:
        api_key = await validate_api_key(own_db, raw_key)
        await own_db.commit()
    if api_key is None:
        return None
    # SQLAlchemy types these attributes as Column[...]; at runtime they are
    # the values.
    return ApiKeyIdentity(
        user_id=cast('UUID', api_key.user_id),
        key_prefix=cast('str', api_key.key_prefix),
        permissions=frozenset(cast('list[str]', api_key.permissions)),
        scopes=tuple(cast('list[str]', api_key.scope_names)),
    )


# Registered at import, not from a startup hook: authentication runs on the
# very first request, which can precede per-module startup hooks.
register_api_key_resolver(_resolve_api_key)
register_issued_api_keys(issued_key_check_async)

module = define_module(router=router)
