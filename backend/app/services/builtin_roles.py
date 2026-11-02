"""What a member may do purely by their base role.

``User.role`` carries one of four levels — admin, manager, user, viewer — and
they are not rows in ``roles``: no permission list is stored for them
anywhere, it is computed when a session's context is built. That is why the
roles screen, which reads the ``roles`` table, could only ever show custom
roles while promising "what each role in this organisation may do", and why
the four levels every account in a fresh organisation actually holds were
the ones an administrator could not look up.

This module is the single definition. ``identity_service`` resolves a
session's permissions through it, and the roles screen reads the same
function, so the screen cannot drift from what the guards enforce.
"""

from __future__ import annotations

from app.core.contracts import SystemPermission

#: The levels ``User.role`` may hold, most authority first. Kept in step with
#: ``VALID_MEMBER_ROLES`` in ``app.services._org_membership``, which decides which
#: of them may be assigned.
BUILTIN_ROLES: tuple[str, ...] = ('admin', 'manager', 'user', 'viewer')

#: Reading, and nothing else.
_VIEWER = frozenset(
    {
        SystemPermission.ITEMS_READ.value,
        SystemPermission.CATEGORIES_READ.value,
        SystemPermission.STORAGES_READ.value,
        SystemPermission.PARTNERS_READ.value,
        SystemPermission.ORG_READ.value,
    }
)

#: An ordinary member files things: naming a category and adding a shelf are
#: part of putting stock away, not administration. The write halves were in
#: the catalogue and granted to nobody, which read as "everyone may" for as
#: long as nothing enforced them.
_MEMBER = frozenset(
    _VIEWER
    | {
        SystemPermission.ITEMS_WRITE.value,
        SystemPermission.CATEGORIES_WRITE.value,
        SystemPermission.STORAGES_WRITE.value,
        SystemPermission.PARTNERS_WRITE.value,
    }
)

_BASE: dict[str, frozenset[str]] = {
    'viewer': _VIEWER,
    'user': _MEMBER,
    'manager': _MEMBER,
}


def builtin_role_permissions(role: str) -> set[str]:
    """Every permission key a member holds by this base role alone.

    Admins are given the whole catalogue, matching the bypass in
    ``UserContextDTO.has_permission``: a screen that showed an admin a
    shorter list than the API will act on would be lying about the account.

    Every other level gets its system permissions plus whatever the enabled
    modules' manifests hand to that role name by default — a member with no
    role row resolves their module permissions the same way, so without the
    second half the same person would be an operator in one organization and
    locked out in the next, purely because nobody created custom roles there.
    """
    from app.core.module_registry import module_registry

    if role == 'admin':
        return set(module_registry.get_all_permissions())

    base = _BASE.get(role, _MEMBER)
    return set(base) | set(module_registry.get_default_permissions_for_role(role))
