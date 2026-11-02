"""The gate that keeps a manifest permission from being decoration.

A key declared in a manifest reaches the roles matrix as a switch. If nothing
enforces it, the switch promises a restriction it never applies — which is how
sixteen of them accumulated. These cases pin what counts as enforcement, and
what the deferral list will and will not accept.
"""

from datetime import date

import pytest

from app.core.architecture_lint._quality_checks_permissions import (
    _check_manifest_permissions_enforced,
    _enforced_permission_keys,
    _manifest_permission_keys,
)


def _module(root, name, permissions, code=''):
    module_dir = root / name
    module_dir.mkdir(parents=True)
    (module_dir / 'manifest.json').write_text(
        '{"permissions": ' + permissions + '}', encoding='utf-8'
    )
    if code:
        (module_dir / 'router.py').write_text(code, encoding='utf-8')
    return module_dir


def test_manifest_keys_read_both_declared_shapes(tmp_path):
    _module(tmp_path, 'stats', '["stats:read"]')
    _module(tmp_path, 'warehouse', '[{"key": "warehouse:read"}]')

    assert _manifest_permission_keys(tmp_path) == {
        'stats:read': 'stats',
        'warehouse:read': 'warehouse',
    }


def test_router_level_pair_covers_both_keys(tmp_path):
    _module(
        tmp_path,
        'warehouse',
        '["warehouse:read", "warehouse:write"]',
        "router = APIRouter(dependencies=[require_read_write('warehouse:read', 'warehouse:write')])",
    )

    assert _check_manifest_permissions_enforced(tmp_path, tmp_path, set()) == []


def test_a_key_nobody_asks_for_is_reported(tmp_path):
    _module(tmp_path, 'stats', '["stats:read"]', 'router = APIRouter()')

    errors = _check_manifest_permissions_enforced(tmp_path, tmp_path, set())

    assert len(errors) == 1
    assert "'stats:read'" in errors[0]


def test_a_module_local_wrapper_counts_as_enforcement(tmp_path):
    """approvals guards its router this way; a fixed list of names would miss it."""
    _module(
        tmp_path,
        'approvals',
        '["approvals:write"]',
        "_guard = _require_module_permission('approvals:write', 'forbidden')",
    )

    assert _check_manifest_permissions_enforced(tmp_path, tmp_path, set()) == []


def test_a_core_key_a_module_names_is_out_of_scope(tmp_path):
    """A module may declare it needs items:read; Core enforces it via the enum."""
    _module(tmp_path, 'recipes', '["items:read"]', 'router = APIRouter()')

    assert _check_manifest_permissions_enforced(tmp_path, tmp_path, set()) == []


def test_a_deferred_key_is_silent(tmp_path):
    _module(tmp_path, 'stats', '["stats:read"]', 'router = APIRouter()')

    assert (
        _check_manifest_permissions_enforced(tmp_path, tmp_path, {'stats:read'}) == []
    )


def test_a_key_named_only_in_a_docstring_is_not_enforcement(tmp_path):
    """A plain grep counts these; the effect on a request is nil."""
    _module(
        tmp_path,
        'maker',
        '["maker:write"]',
        '"""Accept the shorthand "maker:write" alongside full objects."""',
    )

    errors = _check_manifest_permissions_enforced(tmp_path, tmp_path, set())

    assert len(errors) == 1
    assert "'maker:write'" in errors[0]


def test_enforcement_in_a_test_file_does_not_count(tmp_path):
    module_dir = _module(tmp_path, 'stats', '["stats:read"]')
    (module_dir / 'test_stats.py').write_text(
        "require_permission('stats:read')", encoding='utf-8'
    )

    assert _enforced_permission_keys(tmp_path) == set()


@pytest.mark.parametrize(
    'line,expected_error',
    [
        ('stats:read', 'malformed'),
        ('stats:read | owner= | expires=2099-01-01 | why', 'names nobody'),
        ('stats:read | owner=me | expires=soon | why', 'unreadable expiry'),
        ('stats:read | owner=me | expires=2020-01-01 | why', 'expired'),
        ('stats:read | owner=me | expires=2099-01-01 |', 'malformed'),
    ],
)
def test_deferral_list_refuses_a_suppression_that_hides(
    tmp_path, monkeypatch, line, expected_error
):
    from app.core.architecture_lint import _baselines

    path = tmp_path / 'deferrals.txt'
    path.write_text(f'# comment\n{line}\n', encoding='utf-8')
    monkeypatch.setattr(_baselines, 'MANIFEST_PERMISSION_DEFERRALS_FILE', path)

    keys, errors = _baselines._load_manifest_permission_deferrals(date(2026, 8, 23))

    assert keys == set()
    assert len(errors) == 1
    assert expected_error in errors[0]


def test_a_well_formed_deferral_is_accepted(tmp_path, monkeypatch):
    from app.core.architecture_lint import _baselines

    path = tmp_path / 'deferrals.txt'
    path.write_text(
        'stats:read | owner=maintainers | expires=2026-09-30 | Waiting on default_roles.\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(_baselines, 'MANIFEST_PERMISSION_DEFERRALS_FILE', path)

    keys, errors = _baselines._load_manifest_permission_deferrals(date(2026, 8, 23))

    assert keys == {'stats:read'}
    assert errors == []
