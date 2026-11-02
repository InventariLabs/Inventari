"""Unit tests for the contracts additive-only snapshot check."""

from app.core.architecture_lint._contracts_snapshot import (
    build_snapshot,
    diff_snapshot,
)


def _model(fields: dict[str, tuple[str, bool]]) -> dict:
    return {
        'kind': 'model',
        'fields': {
            name: {'type': ftype, 'required': required}
            for name, (ftype, required) in fields.items()
        },
    }


def _snapshot(contracts: dict) -> dict:
    return {'version': 1, 'contracts': contracts}


class TestDiffSnapshotBreakingChanges:
    def test_removed_contract_is_breaking(self):
        old = _snapshot({'ItemDTO': _model({'id': ('UUID', True)})})
        new = _snapshot({})
        errors = diff_snapshot(old, new)
        assert errors == ['ItemDTO: contract removed']

    def test_removed_field_is_breaking(self):
        old = _snapshot(
            {'ItemDTO': _model({'id': ('UUID', True), 'name': ('str', True)})}
        )
        new = _snapshot({'ItemDTO': _model({'id': ('UUID', True)})})
        errors = diff_snapshot(old, new)
        assert errors == ['ItemDTO.name: field removed']

    def test_type_change_is_breaking(self):
        old = _snapshot({'ItemDTO': _model({'qty': ('int', True)})})
        new = _snapshot({'ItemDTO': _model({'qty': ('float', True)})})
        errors = diff_snapshot(old, new)
        assert len(errors) == 1
        assert 'type changed int -> float' in errors[0]

    def test_optional_becoming_required_is_breaking(self):
        old = _snapshot({'ItemDTO': _model({'note': ('str', False)})})
        new = _snapshot({'ItemDTO': _model({'note': ('str', True)})})
        errors = diff_snapshot(old, new)
        assert errors == ['ItemDTO.note: optional field became required']

    def test_new_required_field_is_breaking(self):
        old = _snapshot({'ItemDTO': _model({'id': ('UUID', True)})})
        new = _snapshot(
            {'ItemDTO': _model({'id': ('UUID', True), 'org_id': ('UUID', True)})}
        )
        errors = diff_snapshot(old, new)
        assert len(errors) == 1
        assert 'ItemDTO.org_id: new required field' in errors[0]

    def test_removed_enum_member_is_breaking(self):
        old = _snapshot(
            {'AuditAction': {'kind': 'enum', 'members': ['CREATE', 'DELETE']}}
        )
        new = _snapshot({'AuditAction': {'kind': 'enum', 'members': ['CREATE']}})
        errors = diff_snapshot(old, new)
        assert errors == ['AuditAction.DELETE: enum member removed']

    def test_kind_change_is_breaking(self):
        old = _snapshot({'Thing': {'kind': 'enum', 'members': ['A']}})
        new = _snapshot({'Thing': _model({'id': ('UUID', True)})})
        errors = diff_snapshot(old, new)
        assert errors == ['Thing: kind changed enum -> model']


class TestDiffSnapshotAdditiveChanges:
    def test_forward_ref_vs_resolved_type_passes(self):
        """ForwardRef('X | None') and resolved 'a.b.X | None' are the same type."""
        old = _snapshot(
            {'ItemDTO': _model({'uom': ("ForwardRef('UomDTO | None')", False)})}
        )
        new = _snapshot(
            {
                'ItemDTO': _model(
                    {'uom': ('app.core.contracts._core_dtos.UomDTO | None', False)}
                )
            }
        )
        assert diff_snapshot(old, new) == []
        # And the other way around (committed resolved, live ForwardRef).
        assert diff_snapshot(new, old) == []

    def test_real_type_change_still_breaking_after_normalization(self):
        old = _snapshot({'ItemDTO': _model({'uom': ("ForwardRef('UomDTO')", False)})})
        new = _snapshot(
            {'ItemDTO': _model({'uom': ('app.core.contracts._core_dtos.UomDTO', True)})}
        )
        errors = diff_snapshot(old, new)
        assert errors == ['ItemDTO.uom: optional field became required']

    def test_new_optional_field_passes(self):
        old = _snapshot({'ItemDTO': _model({'id': ('UUID', True)})})
        new = _snapshot(
            {'ItemDTO': _model({'id': ('UUID', True), 'note': ('str | None', False)})}
        )
        assert diff_snapshot(old, new) == []

    def test_new_contract_passes(self):
        old = _snapshot({'ItemDTO': _model({'id': ('UUID', True)})})
        new = _snapshot(
            {
                'ItemDTO': _model({'id': ('UUID', True)}),
                'NewDTO': _model({'id': ('UUID', True)}),
            }
        )
        assert diff_snapshot(old, new) == []

    def test_required_becoming_optional_passes(self):
        old = _snapshot({'ItemDTO': _model({'name': ('str', True)})})
        new = _snapshot({'ItemDTO': _model({'name': ('str | None', False)})})
        # Type repr must stay identical for the relaxation branch to apply;
        # a type repr change is reported as a type change instead.
        old_same_type = _snapshot({'ItemDTO': _model({'name': ('str', True)})})
        new_same_type = _snapshot({'ItemDTO': _model({'name': ('str', False)})})
        assert diff_snapshot(old_same_type, new_same_type) == []
        assert diff_snapshot(old, new)[0].startswith('ItemDTO.name: type changed')

    def test_new_enum_member_passes(self):
        old = _snapshot({'AuditAction': {'kind': 'enum', 'members': ['CREATE']}})
        new = _snapshot(
            {'AuditAction': {'kind': 'enum', 'members': ['CREATE', 'UPDATE']}}
        )
        assert diff_snapshot(old, new) == []

    def test_identical_snapshots_pass(self):
        snap = _snapshot({'ItemDTO': _model({'id': ('UUID', True)})})
        assert diff_snapshot(snap, snap) == []


class TestBuildSnapshot:
    def test_build_snapshot_covers_all_contracts(self):
        from app.core import contracts

        snapshot = build_snapshot()
        assert snapshot['version'] == 1
        entries = snapshot['contracts']
        assert 'ItemDTO' in entries
        assert 'AuditAction' in entries
        assert entries['ItemDTO']['kind'] == 'model'
        assert entries['AuditAction']['kind'] == 'enum'

        # Every *type* the contract layer exports has a shape in the snapshot,
        # except the module model base: it is the one ORM class a module
        # inherits for its own tables, and a declarative base has no fields to
        # freeze (nor a shape a DTO consumer could depend on).
        exported_dtos = {
            name
            for name in contracts.__all__
            if isinstance(getattr(contracts, name, None), type)
        } - {'ModuleModelBase'}
        assert exported_dtos | {'SystemEvent', 'LlmCapability'} == set(entries)

    def test_event_names_and_llm_capabilities_are_snapshotted(self):
        """Enums a module outside the repo names sit outside ``contracts.__all__``.

        Dropping a ``SystemEvent`` member silences every subscription to it
        without an exception, so the enum is held by the same additive-only gate.
        """
        from app.core._event_types import SystemEvent

        entry = build_snapshot()['contracts']['SystemEvent']

        assert entry == {'kind': 'enum', 'members': sorted(m.name for m in SystemEvent)}
        assert 'LlmCapability' in build_snapshot()['contracts']

    def test_removing_a_system_event_member_is_breaking(self):
        live = build_snapshot()
        old = build_snapshot()
        old['contracts']['SystemEvent']['members'].append('ITEM_EXPLODED')

        assert diff_snapshot(old, live) == [
            'SystemEvent.ITEM_EXPLODED: enum member removed'
        ]

    def test_adding_a_system_event_member_passes(self):
        live = build_snapshot()
        old = build_snapshot()
        old['contracts']['SystemEvent']['members'].remove('ITEM_CREATED')

        assert diff_snapshot(old, live) == []

    def test_exported_constants_are_deliberate(self):
        """A non-type export is a value, not a contract the snapshot missed."""
        from app.core import contracts

        values = {
            name
            for name in contracts.__all__
            if not isinstance(getattr(contracts, name, None), type)
        }

        assert values == {
            'API_KEY_HEADER',
            'API_KEY_DEFAULT_PERMISSIONS',
            'API_KEY_PERMISSIONS',
            'API_KEY_PREFIX',
            'API_KEY_WITHHELD_PERMISSIONS',
            # The partner role sets are vocabulary a module compares a
            # partner against, not schema types — the same kind of export as
            # the stock-move enums, and deliberate for the same reason.
            'CUSTOMER_ROLE_TYPES',
            'SUPPLIER_ROLE_TYPES',
        }

    def test_build_snapshot_is_stable(self):
        assert build_snapshot() == build_snapshot()

    def test_committed_snapshot_has_no_breaking_changes(self):
        """Guard: the committed snapshot must match current contracts."""
        from app.core.architecture_lint._constants import CONTRACTS_SNAPSHOT_FILE
        from app.core.architecture_lint._contracts_snapshot import load_snapshot

        assert CONTRACTS_SNAPSHOT_FILE.exists(), (
            'contracts_snapshot.json missing — run '
            '`python manage.py arch lint --update-contracts-snapshot`'
        )
        errors = diff_snapshot(load_snapshot(CONTRACTS_SNAPSHOT_FILE), build_snapshot())
        assert errors == []
