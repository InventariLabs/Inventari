"""`capabilities` is the import allow-list; `permissions` is RBAC vocabulary.

Both used to live in `capabilities: list[str]`, so 13 of 15 in-tree manifests
mixed `maker:write` in with `database`. The AST safety scan only ever looked at
the four capability names (module_safety.CAPABILITY_MAP), which meant the
permission strings sat there doing nothing while the enum meant to constrain the
field went unused. These tests pin the split so they cannot merge back.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.module_manifest_schema import ManifestCapability, ModuleManifest
from app.core.module_safety import CAPABILITY_MAP


def _manifest(**overrides):
    return ModuleManifest(
        name='demo_mod', version='1.0.0', module_type='community', **overrides
    )


@pytest.mark.unit
class TestCapabilities:
    def test_accepts_the_capability_vocabulary(self):
        manifest = _manifest(capabilities=['database', 'network'])

        assert [str(c) for c in manifest.capabilities] == ['database', 'network']

    def test_rejects_a_permission_string(self):
        """`maker:write` is a permission — it never widened the import allow-list."""
        with pytest.raises(ValidationError):
            _manifest(capabilities=['maker:write'])

    def test_rejects_the_capability_the_old_scaffold_generated(self):
        """`module:read` exists in no enum and no CAPABILITY_MAP entry."""
        with pytest.raises(ValidationError):
            _manifest(capabilities=['module:read'])

    def test_enum_matches_what_the_safety_scan_understands(self):
        """A capability the scan cannot map would be unenforceable decoration."""
        assert {c.value for c in ManifestCapability} == set(CAPABILITY_MAP)


@pytest.mark.unit
class TestPermissions:
    def test_accepts_module_action_pairs(self):
        """Strings are still accepted; they widen to definitions."""
        manifest = _manifest(permissions=['demo_mod:write', 'items:read'])

        assert [p.key for p in manifest.permissions] == ['demo_mod:write', 'items:read']

    def test_rejects_a_capability_name_in_permissions(self):
        """Guards the reverse mistake: capability names drifting into permissions."""
        with pytest.raises(ValidationError, match='<module>:<action>'):
            _manifest(permissions=['database'])

    def test_rejects_a_bare_word(self):
        with pytest.raises(ValidationError, match='<module>:<action>'):
            _manifest(permissions=['write'])

    def test_defaults_to_empty(self):
        assert _manifest().permissions == []


@pytest.mark.unit
class TestOptionalRequires:
    """Soft companions get the same input hygiene as hard dependencies."""

    def test_accepts_a_list_of_module_names(self):
        manifest = _manifest(optional_requires=['shopping_lists'])

        assert manifest.optional_requires == ['shopping_lists']

    def test_defaults_to_empty(self):
        assert _manifest().optional_requires == []

    def test_rejects_a_non_list(self):
        with pytest.raises(ValidationError, match='optional_requires must be a list'):
            _manifest(optional_requires='shopping_lists')

    def test_rejects_non_string_entries(self):
        with pytest.raises(ValidationError, match='non-empty strings'):
            _manifest(optional_requires=[42])

    def test_rejects_blank_entries(self):
        with pytest.raises(ValidationError, match='non-empty strings'):
            _manifest(optional_requires=['  '])


@pytest.mark.unit
class TestInTreeManifests:
    """Every shipped manifest must parse — this is what the retype could break."""

    def test_all_in_tree_manifests_are_valid(self):
        manifests = sorted(Path('app/modules').glob('*/manifest.json'))
        assert manifests, 'no in-tree manifests found — wrong working directory?'

        for path in manifests:
            raw = json.loads(path.read_text(encoding='utf-8'))
            ModuleManifest(**raw)  # must not raise

    def test_no_manifest_still_carries_permissions_in_capabilities(self):
        for path in sorted(Path('app/modules').glob('*/manifest.json')):
            raw = json.loads(path.read_text(encoding='utf-8'))
            for cap in raw.get('capabilities', []):
                assert ':' not in cap, (
                    f'{path}: {cap!r} looks like a permission — move it to '
                    f'"permissions"'
                )


@pytest.mark.unit
class TestModuleTypeRequired:
    """The trust level is the one fact a store reader cannot guess
    — a manifest that omits it used to fall back to
    'community' — the lowest level — without declaring anything."""

    def test_a_manifest_without_module_type_is_a_validation_error(self):
        with pytest.raises(ValidationError, match='module_type'):
            ModuleManifest(name='demo_mod', version='1.0.0')

    def test_only_the_trust_vocabulary_is_accepted(self):
        with pytest.raises(ValidationError, match='module_type'):
            ModuleManifest(name='demo_mod', version='1.0.0', module_type='premium')
