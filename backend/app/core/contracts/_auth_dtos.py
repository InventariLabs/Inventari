from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel

from ._system_dtos import SystemPermission

if TYPE_CHECKING:
    from ._core_dtos import OrganizationDTO


class UserContextDTO(BaseModel):
    """Authenticated user context with granular permissions."""

    id: UUID
    organization_id: UUID | None = None
    organization: OrganizationDTO | None = None
    role: str = 'user'
    email: str | None = None
    is_superuser: bool = False
    permissions: set[SystemPermission] = set()
    # Module-registered custom permissions (e.g. 'pos:sell') are stored here.
    extra_permissions: set[str] = set()

    def has_permission(self, permission: SystemPermission | str) -> bool:
        """Check if user has a specific permission.

        Accepts both SystemPermission enum values and plain permission strings
        a module declared in its manifest (e.g. 'approvals:approve').
        Admins bypass all checks.
        """
        if self.role == 'admin':
            return True
        # A system permission named by its string ('items:read') is the same
        # permission: `SystemPermission` is a StrEnum, so the set finds it.
        # Sending such a string to the module branch alone refused every
        # member who held it.
        if permission in self.permissions:
            return True
        return str(permission) in self.extra_permissions
