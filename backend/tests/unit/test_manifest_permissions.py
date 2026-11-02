"""Manifest permissions are typed definitions in the module's own namespace.

Permissions used to be bare strings with nothing checking where they lived, so
a module could declare ``admin:access`` and the registry would publish it as
that module's own — the RBAC matrix would then offer an admin grant that looks
like it belongs to a third-party module.

Two rules make that impossible: a key sits under the module's name, and the one
exception (a core key the module depends on) is published by the system section
rather than the module's.
"""

import pytest
from pydantic import ValidationError

from app.core.contracts import SystemPermission
from app.core.module_manifest_schema import (
    CORE_PERMISSION_KEYS,
    ModuleManifest,
    PermissionDef,
)


def _manifest(name: str, permissions: list[object]) -> ModuleManifest:
    return ModuleManifest(
        name=name, version='1.0.0', module_type='community', permissions=permissions
    )


class TestPermissionDef:
    def test_a_bare_string_widens_to_a_definition(self):
        manifest = _manifest('maker', ['maker:write'])

        (perm,) = manifest.permissions
        assert perm.key == 'maker:write'
        assert perm.label_key == 'maker:permissions.write'
        assert perm.default_roles == []

    def test_an_explicit_label_key_wins(self):
        manifest = _manifest(
            'maker',
            [{'key': 'maker:write', 'label_key': 'maker:custom.label'}],
        )

        assert manifest.permissions[0].label_key == 'maker:custom.label'

    def test_default_roles_survive_parsing(self):
        manifest = _manifest(
            'approvals',
            [{'key': 'approvals:approve', 'default_roles': ['manager']}],
        )

        assert manifest.permissions[0].default_roles == ['manager']

    @pytest.mark.parametrize(
        'bad_key', ['nocolon', 'Maker:write', 'maker:', ':write', 'maker write']
    )
    def test_malformed_keys_are_rejected(self, bad_key: str):
        with pytest.raises(ValidationError):
            PermissionDef(key=bad_key)

    def test_unknown_fields_are_rejected(self):
        """extra='forbid' — a typo in a manifest must not pass silently."""
        with pytest.raises(ValidationError):
            PermissionDef(key='maker:write', labelKey='oops')


class TestNamespaceRule:
    def test_a_module_may_define_its_own_namespace(self):
        assert _manifest('maker', ['maker:write']).permissions

    def test_a_foreign_namespace_is_rejected(self):
        with pytest.raises(ValidationError, match='outside the "maker:" namespace'):
            _manifest('maker', ['warranty:write'])

    def test_a_module_cannot_claim_an_admin_key_as_its_own(self):
        """admin:access is a core key: allowed as a dependency, never redefined."""
        manifest = _manifest('maker', ['admin:access'])

        assert [p.key for p in manifest.permissions] == ['admin:access']
        assert manifest.defined_permissions == []

    def test_a_core_dependency_is_kept_but_not_defined(self):
        manifest = _manifest('recipes', ['items:read', 'recipes:consume'])

        assert len(manifest.permissions) == 2
        assert [p.key for p in manifest.defined_permissions] == ['recipes:consume']


class TestCoreKeyListStaysInStep:
    def test_it_mirrors_the_enum_exactly(self):
        """The list is duplicated for the CLI; drift would silently change the rule."""
        assert CORE_PERMISSION_KEYS == {p.value for p in SystemPermission}


class TestShippedManifests:
    def test_every_shipped_module_obeys_the_rule(self):
        """The manifests in this repo parse — the rule was applied, not just added."""
        from pathlib import Path

        import app.modules as modules_pkg

        base = Path(modules_pkg.__file__).parent
        checked = 0
        for manifest_path in sorted(base.glob('*/manifest.json')):
            manifest = ModuleManifest.load(manifest_path.parent)
            for perm in manifest.permissions:
                namespace = perm.key.split(':', 1)[0]
                assert namespace == manifest.name or perm.key in CORE_PERMISSION_KEYS
            checked += 1

        assert checked > 10, 'expected the full module set to be scanned'
