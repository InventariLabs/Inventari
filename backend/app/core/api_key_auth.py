"""API-key resolution registry — inversion of the Core → api_keys dependency.

API keys are owned by the ``api_keys`` module: the table, the hashing, the
expiry and revocation rules, the last-used debounce. Core authentication still
has to accept them, but Core must not import a feature module.

The module registers its resolver here; Core asks who the key belongs to and
which key it is. Deliberately narrow: the registry hands back an
:class:`ApiKeyIdentity` — the owner's id and the key's prefix — rather than
letting a module ORM object cross the boundary, where it would become an
implicit contract. The prefix is the key's own name, and the journal needs it
for the one question the table cannot answer once a key is revoked: what did
this key do.

Absence is a no-op: with the module gone there are no API keys to honour, so
resolution returns ``None`` and the caller rejects the credential as invalid.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.core.limiter import record_api_key_verdict

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ApiKeyIdentity:
    """What Core authentication needs from a resolved key.

    ``key_prefix`` is the start of the raw key (``inv_live_`` and six characters,
    the same string the API Keys screen shows), never the key itself — the raw
    value is not stored anywhere and must not travel.
    """

    user_id: UUID
    key_prefix: str
    #: The permission keys the key was issued with — the whole of what it may
    #: do, whatever its owner may.
    permissions: frozenset[str] = field(default_factory=frozenset)
    #: Empty for an ordinary key; otherwise the scopes the key was issued for,
    #: which confine it to the endpoints that guard their permissions.
    scopes: tuple[str, ...] = ()


ApiKeyResolverFn = Callable[['AsyncSession', str], Awaitable['ApiKeyIdentity | None']]

_resolver: ApiKeyResolverFn | None = None


def register_api_key_resolver(fn: ApiKeyResolverFn) -> None:
    """Register the API-key resolver (called by the owning module)."""
    global _resolver
    _resolver = fn


def clear_api_key_resolver() -> None:
    """Reset the registry — test isolation only."""
    global _resolver
    _resolver = None


async def resolve_api_key(db: AsyncSession, raw_key: str) -> ApiKeyIdentity | None:
    """Return the identity a valid API key carries, else ``None``.

    ``None`` covers both "no such key" and "the api_keys module is not
    installed" — from the caller's side those are the same answer: this
    credential does not authenticate anyone.
    """
    identity = None if _resolver is None else await _resolver(db, raw_key)
    # Only a key accepted here may count as a client of its own; see
    # ``app.core.limiter``.
    record_api_key_verdict(raw_key, issued=identity is not None)
    return identity


#: Loads, in one query, a check telling an issued, active key from any other
#: value. The rate limiter asks it in place of a lookup per key once a sender
#: has spent its lookups (``app.core.limiter``); the check closes over the
#: module's own hashing, which stays on its side of the boundary.
IssuedApiKeysFn = Callable[['AsyncSession'], Awaitable[Callable[[str], bool]]]

_issued_api_keys: IssuedApiKeysFn | None = None


def register_issued_api_keys(fn: IssuedApiKeysFn) -> None:
    """Register the issued-key list loader (called by the owning module)."""
    global _issued_api_keys
    _issued_api_keys = fn


def _no_key_is_issued(raw_key: str) -> bool:
    return False


async def load_issued_api_keys(db: AsyncSession) -> Callable[[str], bool]:
    """The check of the keys issued now; nothing passes it without the module."""
    if _issued_api_keys is None:
        return _no_key_is_issued
    return await _issued_api_keys(db)


# --- Key scopes ---------------------------------------------------------------
#
# A scoped key is issued for one job — a print agent on a Raspberry Pi next to
# the printer — and must not be able to do anything else. Its permission list
# alone cannot say that: the reads every member needs (the shell, one's own
# account, the units of measure) ask for no permission at all, so a key
# holding nothing still reads them. A scope is therefore a list of
# permissions, registered by the module that guards them, and a key issued for
# it reaches only the endpoints that guard one of those permissions; every
# other endpoint, including the ones that guard nothing, refuses it. Deny by
# default: a scope nobody registered (its module gone) admits no endpoint.
#
# It was a list of URL prefixes once, and renaming a route silently changed
# what a scoped key could reach. A permission is the name the endpoint itself
# declares, so the route and the scope can no longer drift apart.

#: The attribute a permission guard carries naming the permissions it checks
#: (set by ``require_permission`` and ``require_read_write``), which is how a
#: route is read for the permissions it guards.
GUARDED_PERMISSIONS_ATTR = '__guarded_permissions__'

_scopes: dict[str, tuple[str, ...]] = {}

#: Where a route keeps what it guards once read: the route table is built
#: once, and walking a dependency tree on every request would not be.
_GUARDED_CACHE_ATTR = '_api_key_guarded_permissions'


def register_api_key_scope(name: str, permissions: tuple[str, ...]) -> None:
    """Declare a key scope and the permissions a key of that scope may use."""
    _scopes[name] = permissions


def api_key_scopes() -> dict[str, tuple[str, ...]]:
    """Every scope a key can be issued for, with its permissions, by name."""
    return {name: _scopes[name] for name in sorted(_scopes)}


def api_key_permission_catalog() -> dict[str, object]:
    """Every permission a key could name: the catalogue the roles editor offers.

    The same catalogue, so a key and a role name and label a permission alike.
    Grouped as the roles editor groups it — system first, then per module —
    so the issuing module can leave out the modules an organization has off.
    """
    from app.core.module_registry import module_registry

    return module_registry.get_permissions_catalog()


def api_key_scope_permissions(scopes: Iterable[str]) -> frozenset[str]:
    """The permissions the given scopes allow together."""
    return frozenset(p for scope in scopes for p in _scopes.get(scope, ()))


def _guarded_permissions(dependant: Any) -> frozenset[str]:
    found: set[str] = set()
    for dependency in dependant.dependencies:
        found.update(getattr(dependency.call, GUARDED_PERMISSIONS_ATTR, ()))
        found |= _guarded_permissions(dependency)
    return frozenset(found)


def api_key_scopes_admit(scopes: Iterable[str], route: Any) -> bool:
    """Whether a key of ``scopes`` may call ``route``.

    True when the route guards at least one permission of those scopes; the
    guard itself then decides whether the key holds it. A request with no
    route resolved, or a route that guards nothing, admits no scoped key.
    """
    dependant = getattr(route, 'dependant', None)
    if dependant is None:
        return False
    guarded = getattr(route, _GUARDED_CACHE_ATTR, None)
    if guarded is None:
        guarded = _guarded_permissions(dependant)
        setattr(route, _GUARDED_CACHE_ATTR, guarded)
    return bool(guarded & api_key_scope_permissions(scopes))
