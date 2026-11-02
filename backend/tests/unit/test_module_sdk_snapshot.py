"""Unit tests for the module SDK's additive-only snapshot.

The SDK is the third stability promise beside ``contracts_snapshot.json`` and
``core_api_snapshot.json``: a module outside this repository imports it to
register itself and subclasses the hooks it exports. A rename here is not an
internal refactor — it is every installed module failing at import, in front of
a user. These tests pin the diff policy, and the committed snapshot.
"""

from __future__ import annotations

from app.core.architecture_lint._module_sdk_snapshot import (
    build_snapshot,
    diff_snapshot,
    load_snapshot,
)


def _function(*, required: tuple[str, ...] = (), optional: tuple[str, ...] = ()):
    params = [
        {'name': name, 'kind': 'KEYWORD_ONLY', 'required': True} for name in required
    ] + [{'name': name, 'kind': 'KEYWORD_ONLY', 'required': False} for name in optional]
    return {'kind': 'function', 'params': params}


def _snapshot(names: dict) -> dict:
    return {'version': 1, 'names': names}


class TestBreakingChanges:
    def test_an_export_removed_is_breaking(self):
        old = _snapshot({'define_module': _function(required=('router',))})
        new = _snapshot({})

        assert diff_snapshot(old, new) == [
            'define_module: removed from app.core.module_sdk — a module '
            'importing it stops working'
        ]

    def test_a_kind_change_is_breaking(self):
        old = _snapshot({'define_module': _function(required=('router',))})
        new = _snapshot({'define_module': {'kind': 'value', 'type': 'int'}})

        assert diff_snapshot(old, new) == [
            'define_module: kind changed function -> value'
        ]

    def test_a_renamed_parameter_is_breaking(self):
        old = _snapshot({'get_logger': _function(required=('name',))})
        new = _snapshot({'get_logger': _function(required=('logger_name',))})

        errors = diff_snapshot(old, new)

        assert errors[0] == 'get_logger(name): parameter removed or renamed'
        assert any('new required parameter' in error for error in errors)

    def test_a_new_required_parameter_is_breaking(self):
        old = _snapshot({'get_logger': _function(required=('name',))})
        new = _snapshot({'get_logger': _function(required=('name', 'level'))})

        errors = diff_snapshot(old, new)

        assert len(errors) == 1
        assert 'new required parameter' in errors[0]

    def test_an_optional_parameter_becoming_required_is_breaking(self):
        old = _snapshot(
            {'define_module': _function(required=('router',), optional=('schedules',))}
        )
        new = _snapshot(
            {
                'define_module': {
                    'kind': 'function',
                    'params': [
                        {'name': 'router', 'kind': 'KEYWORD_ONLY', 'required': False},
                        {
                            'name': 'schedules',
                            'kind': 'KEYWORD_ONLY',
                            'required': True,
                        },
                    ],
                }
            }
        )

        errors = diff_snapshot(old, new)

        assert 'define_module(schedules): optional parameter became required' in errors

    def test_a_removed_hook_is_breaking(self):
        old = _snapshot(
            {
                'BaseModule': {
                    'kind': 'class',
                    'bases': ['ABC'],
                    'init': [],
                    'members': {
                        'on_enable': {
                            'kind': 'method',
                            'abstract': False,
                            'params': [],
                        }
                    },
                }
            }
        )
        new = _snapshot(
            {
                'BaseModule': {
                    'kind': 'class',
                    'bases': ['ABC'],
                    'init': [],
                    'members': {},
                }
            }
        )

        errors = diff_snapshot(old, new)

        assert errors == [
            'BaseModule.on_enable: member removed — a module that overrides or '
            'calls it stops working'
        ]

    def test_a_concrete_hook_becoming_abstract_is_breaking(self):
        old = _snapshot(
            {
                'ItemInterceptor': {
                    'kind': 'class',
                    'bases': ['ABC'],
                    'init': [],
                    'members': {
                        'before_delete': {
                            'kind': 'method',
                            'abstract': False,
                            'params': [],
                        }
                    },
                }
            }
        )
        new = _snapshot(
            {
                'ItemInterceptor': {
                    'kind': 'class',
                    'bases': ['ABC'],
                    'init': [],
                    'members': {
                        'before_delete': {
                            'kind': 'method',
                            'abstract': True,
                            'params': [],
                        }
                    },
                }
            }
        )

        errors = diff_snapshot(old, new)

        assert 'concrete member became abstract' in errors[0]

    def test_a_new_abstract_hook_is_breaking(self):
        old = _snapshot(
            {
                'ItemInterceptor': {
                    'kind': 'class',
                    'bases': ['ABC'],
                    'init': [],
                    'members': {},
                }
            }
        )
        new = _snapshot(
            {
                'ItemInterceptor': {
                    'kind': 'class',
                    'bases': ['ABC'],
                    'init': [],
                    'members': {
                        'before_archive': {
                            'kind': 'method',
                            'abstract': True,
                            'params': [],
                        }
                    },
                }
            }
        )

        errors = diff_snapshot(old, new)

        assert 'new abstract member' in errors[0]

    def test_a_base_class_change_is_breaking(self):
        old = _snapshot(
            {
                'BaseModule': {
                    'kind': 'class',
                    'bases': ['ABC'],
                    'init': [],
                    'members': {},
                }
            }
        )
        new = _snapshot(
            {
                'BaseModule': {
                    'kind': 'class',
                    'bases': ['Generic'],
                    'init': [],
                    'members': {},
                }
            }
        )

        errors = diff_snapshot(old, new)

        assert errors == ["BaseModule: base class changed ['ABC'] -> ['Generic']"]

    def test_a_constructor_change_is_breaking(self):
        old = _snapshot(
            {
                'ModuleScheduledTask': {
                    'kind': 'class',
                    'bases': [],
                    'init': [
                        {
                            'name': 'name',
                            'kind': 'POSITIONAL_OR_KEYWORD',
                            'required': True,
                        },
                    ],
                    'members': {},
                }
            }
        )
        new = _snapshot(
            {
                'ModuleScheduledTask': {
                    'kind': 'class',
                    'bases': [],
                    'init': [
                        {
                            'name': 'task_name',
                            'kind': 'POSITIONAL_OR_KEYWORD',
                            'required': True,
                        },
                    ],
                    'members': {},
                }
            }
        )

        errors = diff_snapshot(old, new)

        assert errors[0] == 'ModuleScheduledTask(name): parameter removed or renamed'
        assert any('new required parameter' in error for error in errors)

    def test_a_registry_value_changing_type_is_breaking(self):
        old = _snapshot({'scan_registry': {'kind': 'value', 'type': 'ScanRegistry'}})
        new = _snapshot({'scan_registry': {'kind': 'value', 'type': 'dict'}})

        assert diff_snapshot(old, new) == [
            'scan_registry: value type changed ScanRegistry -> dict'
        ]


class TestAdditiveChanges:
    def test_a_new_export_passes(self):
        old = _snapshot({'define_module': _function()})
        new = _snapshot({'define_module': _function(), 'new_helper': _function()})

        assert diff_snapshot(old, new) == []

    def test_a_new_optional_parameter_passes(self):
        old = _snapshot({'define_module': _function(required=('router',))})
        new = _snapshot(
            {'define_module': _function(required=('router',), optional=('seed',))}
        )

        assert diff_snapshot(old, new) == []

    def test_a_new_concrete_hook_passes(self):
        old = _snapshot(
            {
                'BaseModule': {
                    'kind': 'class',
                    'bases': ['ABC'],
                    'init': [],
                    'members': {},
                }
            }
        )
        new = _snapshot(
            {
                'BaseModule': {
                    'kind': 'class',
                    'bases': ['ABC'],
                    'init': [],
                    'members': {
                        'on_ready': {
                            'kind': 'method',
                            'abstract': False,
                            'params': [],
                        }
                    },
                }
            }
        )

        assert diff_snapshot(old, new) == []

    def test_identical_snapshots_pass(self):
        snapshot = _snapshot({'get_logger': _function(required=('name',))})

        assert diff_snapshot(snapshot, snapshot) == []


class TestBuildSnapshot:
    def test_it_covers_every_exported_name(self):
        from app.core import module_sdk

        snapshot = build_snapshot()

        assert snapshot['version'] == 1
        assert set(snapshot['names']) == set(module_sdk.__all__)

    def test_it_records_the_hook_signatures_a_module_implements(self):
        names = build_snapshot()['names']

        based = names['BaseModule']
        assert based['kind'] == 'class'
        assert based['members']['on_enable']['kind'] == 'method'
        assert based['members']['metadata']['kind'] == 'property'
        assert based['members']['metadata']['abstract'] is True
        assert names['define_module']['kind'] == 'function'
        assert [p['name'] for p in names['define_module']['params']] == [
            'router',
            'router_factory',
            'interceptors',
            'seed',
            'schedules',
            'register_services_hook',
            'register_contributions_hook',
            'on_startup_hook',
            'on_startup_async_hook',
            'on_install_hook',
            'on_install_async_hook',
            'on_uninstall_hook',
            'on_upgrade_hook',
            'consumes_stock_quant',
            'settings_schema',
            'default_settings',
        ]

    def test_a_registry_singleton_records_the_methods_a_module_calls(self):
        names = build_snapshot()['names']

        scan = names['scan_registry']
        assert scan['kind'] == 'value'
        assert scan['type'] == 'ScanRegistry'
        assert [p['name'] for p in scan['members']['register']['params']] == [
            'provider',
            'priority',
        ]
        assert scan['members']['scan']['kind'] == 'method'

    def test_a_value_the_sdk_only_re_exports_records_no_members(self):
        assert 'members' not in build_snapshot()['names']['ScannedCode']

    def test_a_changed_registry_method_signature_is_breaking(self):
        from app.core.scan_registry import ScanRegistry

        old = build_snapshot()
        original = ScanRegistry.register

        def register(self, provider, new_required):
            return None

        ScanRegistry.register = register  # type: ignore[method-assign]
        try:
            errors = diff_snapshot(old, build_snapshot())
        finally:
            ScanRegistry.register = original  # type: ignore[method-assign]

        assert any(e.startswith('scan_registry.register') for e in errors)

    def test_a_removed_registry_method_is_breaking(self):
        old = _snapshot(
            {
                'scan_registry': {
                    'kind': 'value',
                    'type': 'ScanRegistry',
                    'members': {
                        'scan': {'kind': 'method', 'abstract': False, 'params': []}
                    },
                }
            }
        )
        new = _snapshot(
            {'scan_registry': {'kind': 'value', 'type': 'ScanRegistry', 'members': {}}}
        )

        assert diff_snapshot(old, new) == [
            'scan_registry.scan: member removed — a module that overrides or '
            'calls it stops working'
        ]

    def test_the_names_the_acceptance_names_are_exported(self):
        from app.core import module_sdk

        for name in (
            'define_module',
            'BaseModule',
            'ModuleContext',
            'ItemInterceptor',
            'StorageInterceptor',
            'CategoryInterceptor',
            'BaseContribution',
            'AppException',
            'NotFoundException',
            'require_module',
            'get_async_db',
            'get_current_user_context',
            'get_logger',
            'ModuleModelBase',
            'PaginatedResponse',
        ):
            assert name in module_sdk.__all__, name

    def test_build_snapshot_is_stable(self):
        assert build_snapshot() == build_snapshot()

    def test_the_committed_snapshot_has_no_breaking_changes(self):
        from app.core.architecture_lint._constants import MODULE_SDK_SNAPSHOT_FILE

        assert MODULE_SDK_SNAPSHOT_FILE.exists(), (
            'module_sdk_snapshot.json missing — run '
            '`python manage.py arch lint --update-module-sdk-snapshot`'
        )
        assert (
            diff_snapshot(load_snapshot(MODULE_SDK_SNAPSHOT_FILE), build_snapshot())
            == []
        )


class TestTheGate:
    def test_a_missing_snapshot_is_an_error_naming_the_command(self, tmp_path):
        from app.core.architecture_lint._module_sdk_snapshot import (
            check_module_sdk_snapshot,
        )

        errors = check_module_sdk_snapshot(tmp_path / 'missing.json')

        assert len(errors) == 1
        assert 'module SDK snapshot missing' in errors[0]
        assert '--update-module-sdk-snapshot' in errors[0]

    def test_a_breaking_change_is_an_error_per_change(self, tmp_path):
        import json

        from app.core.architecture_lint._module_sdk_snapshot import (
            check_module_sdk_snapshot,
        )

        snapshot = build_snapshot()
        # A parameter the live SDK no longer has: the shape a rename leaves in
        # the committed snapshot until somebody regenerates it.
        snapshot['names']['define_module']['params'].append(
            {'name': 'ghost', 'kind': 'KEYWORD_ONLY', 'required': True}
        )
        path = tmp_path / 'module_sdk_snapshot.json'
        path.write_text(json.dumps(snapshot), encoding='utf-8')

        errors = check_module_sdk_snapshot(path)

        assert len(errors) == 1
        assert 'module SDK breaking change' in errors[0]
        assert 'define_module(ghost): parameter removed or renamed' in errors[0]

    def test_the_cli_regenerates_the_snapshot(self, tmp_path):
        """The documented command is the only way the snapshot should move."""
        import json

        from typer.testing import CliRunner

        from manage import app

        target = tmp_path / 'module_sdk_snapshot.json'
        result = CliRunner().invoke(
            app,
            [
                'arch',
                'lint',
                '--update-module-sdk-snapshot',
                '--module-sdk-snapshot',
                str(target),
            ],
        )

        assert result.exit_code == 0, result.output
        assert json.loads(target.read_text(encoding='utf-8'))['names']
        assert 'module SDK snapshot with' in result.output
