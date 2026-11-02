"""A shipped module's reach into Core is frozen and only ever shrinks.

The modules this repository ships were written before ``app.core.module_sdk``
existed, so each still imports core helpers directly. That is debt, not a
contract: the install-time scan refuses a module installed from outside the
repository anything but ``app.core.contracts``, ``app.core.public_api`` and
``app.core.module_sdk``, and the modules here are the only exception — one
frozen list, in ``module_import_surface_baseline.txt``, with a reason per
module. These tests are what makes "frozen" mean it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.architecture_lint._baselines import _load_module_import_surface_baseline
from app.core.architecture_lint._constants import (
    MODULE_IMPORT_SURFACE_BASELINE_FILE,
    MODULES_ROOT,
)
from app.core.architecture_lint._quality_checks_modules import (
    _check_cross_module_imports,
    _check_module_import_surface,
    collect_module_surface_imports,
)


def _tree(root: Path, files: dict[str, str]) -> Path:
    """A modules root with one directory per dotted key prefix."""
    for rel, source in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    return root


@pytest.mark.unit
class TestTheFrozenSurface:
    def test_a_new_core_import_fails(self, tmp_path):
        root = _tree(
            tmp_path / 'modules', {'demo/router.py': 'from app.core.deps import x\n'}
        )

        errors = _check_module_import_surface(root, baseline={})

        assert len(errors) == 1
        assert 'import outside the module SDK' in errors[0]
        assert 'demo imports app.core.deps' in errors[0]

    def test_a_listed_import_passes(self, tmp_path):
        root = _tree(
            tmp_path / 'modules', {'demo/router.py': 'from app.core.deps import x\n'}
        )

        assert _check_module_import_surface(root, {'demo': {'app.core.deps'}}) == []

    def test_a_relative_import_is_judged_as_the_absolute_one(self, tmp_path):
        """``from ...core.deps import x`` in app/modules/demo/router.py is app.core.deps."""
        root = _tree(
            tmp_path / 'modules',
            {'demo/router.py': 'from ...core.deps import x\n'},
        )

        errors = _check_module_import_surface(root, baseline={})

        assert len(errors) == 1
        assert 'demo imports app.core.deps' in errors[0]

    def test_a_path_whose_import_is_gone_fails(self, tmp_path):
        """The list only shrinks: debt paid has to leave the file."""
        root = _tree(
            tmp_path / 'modules',
            {'demo/router.py': 'from app.core.module_sdk import define_module\n'},
        )

        errors = _check_module_import_surface(root, {'demo': {'app.core.deps'}})

        assert len(errors) == 1
        assert 'stale module surface entry' in errors[0]
        assert 'demo -> app.core.deps' in errors[0]

    def test_a_module_that_no_longer_exists_fails(self, tmp_path):
        root = _tree(
            tmp_path / 'modules',
            {'demo/router.py': 'from app.core.module_sdk import define_module\n'},
        )

        errors = _check_module_import_surface(root, {'gone': {'app.core.deps'}})

        assert len(errors) == 1
        assert 'stale module surface entry' in errors[0]
        assert "'gone'" in errors[0]

    def test_another_modules_package_is_frozen_too(self, tmp_path):
        """A sibling public API is legal to call, but a new one is a decision."""
        root = _tree(
            tmp_path / 'modules',
            {'demo/router.py': 'from app.modules.warehouse import warehouse_api\n'},
        )

        live = collect_module_surface_imports(root)

        assert live == {
            'demo': {
                'app.modules.warehouse.warehouse_api': (root / 'demo/router.py', 1)
            }
        }
        errors = _check_module_import_surface(root, baseline={})
        assert len(errors) == 1
        assert 'import outside the module SDK' in errors[0]
        assert 'demo imports app.modules.warehouse.warehouse_api' in errors[0]
        assert 'public API' in errors[0]
        assert (
            _check_module_import_surface(
                root, {'demo': {'app.modules.warehouse.warehouse_api'}}
            )
            == []
        )

    def test_a_private_sibling_file_is_left_to_the_cross_module_gate(self, tmp_path):
        """One refusal, one list: the shape gate already refuses this path."""
        root = _tree(
            tmp_path / 'modules',
            {'demo/router.py': 'from app.modules.warehouse._service import x\n'},
        )

        assert collect_module_surface_imports(root) == {'demo': {}}
        assert len(_check_cross_module_imports(root)) == 1

    def test_the_two_spellings_of_a_sibling_import_are_one_reach(self, tmp_path):
        root = _tree(
            tmp_path / 'modules',
            {
                'demo/a.py': (
                    'from app.modules.warehouse.warehouse_api import warehouse_api\n'
                ),
                'demo/b.py': 'from app.modules.warehouse import warehouse_api\n',
            },
        )

        assert set(collect_module_surface_imports(root)['demo']) == {
            'app.modules.warehouse.warehouse_api'
        }

    @pytest.mark.parametrize(
        'source',
        [
            'from app import config\n',
            'import app.config\n',
        ],
    )
    def test_the_top_package_is_not_a_way_around_the_surface(self, tmp_path, source):
        """``from app import config`` and ``import app.config`` are one reach."""
        root = _tree(tmp_path / 'modules', {'demo/router.py': source})
        (tmp_path / 'config.py').write_text('', encoding='utf-8')

        assert set(collect_module_surface_imports(root)['demo']) == {'app.config'}
        errors = _check_module_import_surface(root, baseline={})
        assert len(errors) == 1
        assert 'demo imports app.config' in errors[0]

    def test_a_bare_top_package_import_is_counted(self, tmp_path):
        root = _tree(tmp_path / 'modules', {'demo/router.py': 'import app\n'})

        assert set(collect_module_surface_imports(root)['demo']) == {'app'}
        assert len(_check_module_import_surface(root, baseline={})) == 1

    def test_a_bound_child_module_is_the_reach_not_its_package(self, tmp_path):
        """``from app.core import db_facade`` reaches app.core.db_facade."""
        root = _tree(
            tmp_path / 'modules',
            {'demo/router.py': 'from app.core import db_facade\n'},
        )
        (tmp_path / 'core').mkdir()
        (tmp_path / 'core' / 'db_facade.py').write_text('', encoding='utf-8')

        assert set(collect_module_surface_imports(root)['demo']) == {
            'app.core.db_facade'
        }

    def test_a_symbol_from_a_package_init_stays_that_package(self, tmp_path):
        """A name that is not a child module is an attribute, not a new path."""
        root = _tree(
            tmp_path / 'modules', {'demo/router.py': 'from app.core import something\n'}
        )
        (tmp_path / 'core').mkdir()
        (tmp_path / 'core' / '__init__.py').write_text(
            'something = 1\n', encoding='utf-8'
        )

        assert set(collect_module_surface_imports(root)['demo']) == {'app.core'}

    def test_test_files_are_not_scanned(self, tmp_path):
        root = _tree(
            tmp_path / 'modules',
            {'demo/tests/test_x.py': 'from app.core.deps import x\n'},
        )

        assert collect_module_surface_imports(root) == {'demo': {}}

    def test_the_warehouse_module_reaches_nothing_behind_the_surface(self):
        """The worked example imports Core only through the declared door.

        Its models share Core's declarative base (through the SDK), its data
        reads go over ``core_api``, its DTOs and vocabularies over
        ``contracts`` and its models' migration environment over the SDK.
        A join on a Core table would be a new path in the baseline — and the
        baseline has none of them for this module.
        """
        live = collect_module_surface_imports(MODULES_ROOT)

        behind_the_surface = {
            path
            for path in live['warehouse']
            if path == 'app'
            or path.startswith(
                ('app.models', 'app.database', 'app.services', 'app.schemas', 'app.api')
            )
        }

        assert behind_the_surface == set()


@pytest.mark.unit
class TestTheCommittedList:
    def test_the_baseline_parses_and_has_not_expired(self):
        modules, errors = _load_module_import_surface_baseline()

        assert errors == []
        assert modules, 'the baseline lists no module — the gate covers nothing'

    def test_every_shipped_module_with_a_core_import_has_a_block(self):
        live = collect_module_surface_imports(MODULES_ROOT)
        modules, _ = _load_module_import_surface_baseline()

        reaching = {module for module, paths in live.items() if paths}

        assert reaching - set(modules) == set()

    def test_the_tree_matches_the_committed_list(self):
        modules, _ = _load_module_import_surface_baseline()

        assert _check_module_import_surface(MODULES_ROOT, modules) == []


@pytest.mark.unit
def test_an_expired_block_fails(tmp_path, monkeypatch):
    """A decision that never comes back is how a gap goes quiet."""
    baseline = tmp_path / 'module_import_surface_baseline.txt'
    baseline.write_text(
        'demo | owner=core | expires=2020-01-01 | because the demo module is old\n'
        '  app.core.deps\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(
        'app.core.architecture_lint._baselines.MODULE_IMPORT_SURFACE_BASELINE_FILE',
        baseline,
    )

    modules, errors = _load_module_import_surface_baseline()

    assert modules == {}
    assert len(errors) == 1
    assert 'expired' in errors[0]


@pytest.mark.unit
def test_a_reason_is_mandatory(tmp_path, monkeypatch):
    baseline = tmp_path / 'module_import_surface_baseline.txt'
    baseline.write_text('demo | owner=core | expires=2099-01-01 |\n', encoding='utf-8')
    monkeypatch.setattr(
        'app.core.architecture_lint._baselines.MODULE_IMPORT_SURFACE_BASELINE_FILE',
        baseline,
    )

    modules, errors = _load_module_import_surface_baseline()

    assert modules == {}
    assert len(errors) == 1
    assert 'malformed' in errors[0]


@pytest.mark.unit
def test_an_owner_is_mandatory(tmp_path, monkeypatch):
    baseline = tmp_path / 'module_import_surface_baseline.txt'
    baseline.write_text(
        'demo | nobody | expires=2099-01-01 | because it is old\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(
        'app.core.architecture_lint._baselines.MODULE_IMPORT_SURFACE_BASELINE_FILE',
        baseline,
    )

    modules, errors = _load_module_import_surface_baseline()

    assert modules == {}
    assert len(errors) == 1
    assert 'without owner' in errors[0]


@pytest.mark.unit
def test_a_path_without_a_module_line_fails(tmp_path, monkeypatch):
    baseline = tmp_path / 'module_import_surface_baseline.txt'
    baseline.write_text('  app.core.deps\n', encoding='utf-8')
    monkeypatch.setattr(
        'app.core.architecture_lint._baselines.MODULE_IMPORT_SURFACE_BASELINE_FILE',
        baseline,
    )

    modules, errors = _load_module_import_surface_baseline()

    assert modules == {}
    assert len(errors) == 1
    assert 'without a module' in errors[0]


@pytest.mark.unit
def test_an_unreadable_expiry_fails(tmp_path, monkeypatch):
    baseline = tmp_path / 'module_import_surface_baseline.txt'
    baseline.write_text(
        'demo | owner=core | expires=soon | because it is old\n', encoding='utf-8'
    )
    monkeypatch.setattr(
        'app.core.architecture_lint._baselines.MODULE_IMPORT_SURFACE_BASELINE_FILE',
        baseline,
    )

    modules, errors = _load_module_import_surface_baseline()

    assert modules == {}
    assert len(errors) == 1
    assert 'unreadable expiry' in errors[0]


@pytest.mark.unit
def test_an_entry_without_an_expiry_fails(tmp_path, monkeypatch):
    baseline = tmp_path / 'module_import_surface_baseline.txt'
    baseline.write_text(
        'demo | owner=core | forever | because it is old\n', encoding='utf-8'
    )
    monkeypatch.setattr(
        'app.core.architecture_lint._baselines.MODULE_IMPORT_SURFACE_BASELINE_FILE',
        baseline,
    )

    modules, errors = _load_module_import_surface_baseline()

    assert modules == {}
    assert len(errors) == 1
    assert 'without expiry' in errors[0]


@pytest.mark.unit
def test_the_committed_file_is_the_one_the_lint_reads():
    """A path constant that drifted from the committed file would read an empty list."""
    assert MODULE_IMPORT_SURFACE_BASELINE_FILE.is_file()
    assert MODULE_IMPORT_SURFACE_BASELINE_FILE == (
        MODULES_ROOT.parent / 'core' / 'module_import_surface_baseline.txt'
    )
