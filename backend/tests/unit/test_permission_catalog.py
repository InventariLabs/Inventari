"""Module permissions reach the catalog a role editor can offer (step 2).

The registration and catalog methods existed but had no callers outside their
own tests — a manifest could declare ``maker:write`` and nothing in the system
ever learned the key existed, so no role could grant it and the endpoint
guarded by it rejected everyone.
"""

import pytest

from app.core._registry_class import module_registry
from app.core.contracts import SystemPermission
from app.core.module_manifest_schema import PermissionDef


@pytest.fixture(autouse=True)
def _restore_custom_permissions():
    saved = dict(module_registry._custom_permissions)
    yield
    module_registry._custom_permissions.clear()
    module_registry._custom_permissions.update(saved)


class TestPermissionCatalog:
    def test_module_permissions_join_the_catalog(self):
        module_registry.register_permission_defs(
            'warranty', [PermissionDef(key='warranty:write')]
        )

        assert 'warranty:write' in module_registry.get_all_permissions()

    def test_system_permissions_are_always_there(self):
        catalog = module_registry.get_all_permissions()

        assert SystemPermission.ITEMS_DELETE.value in catalog

    def test_no_duplicates_when_a_module_reregisters(self):
        module_registry.register_permission_defs(
            'warranty', [PermissionDef(key='warranty:write')]
        )
        module_registry.register_permission_defs(
            'warranty', [PermissionDef(key='warranty:write')]
        )

        catalog = module_registry.get_all_permissions()

        assert catalog.count('warranty:write') == 1

    def test_re_registration_replaces_rather_than_appends(self):
        """A module that drops a permission must not leave it grantable."""
        module_registry.register_permission_defs(
            'warranty', [PermissionDef(key='warranty:old')]
        )
        module_registry.register_permission_defs(
            'warranty', [PermissionDef(key='warranty:new')]
        )

        catalog = module_registry.get_all_permissions()

        assert 'warranty:new' in catalog
        assert 'warranty:old' not in catalog


class TestGroupedCatalog:
    """The shape the RBAC matrix renders: a system group plus one per module."""

    def test_system_permissions_are_always_present(self):
        catalog = module_registry.get_permissions_catalog([])

        keys = {p['key'] for p in catalog['system']}
        assert keys == {p.value for p in SystemPermission}

    def test_a_module_section_carries_the_labels(self):
        module_registry.register_permission_defs(
            'warranty',
            [PermissionDef(key='warranty:write', default_roles=['manager'])],
        )

        catalog = module_registry.get_permissions_catalog(['warranty'])

        (section,) = [m for m in catalog['modules'] if m['module'] == 'warranty']
        assert section['permissions'] == [
            {
                'key': 'warranty:write',
                'label_key': 'warranty:permissions.write',
                'description_key': None,
                'default_roles': ['manager'],
            }
        ]

    def test_a_disabled_module_contributes_no_columns(self):
        """A grant for a module the org does not run could never take effect."""
        module_registry.register_permission_defs(
            'warranty', [PermissionDef(key='warranty:write')]
        )

        catalog = module_registry.get_permissions_catalog(enabled_modules=['maker'])

        assert all(m['module'] != 'warranty' for m in catalog['modules'])

    def test_no_scope_means_everything(self):
        module_registry.register_permission_defs(
            'warranty', [PermissionDef(key='warranty:write')]
        )

        catalog = module_registry.get_permissions_catalog()

        assert any(m['module'] == 'warranty' for m in catalog['modules'])

    def test_a_key_alone_still_yields_a_conventional_label(self):
        """A definition with no explicit label is not left unrenderable."""
        module_registry.register_permission_defs(
            'warranty', [PermissionDef(key='warranty:write')]
        )

        catalog = module_registry.get_permissions_catalog(['warranty'])

        (section,) = [m for m in catalog['modules'] if m['module'] == 'warranty']
        assert section['permissions'][0]['label_key'] == 'warranty:permissions.write'
