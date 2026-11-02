"""A system permission named by its string is the permission itself.

``require_permission`` takes a string as readily as the enum, and so does
``has_permission``. A string went to the module-permission branch only, so a
member holding ``items:read`` was refused ``has_permission('items:read')`` —
admins bypass the check, which is how it went unseen.
"""

from uuid import uuid4

from app.core.contracts import SystemPermission, UserContextDTO


def _member(*permissions: SystemPermission) -> UserContextDTO:
    return UserContextDTO(
        id=uuid4(),
        organization_id=uuid4(),
        role='manager',
        permissions=set(permissions),
        extra_permissions={'printing:agent'},
    )


class TestASystemPermissionByItsName:
    def test_the_string_finds_a_held_system_permission(self) -> None:
        assert _member(SystemPermission.ITEMS_READ).has_permission('items:read')

    def test_the_string_does_not_find_one_not_held(self) -> None:
        assert not _member(SystemPermission.ITEMS_READ).has_permission('items:write')

    def test_a_module_permission_is_still_read_from_its_own_set(self) -> None:
        assert _member().has_permission('printing:agent')
        assert not _member().has_permission('warehouse:read')
