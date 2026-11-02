"""Where the checkout sits must not change what the gate sees.

Every "is this file in scope" predicate in the linter used to read the
absolute path, so a checkout under any directory named ``tests`` (a CI
workspace at ``~/tests/inventari``, say) answered "test file" for every
file in the tree — and the gate printed "Architecture lint passed" over a
tree it had judged nothing in. The predicates now read the path relative
to the root they were handed.
"""

from pathlib import Path

from app.core.architecture_lint import (
    find_api_layer_import_violations,
    find_module_boundary_violations,
)
from app.core.architecture_lint._constants import _is_test_file


def _planted_module(root: Path) -> Path:
    """A module importing a Core model — one violation, wherever it lives."""
    module_dir = root / 'inventory'
    module_dir.mkdir(parents=True)
    (module_dir / 'service.py').write_text(
        'from app.models.item import Item\n', encoding='utf-8'
    )
    return module_dir


def test_a_checkout_under_a_directory_named_tests_is_still_linted(tmp_path):
    modules_root = tmp_path / 'tests' / 'inventari' / 'backend' / 'app' / 'modules'
    _planted_module(modules_root)

    violations, _ = find_module_boundary_violations(modules_root, baseline_file=None)

    assert [v.import_path for v in violations] == ['app.models.item']


def test_the_api_layer_check_survives_the_same_checkout(tmp_path):
    api_root = tmp_path / 'tests' / 'workspace' / 'backend' / 'app' / 'api'
    api_root.mkdir(parents=True)
    (api_root / 'items.py').write_text(
        'from app.models.item import Item\n', encoding='utf-8'
    )

    violations, _ = find_api_layer_import_violations(api_root, baseline_file=None)

    assert [v.import_path for v in violations] == ['app.models.item']


def test_tests_below_the_scan_root_are_still_skipped(tmp_path):
    """The relative reading must keep recognising the real thing."""
    modules_root = tmp_path / 'tests' / 'inventari' / 'modules'
    (modules_root / 'inventory' / 'tests').mkdir(parents=True)
    (modules_root / 'inventory' / 'tests' / 'test_example.py').write_text(
        'from app.models.item import Item\n', encoding='utf-8'
    )

    violations, _ = find_module_boundary_violations(modules_root, baseline_file=None)

    assert violations == []


def test_the_predicate_reads_the_path_relative_to_the_root_it_was_given(tmp_path):
    root = tmp_path / 'tests' / 'inventari'
    inside = root / 'app' / 'services' / 'item_service.py'
    below = root / 'app' / 'tests' / 'test_item_service.py'

    assert _is_test_file(inside, root) is False
    assert _is_test_file(below, root) is True
