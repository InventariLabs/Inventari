"""FastAPI dependency helpers.

Modules should import from here for DI helpers (``Depends(...)`` factories,
current-user context, permission guards).  DB primitives (``Base``,
``SessionLocal`` …) live in :mod:`app.core.db_facade` — the path for modules
the import lint keeps out of ``app.database`` and ``app.models``; modules on
``TRUSTED_CORE_MODULES`` may import them directly.
"""

from typing import Any
from uuid import UUID

from fastapi import Depends, Request

from app.core.api_key_auth import GUARDED_PERMISSIONS_ATTR
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.exceptions import ForbiddenException
from app.core.module_identity import current_module
from app.database import get_async_db, get_db
from app.i18n.service import get_current_lang, get_error_message
from app.services.identity_service import (
    get_current_user,
    get_current_user_context,
)


def _refuse_borrowed_permission(permission: str) -> None:
    """A community module guards only its own permission namespace.

    ``require_permission`` takes any key, so an endpoint of a third-party
    module could enforce ``items:read``: a grant made for the core UI then
    authorized the module's endpoint as a side effect, and the roles matrix
    showed a key no module can meaningfully own. A module the repository
    ships is reviewed code and may guard core resources (equipment guards
    ``items:write``); a dropped/installed community module may not. Core
    endpoints carry no identity and are never refused.
    """
    caller = current_module()
    if caller is None:
        return
    from app.core.module_safety import REPO_SHIPPED_MODULES

    if caller in REPO_SHIPPED_MODULES:
        return
    namespace = permission.partition(':')[0]
    if namespace == caller:
        return
    raise RuntimeError(
        f'require_permission({permission!r}) on a {caller!r} endpoint: a '
        f'module may guard only permissions in its own "{caller}:" namespace'
    )


def require_permission(
    permission: 'SystemPermission | str',
    *,
    message_key: str = 'insufficient_permissions',
) -> Any:
    """FastAPI dependency factory that enforces a single permission.

    Usage::

        @router.delete('/items/{item_id}')
        async def delete_item(
            ...,
            _: None = Depends(require_permission(SystemPermission.ITEMS_DELETE)),
            current_user: UserContextDTO = Depends(get_current_user_context),
        ): ...

    Raises HTTP 403 when the resolved user context does not satisfy the
    required permission.  Admins bypass all checks (UserContextDTO.has_permission).

    A module endpoint may only guard permissions in its own ``<module>:``
    namespace; a module the repository ships may guard core ones (equipment
    guards ``items:write``). The caller's identity is read at request time
    from ``app.core.module_identity``; core endpoints carry none and are
    never refused.

    ``message_key`` names the error message the refusal carries, for a guard
    whose refusal says more than "you may not" (approvals: who configures).
    """

    async def _check(
        user_context: UserContextDTO = Depends(get_current_user_context),
    ) -> None:
        needed = (
            permission.value
            if isinstance(permission, SystemPermission)
            else str(permission)
        )
        _refuse_borrowed_permission(needed)
        if not user_context.has_permission(permission):
            raise ForbiddenException(get_error_message(message_key, get_current_lang()))

    # Preserve a readable name for FastAPI's OpenAPI schema and for debugging.
    perm_label = (
        permission.value
        if isinstance(permission, SystemPermission)
        else str(permission)
    )
    _check.__name__ = f'require_{perm_label.replace(":", "_")}'
    setattr(_check, GUARDED_PERMISSIONS_ATTR, (perm_label,))

    return Depends(_check)


def require_any_permission(
    *permissions: 'SystemPermission | str',
    message_key: str = 'insufficient_permissions',
) -> Any:
    """Like ``require_permission``, admitting a caller who holds any of these.

    For a route two screens share under different grants: the print queue
    serves the Labels screen (``items:read``) and a location card
    (``locations:read``); a workflow's definition is read by its readers and
    by those who configure it. A key of a scope covering any of them is
    admitted to the route, and the guard decides.
    """
    labels = tuple(
        p.value if isinstance(p, SystemPermission) else str(p) for p in permissions
    )

    async def _check(
        user_context: UserContextDTO = Depends(get_current_user_context),
    ) -> None:
        for label in labels:
            _refuse_borrowed_permission(label)
        if not any(user_context.has_permission(label) for label in labels):
            raise ForbiddenException(get_error_message(message_key, get_current_lang()))

    _check.__name__ = 'require_any_of_' + '_'.join(
        label.replace(':', '_') for label in labels
    )
    setattr(_check, GUARDED_PERMISSIONS_ATTR, labels)

    return Depends(_check)


_SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})


def read_only_post(endpoint: Any) -> Any:
    """Mark a ``POST`` endpoint that changes nothing, for ``require_read_write``.

    A preview or a search is a ``POST`` only because it carries a body; the
    guard then asks for *read* instead of *write*. Mark the handler, not the
    router, so the exemption cannot spread to a sibling route.
    """
    endpoint.__read_only_post__ = True
    return endpoint


def require_read_write(read_permission: str, write_permission: str) -> Any:
    """Router-level guard: safe methods need *read*, mutating ones need *write*.

       Usage::

           router = APIRouter(
               dependencies=[
                   Depends(require_module('warehouse')),
                   require_read_write('warehouse:read', 'warehouse:write'),
               ]
           )

       Mounted once on a module's top-level router it covers every endpoint of
       every sub-router, including the ones added later — which is the point.
       Declaring the pair per endpoint is how a module ends up with a manifest
    permission that guards three routes out of eighty.

       Only use it where the HTTP method tells the truth about the effect; a
       ``POST`` that merely reads is marked with ``read_only_post``.
    """

    async def _check(
        request: Request,
        user_context: UserContextDTO = Depends(get_current_user_context),
    ) -> None:
        route = request.scope.get('route')
        reads = request.method in _SAFE_METHODS or getattr(
            getattr(route, 'endpoint', None), '__read_only_post__', False
        )
        needed = read_permission if reads else write_permission
        _refuse_borrowed_permission(needed)
        if not user_context.has_permission(needed):
            raise ForbiddenException(
                get_error_message('insufficient_permissions', get_current_lang())
            )

    _check.__name__ = f'require_{read_permission.replace(":", "_")}_rw'
    setattr(_check, GUARDED_PERMISSIONS_ATTR, (read_permission, write_permission))
    return Depends(_check)


def require_org(
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> UUID:
    """FastAPI dependency that resolves and returns the current org id.

    Usable both as an injected dependency (``org_id: UUID = Depends(require_org)``)
    and as a plain helper (``org_id = require_org(current_user)``). Raises
    HTTP 403 when the authenticated user has no organization.
    """
    if not current_user.organization_id:
        raise ForbiddenException(
            get_error_message('organization_required', get_current_lang())
        )
    return current_user.organization_id


__all__ = [
    'get_db',
    'get_async_db',
    'get_current_user',
    'get_current_user_context',
    'require_permission',
    'read_only_post',
    'require_read_write',
    'require_org',
]
