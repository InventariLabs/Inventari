import ast
from pathlib import Path

import pytest

from app.core.architecture_lint import (
    _check_module_migrations_exist,
    _check_sync_async_function_pairs,
    _is_cross_module_import_whitelisted,
    find_api_layer_import_violations,
    find_module_boundary_violations,
)
from app.core.architecture_lint import _main as lint_main
from app.core.architecture_lint._constants import _rel
from app.core.architecture_lint._main import (
    _BASELINED_SUMMARY,
    _emit_baselined,
    _print_baselined_counts,
)
from app.core.architecture_lint._quality_checks import (
    _check_coreapi_async_naming,
    _check_coreapi_signature_legality,
    _check_public_api_return_types,
    _check_services_escape_hatch_marker,
    _check_sync_async_function_twins,
    _check_toctou_risk,
    _collect_module_tablenames,
    _extract_tablenames,
    _list_version_files,
)
from app.core.architecture_lint._quality_checks_modules import (
    _check_cross_module_imports,
)


def test_architecture_lint_reports_forbidden_imports(tmp_path):
    modules_root = tmp_path / 'modules'
    modules_root.mkdir()

    violating_file = modules_root / 'example.py'
    violating_file.write_text(
        'from app.models.item import Item\nfrom app.database import get_db\n',
        encoding='utf-8',
    )

    violations, escape_hatch_files = find_module_boundary_violations(
        modules_root, baseline_file=None
    )

    assert len(violations) == 2
    import_paths = {v.import_path for v in violations}
    assert 'app.models.item' in import_paths
    assert 'app.database' in import_paths
    assert escape_hatch_files == []


def test_a_migration_env_is_neither_a_violation_nor_an_l2_bypass(tmp_path):
    """``migrations/env.py`` imports the metadata for Alembic and nothing
    else: it needs no marker, and must not be counted as a read bypass."""
    modules_root = tmp_path / 'modules'
    (modules_root / 'widgets' / 'migrations').mkdir(parents=True)
    (modules_root / 'widgets' / 'migrations' / 'env.py').write_text(
        'from app.database import Base\n', encoding='utf-8'
    )

    violations, escape_hatch_files = find_module_boundary_violations(
        modules_root, baseline_file=None
    )

    assert violations == []
    assert escape_hatch_files == []


def test_a_migration_version_file_is_still_scanned(tmp_path):
    modules_root = tmp_path / 'modules'
    versions = modules_root / 'widgets' / 'migrations' / 'versions'
    versions.mkdir(parents=True)
    (versions / '0001_init.py').write_text(
        'from app.models.item import Item\n', encoding='utf-8'
    )

    violations, _ = find_module_boundary_violations(modules_root, baseline_file=None)

    assert [v.import_path for v in violations] == ['app.models.item']


def test_architecture_lint_ignores_allowed_imports(tmp_path):
    modules_root = tmp_path / 'modules'
    modules_root.mkdir()

    safe_file = modules_root / 'safe.py'
    safe_file.write_text(
        'from app.core.public_api import core_api\nfrom app.core.contracts import ItemDTO\n',
        encoding='utf-8',
    )

    violations, escape_hatch_files = find_module_boundary_violations(
        modules_root, baseline_file=None
    )

    assert violations == []
    assert escape_hatch_files == []


def test_architecture_lint_ignores_entries_from_baseline(tmp_path):
    modules_root = tmp_path / 'modules'
    modules_root.mkdir()

    violating_file = modules_root / 'example.py'
    violating_file.write_text('from app.models.item import Item\n', encoding='utf-8')

    baseline_file = tmp_path / 'baseline.txt'
    baseline_file.write_text('modules/example.py::app.models.item\n', encoding='utf-8')

    violations, _ = find_module_boundary_violations(
        modules_root,
        baseline_file=baseline_file,
    )

    assert violations == []


def test_architecture_lint_skips_test_files(tmp_path):
    modules_root = tmp_path / 'modules'
    (modules_root / 'tests').mkdir(parents=True)

    test_file = modules_root / 'tests' / 'test_example.py'
    test_file.write_text('from app.models.item import Item\n', encoding='utf-8')

    violations, _ = find_module_boundary_violations(modules_root, baseline_file=None)

    assert violations == []


def test_escape_hatch_with_valid_reason_skips_violations(tmp_path):
    modules_root = tmp_path / 'modules'
    modules_root.mkdir()

    service_file = modules_root / 'analytics_service.py'
    service_file.write_text(
        '# architecture: allow_direct_db_access\n'
        '# reason: Complex GROUP BY aggregation across three tables required for stats\n'
        'from app.models.item import Item\n',
        encoding='utf-8',
    )

    violations, escape_hatch_files = find_module_boundary_violations(
        modules_root, baseline_file=None
    )

    assert violations == []
    assert len(escape_hatch_files) == 1
    assert 'Complex GROUP BY' in escape_hatch_files[0][1]


@pytest.mark.parametrize(
    'source',
    [
        pytest.param(
            '# architecture: allow_direct_db_access\nfrom app.models.item import Item\n',
            id='no-reason',
        ),
        pytest.param(
            '# architecture: allow_direct_db_access\n'
            '# reason: because needed\n'
            'from app.models.item import Item\n',
            id='reason-too-short',
        ),
        pytest.param(
            '# architecture: allow_direct_db_access\n'
            '# reason: Complex multi-join aggregation for analytics reporting dashboard\n'
            'from app.models.item import Item\n'
            '\ndef save(db, item):\n'
            '    db.add(item)\n'
            '    db.commit()\n',
            id='commit-under-the-marker',
        ),
    ],
)
def test_a_malformed_escape_hatch_exits(tmp_path, source):
    modules_root = tmp_path / 'modules'
    modules_root.mkdir()
    (modules_root / 'bad_service.py').write_text(source, encoding='utf-8')

    with pytest.raises(SystemExit) as exc_info:
        find_module_boundary_violations(modules_root, baseline_file=None)

    assert exc_info.value.code == 1


def test_model_files_are_excluded(tmp_path):
    modules_root = tmp_path / 'modules'
    modules_root.mkdir()

    model_file = modules_root / 'models.py'
    model_file.write_text(
        'from app.database import Base\nfrom app.models.user import User\n',
        encoding='utf-8',
    )

    violations, hatch_files = find_module_boundary_violations(
        modules_root, baseline_file=None
    )

    assert violations == []
    assert hatch_files == []


def test_module_local_db_writes_are_auto_approved(tmp_path):
    modules_root = tmp_path / 'modules'
    modules_root.mkdir()

    service_file = modules_root / 'my_service.py'
    service_file.write_text(
        'from app.modules.mymodule.models import MyModel\n'
        'from sqlalchemy.orm import Session\n'
        '\n'
        'def save(db: Session, obj: MyModel):\n'
        '    db.add(obj)\n'
        '    db.commit()\n',
        encoding='utf-8',
    )

    violations, escape_hatch_files = find_module_boundary_violations(
        modules_root, baseline_file=None
    )

    assert violations == []
    assert escape_hatch_files == []


def test_l3_marker_is_no_longer_recognized(tmp_path):
    modules_root = tmp_path / 'modules'
    modules_root.mkdir()

    service_file = modules_root / 'write_service.py'
    service_file.write_text(
        '# architecture: allow_db_read_write\n'
        '# reason: Module local table writes for creating and updating records\n'
        '# allowed_tables: MyModel\n'
        'from app.models.item import Item\n',
        encoding='utf-8',
    )

    violations, escape_hatch_files = find_module_boundary_violations(
        modules_root, baseline_file=None
    )

    assert len(violations) == 1
    assert violations[0].import_path == 'app.models.item'
    assert escape_hatch_files == []


def test_api_layer_import_violations_detect_models(tmp_path):
    api_root = tmp_path / 'api'
    api_root.mkdir()

    (api_root / 'users.py').write_text(
        'from app.models.user import User\n', encoding='utf-8'
    )
    (api_root / 'uploads.py').write_text(
        'from app.models.item import Item\n'
        'from app.models.item_attachment import ItemAttachment\n',
        encoding='utf-8',
    )

    new, baselined = find_api_layer_import_violations(api_root, baseline_file=None)

    assert len(new) == 3
    assert baselined == []
    paths = {v.import_path for v in new}
    assert paths == {
        'app.models.user',
        'app.models.item',
        'app.models.item_attachment',
    }


def test_api_layer_import_violations_detect_database(tmp_path):
    api_root = tmp_path / 'api'
    api_root.mkdir()

    (api_root / 'products.py').write_text(
        'from app.database import ProductsSessionLocal\n', encoding='utf-8'
    )

    new, baselined = find_api_layer_import_violations(api_root, baseline_file=None)

    assert len(new) == 1
    assert new[0].import_path == 'app.database'


def test_api_layer_import_violations_baseline_filters(tmp_path):
    api_root = tmp_path / 'api'
    api_root.mkdir()

    (api_root / 'users.py').write_text(
        'from app.models.user import User\n', encoding='utf-8'
    )
    (api_root / 'uploads.py').write_text(
        'from app.models.item import Item\n', encoding='utf-8'
    )

    baseline_file = tmp_path / 'api_baseline.txt'
    baseline_file.write_text('api/users.py::app.models.user\n', encoding='utf-8')

    new, baselined = find_api_layer_import_violations(
        api_root, baseline_file=baseline_file
    )

    assert len(new) == 1
    assert new[0].import_path == 'app.models.item'
    assert len(baselined) == 1
    assert baselined[0].import_path == 'app.models.user'


def test_api_layer_import_violations_skip_test_files(tmp_path):
    api_root = tmp_path / 'api'
    (api_root / 'tests').mkdir(parents=True)

    (api_root / 'users.py').write_text(
        'from app.models.user import User\n', encoding='utf-8'
    )
    (api_root / 'tests' / 'test_users.py').write_text(
        'from app.models.user import User\n', encoding='utf-8'
    )

    new, _ = find_api_layer_import_violations(api_root, baseline_file=None)

    assert len(new) == 1
    assert new[0].file_path.name == 'users.py'


def test_api_layer_import_violations_allow_safe_imports(tmp_path):
    api_root = tmp_path / 'api'
    api_root.mkdir()

    (api_root / 'safe.py').write_text(
        'from app.core.public_api import core_api\n'
        'from app.core.contracts import UserDTO\n',
        encoding='utf-8',
    )

    new, baselined = find_api_layer_import_violations(api_root, baseline_file=None)

    assert new == []
    assert baselined == []


def test_api_layer_import_violations_skip_type_checking(tmp_path):
    """Imports inside `if TYPE_CHECKING:` blocks are allowed (type hints only)."""
    api_root = tmp_path / 'api'
    api_root.mkdir()

    (api_root / 'typed.py').write_text(
        'from __future__ import annotations\n'
        'from typing import TYPE_CHECKING\n'
        'if TYPE_CHECKING:\n'
        '    from app.models.user import User\n'
        '\n'
        'def get_user() -> "User | None":\n'
        '    return None\n',
        encoding='utf-8',
    )

    new, baselined = find_api_layer_import_violations(api_root, baseline_file=None)

    assert new == []
    assert baselined == []


@pytest.mark.parametrize(
    ('target', 'allowed'),
    [
        # The public door: `<module>_api`, plus the module's own
        # `exceptions` and `schemas`.
        pytest.param('app.modules.approvals.approvals_api', True, id='own-api-file'),
        pytest.param('app.modules.warehouse.warehouse_api', True, id='own-api-file-2'),
        pytest.param('app.modules.approvals.exceptions', True, id='exceptions'),
        pytest.param('app.modules.approvals.schemas', True, id='schemas'),
        # Everything else inside a module is private.
        pytest.param('app.modules.approvals.models', False, id='models'),
        pytest.param('app.modules.approvals.services', False, id='services'),
        pytest.param('app.modules.approvals.router', False, id='router'),
        # The contract names one door per module, not an `_api` naming habit:
        # the suffix alone used to be the whole test, so any file ending in
        # `_api` opened the module — including one named after somebody
        # else's.
        pytest.param(
            'app.modules.maker.secret_internal_api', False, id='api-suffix-only'
        ),
        pytest.param('app.modules.maker.warehouse_api', False, id='anothers-api-file'),
        # `exceptions` and `schemas` are the module's own, not any leaf so named.
        pytest.param(
            'app.modules.approvals.schemas.internal', False, id='below-schemas'
        ),
        pytest.param(
            'app.modules.approvals.sub.exceptions', False, id='nested-exceptions'
        ),
        # Only app.modules.* paths can be whitelisted.
        pytest.param('app.core.public_api', False, id='core-api'),
        pytest.param('app.core.contracts.dtos', False, id='core-contracts'),
        pytest.param('app.services.items.query_service', False, id='legacy-services'),
        pytest.param('app.models', False, id='too-short-models'),
        pytest.param('app', False, id='too-short-app'),
    ],
)
def test_the_cross_module_whitelist_judges_an_import_target(target, allowed):
    assert _is_cross_module_import_whitelisted(target) is allowed


def test_cross_module_check_reads_plain_import_too(tmp_path):
    """`import app.modules.X.Y` reaches as far as `from app.modules.X.Y import`.

    Red before the fix on exactly this line: the check only ever looked at
    `ast.ImportFrom`, so the one import form that needs no `from` walked
    through a gate that stopped lazy imports, aliases and TYPE_CHECKING
    blocks alike.
    """
    modules_root = tmp_path / 'modules'
    (modules_root / 'stats').mkdir(parents=True)
    (modules_root / 'maker').mkdir(parents=True)
    (modules_root / 'stats' / 'services.py').write_text(
        'import app.modules.maker.bom_tree\n', encoding='utf-8'
    )

    errors = _check_cross_module_imports(modules_root)

    assert len(errors) == 1
    assert 'app.modules.maker.bom_tree' in errors[0]
    assert errors[0].startswith('::error')


def test_cross_module_check_allows_the_public_door_either_way(tmp_path):
    """Both import forms pass when they name the target module's own API.

    Green on the old check too, for a different reason: the plain `import`
    half was invisible to it, not approved by it.
    """
    modules_root = tmp_path / 'modules'
    (modules_root / 'stats').mkdir(parents=True)
    (modules_root / 'maker').mkdir(parents=True)
    (modules_root / 'stats' / 'services.py').write_text(
        'import app.modules.maker.maker_api\n'
        'from app.modules.maker.maker_api import build\n',
        encoding='utf-8',
    )

    assert _check_cross_module_imports(modules_root) == []


def test_cross_module_check_rejects_a_borrowed_api_name(tmp_path):
    """A file inside maker named after another module is not maker's door."""
    modules_root = tmp_path / 'modules'
    (modules_root / 'stats').mkdir(parents=True)
    (modules_root / 'maker').mkdir(parents=True)
    (modules_root / 'stats' / 'services.py').write_text(
        'from app.modules.maker.secret_internal_api import thing\n', encoding='utf-8'
    )

    errors = _check_cross_module_imports(modules_root)

    assert len(errors) == 1
    assert 'secret_internal_api' in errors[0]


def test_a_mixed_statement_is_judged_name_by_name(tmp_path):
    """A door and a private file bound by one statement are judged apart.

    The first cut of the door rule silenced the WHOLE statement when any
    bound name was a whitelisted door — `from app.modules.other import
    other_api, services` walked the private file through under the door's
    name. Red before the per-name fix: zero findings on this statement.
    """
    modules_root = tmp_path / 'modules'
    other = modules_root / 'other'
    me = modules_root / 'me'
    other.mkdir(parents=True)
    me.mkdir(parents=True)
    (other / 'other_api.py').write_text('api = 1\n', encoding='utf-8')
    (other / 'services.py').write_text('VALUE = 1\n', encoding='utf-8')
    (me / 'mine.py').write_text(
        'from app.modules.other import other_api, services\n'
        'from ..other import other_api, services\n',
        encoding='utf-8',
    )

    findings = _check_cross_module_imports(modules_root)

    assert len(findings) == 2
    quoted = [f.split('Import of ')[1].split("'")[1] for f in findings]
    assert sorted(quoted) == [
        'app.modules.other.services',
        'app.modules.other.services',
    ]


def test_the_prefix_is_derived_from_the_root_the_check_is_handed(tmp_path):
    """A modules root under another name gets its own package name.

    The check takes the root as a parameter but used to assume its name:
    relative climbs resolved against ('app', 'modules') and findings
    named the wrong package. Red before the fix: this finding named
    `app.modules.other.services`.
    """
    modules_root = tmp_path / 'plugins'
    other = modules_root / 'other'
    me = modules_root / 'me'
    other.mkdir(parents=True)
    me.mkdir(parents=True)
    (other / 'services.py').write_text('VALUE = 1\n', encoding='utf-8')
    (me / 'mine.py').write_text('from ..other.services import VALUE\n')

    findings = _check_cross_module_imports(modules_root)

    assert len(findings) == 1
    assert 'app.plugins.other.services' in findings[0]


@pytest.mark.parametrize(
    ('source', 'named'),
    [
        # Relative spellings resolve against the file's own package, so each
        # names the same crossing as its absolute twin; the dots and the
        # named module are one address. Red before the relative branch was
        # resolved: a climb to bare `app.modules` dropped the bound names
        # and the gate exited 0 with a live crossing in the tree.
        pytest.param(
            'from ...modules import warehouse\n',
            'app.modules.warehouse',
            id='relative-climb',
        ),
        pytest.param(
            'from ...modules import warehouse as d\n',
            'app.modules.warehouse',
            id='climb-with-alias',
        ),
        pytest.param(
            'from ..other.services import VALUE\n',
            'app.modules.other.services',
            id='relative-into-module',
        ),
        pytest.param(
            'from ..other import services\n', 'app.modules.other', id='relative-package'
        ),
        pytest.param(
            'from app.modules import other\n',
            'app.modules.other',
            id='package-root-grab',
        ),
        pytest.param(
            'from ...modules.other.services import VALUE\n',
            'app.modules.other.services',
            id='climb-over-root',
        ),
    ],
)
def test_an_import_that_reaches_another_module_is_an_error(
    tmp_path, monkeypatch, source, named
):
    monkeypatch.chdir(tmp_path)
    modules_root = _two_modules(tmp_path, source)

    findings = _check_cross_module_imports(modules_root)

    assert len(findings) == 1
    assert named in findings[0]


def test_a_climb_from_a_nested_file_reaches_the_modules_package_too(
    tmp_path, monkeypatch
):
    """One package deeper than the sibling test: `....modules` from
    `me/sub/deep.py` climbs back to the same address and binds the same
    children — depth buys nothing."""
    monkeypatch.chdir(tmp_path)
    modules_root = tmp_path / 'modules'
    other = modules_root / 'other'
    deep = modules_root / 'me' / 'sub'
    other.mkdir(parents=True)
    deep.mkdir(parents=True)
    (other / 'services.py').write_text('VALUE = 1\n', encoding='utf-8')
    (deep / 'deep.py').write_text('from ....modules import other\n', encoding='utf-8')

    findings = _check_cross_module_imports(modules_root)

    assert len(findings) == 1
    assert 'app.modules.other' in findings[0]


def test_a_relative_climb_that_names_the_own_module_passes(tmp_path, monkeypatch):
    """`from ...modules import me` from inside me resolves to me's own
    package. Green before the fix too — but for the wrong reason: the
    judge never saw the address at all. After the fix it is green because
    the resolved target is the importer itself.
    """
    monkeypatch.chdir(tmp_path)
    modules_root = _two_modules(tmp_path, 'from ...modules import me\n')

    assert _check_cross_module_imports(modules_root) == []


def test_a_two_part_import_of_the_public_door_is_not_a_finding(tmp_path):
    """`from app.modules.other import other_api` names the sanctioned door
    file, but the judge saw only the package address — too short for the
    whitelist — and fired on correct code. Every relative spelling of the
    same statement was invisible before this gate widened, so the first
    author writing the door two-part would have been refused on legal
    imports. The statement is judged by what it can name.
    """
    modules_root = tmp_path / 'modules'
    other = modules_root / 'other'
    me = modules_root / 'me'
    other.mkdir(parents=True)
    me.mkdir(parents=True)
    (other / 'other_api.py').write_text('api = 1\n', encoding='utf-8')
    (me / 'mine.py').write_text(
        'from app.modules.other import other_api\n'
        'from ..other import other_api\n'
        'from ...modules.other import other_api\n',
        encoding='utf-8',
    )

    assert _check_cross_module_imports(modules_root) == []


def test_a_two_part_import_of_an_inner_file_is_still_an_error(tmp_path):
    """Opening the door form for `other_api` must not open it for the
    module's private files: the bound alias, not the package, decides.
    """
    modules_root = tmp_path / 'modules'
    other = modules_root / 'other'
    me = modules_root / 'me'
    other.mkdir(parents=True)
    me.mkdir(parents=True)
    (other / 'services.py').write_text('VALUE = 1\n', encoding='utf-8')
    (me / 'mine.py').write_text('from app.modules.other import services\n')

    findings = _check_cross_module_imports(modules_root)

    assert len(findings) == 1
    assert 'app.modules.other' in findings[0]


def _two_modules(tmp_path, importing_source):
    """modules/me importing from modules/other, with a real target file."""
    modules_root = tmp_path / 'modules'
    other = modules_root / 'other'
    me = modules_root / 'me'
    (other / 'tests').mkdir(parents=True)
    me.mkdir(parents=True)
    (other / 'services.py').write_text('VALUE = 1\n', encoding='utf-8')
    (me / 'mine.py').write_text(importing_source, encoding='utf-8')
    return modules_root


def test_a_cross_module_import_outside_the_contract_is_an_error(tmp_path, monkeypatch):
    """A leak into a sibling module's private service must fail the gate.

    The finding is an ``::error`` annotation, not a ``::warning``: the gate
    used to print the leak and still exit 0, so the boundary held by
    discipline, not by the check.
    """
    monkeypatch.chdir(tmp_path)
    modules_root = _two_modules(
        tmp_path, 'from app.modules.other.services import VALUE\n'
    )

    findings = _check_cross_module_imports(modules_root)

    assert len(findings) == 1
    assert findings[0].startswith('::error file=')
    assert 'line=1' in findings[0]
    assert 'app.modules.other.services' in findings[0]


def test_imports_on_the_public_contract_are_not_findings(tmp_path, monkeypatch):
    """<module>_api, .exceptions and .schemas are the sanctioned surface."""
    monkeypatch.chdir(tmp_path)
    modules_root = _two_modules(
        tmp_path,
        'from app.modules.other.other_api import api\n'
        'from app.modules.other.exceptions import OtherError\n'
        'from app.modules.other.schemas import OtherDTO\n',
    )
    (tmp_path / 'modules' / 'other' / 'other_api.py').write_text('api = 1\n')
    (tmp_path / 'modules' / 'other' / 'exceptions.py').write_text('OtherError = 1\n')
    (tmp_path / 'modules' / 'other' / 'schemas.py').write_text('OtherDTO = 1\n')

    assert _check_cross_module_imports(modules_root) == []


def test_a_relative_import_inside_the_owner_is_not_an_edge(tmp_path, monkeypatch):
    """`from .helpers import VALUE` stays inside the module that wrote it."""
    monkeypatch.chdir(tmp_path)
    modules_root = _two_modules(tmp_path, 'from .helpers import VALUE\n')
    (tmp_path / 'modules' / 'me' / 'helpers.py').write_text('VALUE = 1\n')

    assert _check_cross_module_imports(modules_root) == []


def test_sync_async_module_level_pair_is_flagged(tmp_path):
    """Module-level free functions with the same name (sync + async) are flagged."""
    (tmp_path / 'svc.py').write_text(
        'def get_data():\n    return []\n\n\nasync def get_data():\n    return []\n',
        encoding='utf-8',
    )

    warnings = _check_sync_async_function_pairs(tmp_path)

    assert len(warnings) == 1
    assert 'get_data' in warnings[0]


def test_sync_async_methods_in_separate_classes_not_flagged(tmp_path):
    """Parallel sync/async wrapper classes mirroring method names are allowed.

    Regression guard for the scoped_session pattern: ``ModuleScopedSession``
    (sync) and ``AsyncModuleScopedSession`` (async) intentionally expose the
    same method names. The old ``ast.walk``-based check flattened every class
    and falsely flagged this legitimate mirrored API.
    """
    (tmp_path / 'scoped.py').write_text(
        'class ModuleScopedSession:\n'
        '    def commit(self):\n        pass\n'
        '    def get(self, model, pk):\n        return None\n\n'
        'class AsyncModuleScopedSession:\n'
        '    async def commit(self):\n        pass\n'
        '    async def get(self, model, pk):\n        return None\n',
        encoding='utf-8',
    )

    warnings = _check_sync_async_function_pairs(tmp_path)

    assert warnings == []


# ---------------------------------------------------------------------------
# Module migration checks (_check_module_migrations_exist)
#
# Regression coverage for the two bugs fixed when module migrations were
# extracted from the core baseline:
#   Bug A — empty versions/ directory was not detected
#   Bug B — models/ package (vs single models.py) was not scanned
# ---------------------------------------------------------------------------

_MODELS_PY = "class Foo:\n    __tablename__ = 'foo'\n"

_MODELS_PKG_INNER = "class Bar:\n    __tablename__ = 'bar'\n"


def _make_module_with_models_py(modules_root, name='mymod'):
    module_dir = modules_root / name
    module_dir.mkdir(parents=True)
    (module_dir / 'models.py').write_text(_MODELS_PY, encoding='utf-8')
    return module_dir


def _make_module_with_models_pkg(modules_root, name='mymod'):
    module_dir = modules_root / name
    pkg = module_dir / 'models'
    pkg.mkdir(parents=True)
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'inner.py').write_text(_MODELS_PKG_INNER, encoding='utf-8')
    return module_dir


def test_migration_check_flags_empty_versions_for_models_py(tmp_path):
    """Bug A: models.py with migrations/ but empty versions/ -> ::error."""
    modules_root = tmp_path / 'modules'
    module_dir = _make_module_with_models_py(modules_root)
    (module_dir / 'migrations' / 'versions').mkdir(parents=True)

    errors = _check_module_migrations_exist(modules_root)

    assert len(errors) == 1
    assert '::error' in errors[0]
    assert 'Empty module migrations' in errors[0]
    assert "'mymod'" in errors[0]
    assert 'foo' in errors[0]


def test_migration_check_flags_empty_versions_for_models_pkg(tmp_path):
    """Bug B: models/ package with migrations/ but empty versions/ -> ::error."""
    modules_root = tmp_path / 'modules'
    module_dir = _make_module_with_models_pkg(modules_root)
    (module_dir / 'migrations' / 'versions').mkdir(parents=True)

    errors = _check_module_migrations_exist(modules_root)

    assert len(errors) == 1
    assert '::error' in errors[0]
    assert "'mymod'" in errors[0]
    assert 'bar' in errors[0]


def test_migration_check_flags_missing_migrations_dir_for_models_py(tmp_path):
    """models.py with tables but no migrations/ directory -> ::error."""
    modules_root = tmp_path / 'modules'
    _make_module_with_models_py(modules_root)

    errors = _check_module_migrations_exist(modules_root)

    assert len(errors) == 1
    assert '::error' in errors[0]
    assert 'no migrations/ directory' in errors[0]


def test_migration_check_flags_missing_migrations_dir_for_models_pkg(tmp_path):
    """models/ package with tables but no migrations/ directory -> ::error."""
    modules_root = tmp_path / 'modules'
    _make_module_with_models_pkg(modules_root)

    errors = _check_module_migrations_exist(modules_root)

    assert len(errors) == 1
    assert '::error' in errors[0]
    assert 'no migrations/ directory' in errors[0]


def test_migration_check_passes_when_versions_has_migration(tmp_path):
    """Module with models.py AND versions/001_initial.py -> no error."""
    modules_root = tmp_path / 'modules'
    module_dir = _make_module_with_models_py(modules_root)
    versions_dir = module_dir / 'migrations' / 'versions'
    versions_dir.mkdir(parents=True)
    (versions_dir / '001_initial.py').write_text(
        'revision = "001_initial"\n', encoding='utf-8'
    )

    errors = _check_module_migrations_exist(modules_root)

    assert errors == []


def test_migration_check_skips_module_without_tables(tmp_path):
    """Module with models.py but no __tablename__ -> skipped."""
    modules_root = tmp_path / 'modules'
    module_dir = modules_root / 'notables'
    module_dir.mkdir(parents=True)
    (module_dir / 'models.py').write_text('class Config:\n    pass\n', encoding='utf-8')

    errors = _check_module_migrations_exist(modules_root)

    assert errors == []


def test_migration_check_baselined_module_emits_notice(tmp_path):
    """Baselined module with empty versions/ -> ::notice (not ::error)."""
    modules_root = tmp_path / 'modules'
    module_dir = _make_module_with_models_py(modules_root, name='grandfathered')
    (module_dir / 'migrations' / 'versions').mkdir(parents=True)

    errors = _check_module_migrations_exist(
        modules_root, baseline_modules={'grandfathered'}
    )

    assert len(errors) == 1
    assert '::notice' in errors[0]
    assert '::error' not in errors[0]


def test_migration_check_baselined_missing_migrations_emits_notice(tmp_path):
    """Baselined module without migrations/ dir -> ::notice (not ::error)."""
    modules_root = tmp_path / 'modules'
    _make_module_with_models_py(modules_root, name='grandfathered')

    errors = _check_module_migrations_exist(
        modules_root, baseline_modules={'grandfathered'}
    )

    assert len(errors) == 1
    assert '::notice' in errors[0]
    assert '::error' not in errors[0]


def test_migration_check_multiple_modules_mixed_states(tmp_path):
    """Integration: multiple modules in different states are reported correctly."""
    modules_root = tmp_path / 'modules'

    # Module A: good — has migration
    good = _make_module_with_models_py(modules_root, name='good_mod')
    versions_a = good / 'migrations' / 'versions'
    versions_a.mkdir(parents=True)
    (versions_a / '001_initial.py').write_text('revision="x"\n', encoding='utf-8')

    # Module B: bad — empty versions/ (not baselined)
    bad = _make_module_with_models_py(modules_root, name='bad_mod')
    (bad / 'migrations' / 'versions').mkdir(parents=True)

    # Module C: baselined — empty versions/ (in baseline)
    baselined = _make_module_with_models_py(modules_root, name='baselined_mod')
    (baselined / 'migrations' / 'versions').mkdir(parents=True)

    errors = _check_module_migrations_exist(
        modules_root, baseline_modules={'baselined_mod'}
    )

    assert len(errors) == 2
    severities = [e.split('::')[1].split(' ')[0] for e in errors]
    assert 'error' in severities
    assert 'notice' in severities
    bad_msg = next(e for e in errors if 'bad_mod' in e)
    baselined_msg = next(e for e in errors if 'baselined_mod' in e)
    assert '::error' in bad_msg
    assert '::notice' in baselined_msg


def test_migration_check_skips_underscore_directories(tmp_path):
    """Directories starting with '_' are skipped (e.g. __pycache__)."""
    modules_root = tmp_path / 'modules'
    modules_root.mkdir(parents=True)
    (modules_root / '_internal').mkdir()
    (modules_root / '_internal' / 'models.py').write_text(_MODELS_PY, encoding='utf-8')

    errors = _check_module_migrations_exist(modules_root)

    assert errors == []


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


def test_extract_tablenames_returns_empty_for_no_tables(tmp_path):
    """_extract_tablenames returns empty set when no __tablename__ present."""
    f = tmp_path / 'models.py'
    f.write_text('class C:\n    pass\n', encoding='utf-8')

    assert _extract_tablenames(f) == set()


def test_extract_tablenames_finds_multiple(tmp_path):
    """_extract_tablenames finds all __tablename__ assignments."""
    f = tmp_path / 'models.py'
    f.write_text(
        "class A:\n    __tablename__ = 'table_a'\n"
        "class B:\n    __tablename__ = 'table_b'\n",
        encoding='utf-8',
    )

    assert _extract_tablenames(f) == {'table_a', 'table_b'}


def test_extract_tablenames_skips_dynamic_assignment(tmp_path):
    """_extract_tablenames only matches literal string assignments."""
    f = tmp_path / 'models.py'
    f.write_text(
        'class A:\n    __tablename__ = get_name()  # dynamic, not a literal\n',
        encoding='utf-8',
    )

    assert _extract_tablenames(f) == set()


def test_collect_module_tablenames_from_package(tmp_path):
    """_collect_module_tablenames reads models/ package recursively."""
    module_dir = tmp_path / 'mymod'
    pkg = module_dir / 'models'
    pkg.mkdir(parents=True)
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'a.py').write_text(
        "class A:\n    __tablename__ = 'tbl_a'\n", encoding='utf-8'
    )
    (pkg / 'sub').mkdir()
    (pkg / 'sub' / 'b.py').write_text(
        "class B:\n    __tablename__ = 'tbl_b'\n", encoding='utf-8'
    )

    tables = _collect_module_tablenames(module_dir)

    assert tables == {'tbl_a', 'tbl_b'}


def test_collect_module_tablenames_from_single_file(tmp_path):
    """_collect_module_tablenames reads single models.py file."""
    module_dir = tmp_path / 'mymod'
    module_dir.mkdir()
    (module_dir / 'models.py').write_text(
        "class X:\n    __tablename__ = 'tbl_x'\n", encoding='utf-8'
    )

    tables = _collect_module_tablenames(module_dir)

    assert tables == {'tbl_x'}


def test_list_version_files_excludes_init(tmp_path):
    """_list_version_files excludes __init__.py from the listing."""
    versions = tmp_path / 'versions'
    versions.mkdir()
    (versions / '__init__.py').write_text('', encoding='utf-8')
    (versions / '001_initial.py').write_text('revision="x"\n', encoding='utf-8')
    (versions / '002_add_col.py').write_text('revision="y"\n', encoding='utf-8')

    files = _list_version_files(versions)

    assert len(files) == 2
    assert all(f.name != '__init__.py' for f in files)


def test_list_version_files_empty_when_no_dir(tmp_path):
    """_list_version_files returns [] when versions/ doesn't exist."""
    assert _list_version_files(tmp_path / 'nonexistent') == []


# ── Non-Core DeclarativeBase detection (nutrition/OFFBase pattern) ──────────


def test_extract_tablenames_counts_own_declarative_base(tmp_path):
    """Own-DeclarativeBase tables count at the file level now.

    The walk used to exclude them because core Alembic does not track
    non-Core bases — which made the helper blind to every community
    module, since a community module may not import app.database and so
    every one of its models sits on a base of its own. The exclusion for
    genuinely separate-database models (nutrition's products db) lives at
    the module level now, keyed on the database seam the module imports,
    not on the base.
    """
    f = tmp_path / 'models.py'
    f.write_text(
        'from sqlalchemy.orm import DeclarativeBase\n'
        'class OFFBase(DeclarativeBase):\n'
        '    pass\n'
        'class OFFProductLocal(OFFBase):\n'
        "    __tablename__ = 'off_products_local'\n",
        encoding='utf-8',
    )

    assert _extract_tablenames(f) == {'off_products_local'}


def test_collect_excludes_own_base_when_the_module_targets_separate_db(
    tmp_path,
):
    """The nutrition shape outside the defining module: the models INHERIT
    the separate-database base (imported from where it is defined), so those
    tables stay out of the migration check — core Alembic will never track
    them. The products-engine import sits in the module too, and decides
    nothing: without the inheritance the tables would stay in the check's
    sight."""
    module = tmp_path / 'nutrition_like'
    module.mkdir()
    (module / 'module.py').write_text(
        'from app.core.db_facade import products_engine\n',
        encoding='utf-8',
    )
    (module / 'models.py').write_text(
        'from app.modules.nutrition.models import OFFBase\n'
        'from sqlalchemy.orm import Mapped, mapped_column\n'
        'class OFFProductLocal(OFFBase):\n'
        "    __tablename__ = 'off_products_local'\n"
        '    barcode: Mapped[str] = mapped_column(primary_key=True)\n',
        encoding='utf-8',
    )

    assert _collect_module_tablenames(module) == set()


def test_extract_tablenames_includes_core_base_subclass(tmp_path):
    """Tables on classes inheriting from Core Base are included."""
    f = tmp_path / 'models.py'
    f.write_text(
        'from app.database import Base\n'
        'class Widget(Base):\n'
        "    __tablename__ = 'widgets'\n",
        encoding='utf-8',
    )

    assert _extract_tablenames(f) == {'widgets'}


def test_extract_tablenames_includes_core_base_alias(tmp_path):
    """Core Base imported under an alias is still detected."""
    f = tmp_path / 'models.py'
    f.write_text(
        'from app.database import Base as CoreBase\n'
        'class Widget(CoreBase):\n'
        "    __tablename__ = 'widgets'\n",
        encoding='utf-8',
    )

    assert _extract_tablenames(f) == {'widgets'}


def test_extract_tablenames_mixed_core_and_own_base(tmp_path):
    """The walk counts a table on the Core ``Base`` and one on a base of the
    module's own: it is blind to which base the model inherits."""
    f = tmp_path / 'models.py'
    f.write_text(
        'from app.database import Base\n'
        'from sqlalchemy.orm import DeclarativeBase\n'
        'class MyOwn(DeclarativeBase):\n'
        '    pass\n'
        'class Widget(Base):\n'
        "    __tablename__ = 'widgets'\n"
        'class External(MyOwn):\n'
        "    __tablename__ = 'external_table'\n",
        encoding='utf-8',
    )

    assert _extract_tablenames(f) == {'widgets', 'external_table'}


def test_extract_tablenames_core_db_facade_source(tmp_path):
    """Core Base imported from app.core.db_facade is detected."""
    f = tmp_path / 'models.py'
    f.write_text(
        'from app.core.db_facade import Base\n'
        'class Thing(Base):\n'
        "    __tablename__ = 'things'\n",
        encoding='utf-8',
    )

    assert _extract_tablenames(f) == {'things'}


# ── Guardrail 1: sync/async function twins ──────────────────────────────────


class TestSyncAsyncTwinGuardrail:
    """Tests for _check_sync_async_function_twins."""

    def test_detects_twin_as_error(self, tmp_path):
        """A sync function + _async variant in the same file = error."""
        f = tmp_path / 'service.py'
        f.write_text(
            'def get_item():\n    pass\n\nasync def get_item_async():\n    pass\n',
            encoding='utf-8',
        )
        result = _check_sync_async_function_twins(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 1
        assert 'get_item_async() is a twin of get_item()' in errors[0]

    def test_baselined_twin_emits_notice(self, tmp_path):
        """A baselined twin emits ::notice, not ::error."""
        f = tmp_path / 'service.py'
        f.write_text(
            'def get_item():\n    pass\n\nasync def get_item_async():\n    pass\n',
            encoding='utf-8',
        )
        # Compute the actual key the linter will generate
        unbaselined = _check_sync_async_function_twins(tmp_path)
        assert unbaselined  # should find the twin
        # The baseline key is path::function_name — extract from the error
        twin_func = 'get_item_async'
        from app.core.architecture_lint._constants import _rel

        actual_key = f'{_rel(f)}::{twin_func}'
        result = _check_sync_async_function_twins(tmp_path, baseline={actual_key})
        errors = [r for r in result if r.startswith('::error')]
        notices = [r for r in result if r.startswith('::notice')]
        assert errors == []
        assert len(notices) == 1

    def test_no_twin_no_error(self, tmp_path):
        """A single async function with _async suffix is fine."""
        f = tmp_path / 'service.py'
        f.write_text(
            'async def get_item_async():\n    pass\n',
            encoding='utf-8',
        )
        result = _check_sync_async_function_twins(tmp_path)
        assert result == []

    def test_detects_a_pair_split_across_two_files(self, tmp_path):
        """The async door in one file driving a sync implementation in
        another (through db.run_sync) is the same twin — both halves get
        named, each under its own file. The import is what makes the two
        names one pair rather than a shared spelling."""
        service = tmp_path / 'metrics_service.py'
        service.write_text(
            'def get_timeline_sync():\n    return []\n',
            encoding='utf-8',
        )
        door = tmp_path / 'admin_api.py'
        door.write_text(
            'from metrics_service import get_timeline_sync\n\n'
            'async def get_timeline_async():\n'
            '    return await db.run_sync(get_timeline_sync)\n',
            encoding='utf-8',
        )
        result = _check_sync_async_function_twins(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        named = '\n'.join(errors)
        assert 'get_timeline_sync' in named
        assert 'get_timeline_async' in named
        assert 'metrics_service.py' in named
        assert 'admin_api.py' in named
        # No `get_timeline` exists, so the message names the halves that do.
        assert 'get_timeline_async() is a twin of get_timeline_sync()' in named
        assert 'get_timeline_sync() is a twin of get_timeline_async()' in named
        assert 'twin of get_timeline()' not in named

    @pytest.mark.parametrize(
        ('files', 'half'),
        [
            # `run_sync(lambda s: get_timeline_sync(s, days=days))` — the name
            # sits inside the lambda handed to the offload, which is the real
            # shape of the one cross-file pair in the corpus.
            pytest.param(
                {
                    'metrics_service.py': (
                        'def get_timeline_sync(session, *, days):\n    return []\n'
                    ),
                    'admin_api.py': (
                        'from metrics_service import get_timeline_sync\n\n'
                        'async def get_timeline_async(db, days):\n'
                        '    return await db.run_sync(\n'
                        '        lambda sync_sess: get_timeline_sync(sync_sess, days=days)\n'
                        '    )\n'
                    ),
                },
                'get_timeline',
                id='lambda-handed-to-the-offload',
            ),
            # Blocking work pushed to a thread pool —
            # `run_sync_in_thread(lambda: render_pdf_sync(html))` — is the same
            # drive relation under the other helper.
            pytest.param(
                {
                    'pdf_service.py': 'def render_pdf_sync(html):\n    return html\n',
                    'protocol_service.py': (
                        'from pdf_service import render_pdf_sync\n\n'
                        'async def render_pdf_async(html):\n'
                        '    return await run_sync_in_thread(lambda: render_pdf_sync(html))\n'
                    ),
                },
                'render_pdf',
                id='thread-offload-of-a-lambda',
            ),
        ],
    )
    def test_the_offload_may_carry_the_sibling_in_a_lambda(self, tmp_path, files, half):
        for name, source in files.items():
            (tmp_path / name).write_text(source, encoding='utf-8')
        result = _check_sync_async_function_twins(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 2
        named = '\n'.join(errors)
        assert f'{half}_sync' in named
        assert f'{half}_async' in named

    def test_app_prefixed_and_relative_imports_name_the_same_module(self, tmp_path):
        """`from app.services.x import foo` and, inside `services`,
        `from .x import foo` are the same import: the `app.` prefix is
        where the tree is rooted, not part of the name below it."""
        services = tmp_path / 'services'
        services.mkdir()
        (services / 'implementation.py').write_text(
            'def get_x_sync():\n    return []\n\ndef get_y_sync():\n    return []\n',
            encoding='utf-8',
        )
        (services / 'absolute.py').write_text(
            'from app.services.implementation import get_x_sync\n\n'
            'async def get_x_async(db):\n'
            '    return await db.run_sync(get_x_sync)\n',
            encoding='utf-8',
        )
        (services / 'relative.py').write_text(
            'from .implementation import get_y_sync\n\n'
            'async def get_y_async(db):\n'
            '    return await db.run_sync(get_y_sync)\n',
            encoding='utf-8',
        )
        result = _check_sync_async_function_twins(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 4
        named = '\n'.join(errors)
        assert 'get_x_async() is a twin of get_x_sync()' in named
        assert 'get_x_sync() is a twin of get_x_async()' in named
        assert 'get_y_async() is a twin of get_y_sync()' in named
        assert 'get_y_sync() is a twin of get_y_async()' in named

    @pytest.mark.parametrize(
        'files',
        [
            # `get_profile('food')` in the middle of an unrelated async
            # function names the same spelling and nothing else: importing a
            # module is not calling its function through the offload.
            pytest.param(
                {
                    'product_profiles.py': 'def get_profile(code):\n    return code\n',
                    'auth_service.py': (
                        'from product_profiles import get_profile\n\n'
                        'class AuthService:\n'
                        '    async def get_profile_async(self, user):\n'
                        '        return get_profile(user.profile_code)\n'
                    ),
                },
                id='a-call-that-is-not-an-offload',
            ),
            # A local bound to the same spelling is not a call to another
            # module's function — the check reads calls, not vocabulary.
            pytest.param(
                {
                    'product_profiles.py': 'def get_profile(code):\n    return code\n',
                    'auth_service.py': (
                        'class AuthService:\n'
                        '    async def get_profile_async(self, user):\n'
                        '        get_profile = self._cached(user)\n'
                        '        return get_profile\n'
                    ),
                },
                id='a-local-variable-sharing-the-name',
            ),
            # `db.run_sync(get_x_sync)` offloads *some* name; the import is what
            # says it is the function in the other file rather than a local —
            # or another module's function spelled the same way.
            pytest.param(
                {
                    'implementation.py': 'def get_x_sync():\n    return []\n',
                    'door.py': (
                        'async def get_x_async():\n'
                        '    return await db.run_sync(get_x_sync)\n'
                    ),
                },
                id='an-offload-naming-an-unimported-name',
            ),
            # `from implementation import other_sync as gz` then `run_sync(gz)`
            # drives `other_sync`, not every sibling the module defines: the
            # alias is a spelling, not a licence to pair by module. Passes on
            # both sides of the alias reading — it is a guard, not the fix —
            # against the collapse into "the name came from a module that also
            # defines the target".
            pytest.param(
                {
                    'implementation.py': (
                        'def get_z_sync():\n    return []\n\n'
                        'def other_sync():\n    return []\n'
                    ),
                    'door.py': (
                        'from implementation import other_sync as gz\n\n'
                        'async def get_z_async(db):\n'
                        '    return await db.run_sync(gz)\n'
                    ),
                },
                id='an-alias-of-another-function',
            ),
            # Two imports of the same published name, each under its own alias,
            # only one of them offloaded: the module behind the alias the
            # offload never named is not a twin. Reading each alias as its
            # published name alone merged both sources, so `implementation`'s
            # half was paired with an offload that bound to `external_library`
            # — outside the scanned tree. Fails on the merged reading (two
            # errors), pins the source-preserving one.
            pytest.param(
                {
                    'implementation.py': 'def get_z_sync():\n    return []\n',
                    'door.py': (
                        'from implementation import get_z_sync as gz\n'
                        'from external_library import get_z_sync as other\n\n'
                        'async def get_z_async(db):\n'
                        '    return await db.run_sync(other)\n'
                    ),
                },
                id='two-sources-bound-by-the-offloaded-alias',
            ),
            # The drive must sit in the body of the function being reported: a
            # file that offloads the name somewhere else knows about the
            # implementation, but not through this door.
            pytest.param(
                {
                    'implementation.py': 'def get_x_sync():\n    return []\n',
                    'door.py': (
                        'from implementation import get_x_sync\n\n'
                        'async def warm_cache_async():\n'
                        '    return await db.run_sync(get_x_sync)\n\n'
                        'async def get_x_async():\n'
                        '    return None\n'
                    ),
                },
                id='an-offload-in-a-sibling-function',
            ),
            # foo_sync in one file and foo_async in another, with no base and no
            # relation between them: the spelling converges, the pair does not
            # exist — a gate that blocked here would block on any two files that
            # happen to share a name.
            pytest.param(
                {
                    '_rev_j1.py': 'def rebuild_index_sync():\n    return []\n',
                    '_rev_j2.py': 'async def rebuild_index_async():\n    return []\n',
                },
                id='halves-in-unrelated-files',
            ),
            # `create` in one file and `create_async` in another is a
            # coincidence unless the second actually calls the first — generic
            # names exist in many modules and most of them never meet.
            pytest.param(
                {
                    'billing.py': 'def create():\n    pass\n',
                    'shipping.py': 'async def create_async():\n    pass\n',
                },
                id='a-generic-name-in-two-files',
            ),
        ],
    )
    def test_a_name_that_is_not_driven_through_the_offload_is_not_a_twin(
        self, tmp_path, files
    ):
        for name, source in files.items():
            (tmp_path / name).write_text(source, encoding='utf-8')
        result = _check_sync_async_function_twins(tmp_path)
        assert [r for r in result if r.startswith('::error')] == []

    def test_an_aliased_import_still_names_the_sync_half(self, tmp_path):
        """`from implementation import get_z_sync as gz` then
        `db.run_sync(gz)`: the offload writes the local spelling, and the
        import is what says which function that spelling names. Reading
        the alias without the name it stands for left the pair silent."""
        impl = tmp_path / 'implementation.py'
        impl.write_text('def get_z_sync():\n    return []\n', encoding='utf-8')
        door = tmp_path / 'door.py'
        door.write_text(
            'from implementation import get_z_sync as gz\n\n'
            'async def get_z_async(db):\n'
            '    return await db.run_sync(gz)\n',
            encoding='utf-8',
        )
        result = _check_sync_async_function_twins(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 2
        named = '\n'.join(errors)
        assert 'get_z_async() is a twin of get_z_sync()' in named
        assert 'get_z_sync() is a twin of get_z_async()' in named

    def test_a_baseless_sync_variant_beside_an_async_one_is_flagged(self, tmp_path):
        """foo_sync + foo_async with no foo anywhere: both trim to a base
        that does not exist, and the sync one is the debt."""
        f = tmp_path / 'service.py'
        f.write_text(
            'async def export_async():\n    pass\n\ndef export_sync():\n    pass\n',
            encoding='utf-8',
        )
        result = _check_sync_async_function_twins(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 1
        assert 'export_sync() is a twin of export_async()' in errors[0]
        assert 'twin of export()' not in errors[0]

    def test_an_async_base_is_an_alias_not_a_twin(self, tmp_path):
        """Both variants async — a compatibility alias delegating to the
        _async spelling — is a naming decision, not a sync leftover."""
        f = tmp_path / 'users.py'
        f.write_text(
            'async def promote_superuser():\n'
            '    return await _promote()\n\n'
            'async def promote_superuser_async():\n'
            '    return await promote_superuser()\n',
            encoding='utf-8',
        )
        result = _check_sync_async_function_twins(tmp_path)
        assert [r for r in result if r.startswith('::error')] == []


# ── Guardrail 2: CoreAPI model return type leak ─────────────────────────────


class TestCoreApiModelLeakGuardrail:
    """Tests for _check_public_api_return_types."""

    @pytest.mark.parametrize(
        'definition',
        [
            pytest.param(
                'async def get_async() -> "Item":\n    pass\n', id='model-return'
            ),
            # _model_-named public methods are no longer exempt.
            pytest.param(
                'async def get_model_async() -> "Item":\n    pass\n',
                id='model-in-the-method-name',
            ),
        ],
    )
    def test_a_public_method_returning_a_model_is_an_error(self, tmp_path, definition):
        f = tmp_path / 'items.py'
        f.write_text(
            'from typing import TYPE_CHECKING\n'
            'if TYPE_CHECKING:\n'
            '    from app.models.item import Item\n\n' + definition,
            encoding='utf-8',
        )
        result = _check_public_api_return_types(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 1
        assert 'Item' in errors[0]

    @pytest.mark.parametrize(
        'source',
        [
            # Private (_-prefixed) helpers may handle ORM models internally.
            pytest.param(
                'from typing import TYPE_CHECKING\n'
                'if TYPE_CHECKING:\n'
                '    from app.models.item import Item\n\n'
                'def _to_dto(item: "Item") -> "Item":\n    pass\n',
                id='private-helper',
            ),
            pytest.param(
                'from app.core.contracts import ItemDTO\n\n'
                'async def update_async(data: ItemDTO) -> ItemDTO:\n    pass\n',
                id='dto-param',
            ),
            pytest.param(
                'from app.core.contracts import ItemDTO\n\n'
                'async def get_async() -> ItemDTO:\n    pass\n',
                id='dto-return',
            ),
        ],
    )
    def test_model_use_outside_a_public_return_type_is_not_flagged(
        self, tmp_path, source
    ):
        f = tmp_path / 'items.py'
        f.write_text(source, encoding='utf-8')
        result = _check_public_api_return_types(tmp_path)
        assert result == []

    def test_detects_model_param_as_error(self, tmp_path):
        """Accepting an ORM model parameter is flagged as error."""
        f = tmp_path / 'items.py'
        f.write_text(
            'from typing import TYPE_CHECKING\n'
            'if TYPE_CHECKING:\n'
            '    from app.models.item import Item\n\n'
            'async def update_async(item: "Item") -> None:\n    pass\n',
            encoding='utf-8',
        )
        result = _check_public_api_return_types(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 1
        assert 'item' in errors[0]
        assert 'Item' in errors[0]

    def test_detects_model_kwonly_param_as_error(self, tmp_path):
        """Keyword-only ORM model parameters are flagged too."""
        f = tmp_path / 'items.py'
        f.write_text(
            'from typing import TYPE_CHECKING\n'
            'if TYPE_CHECKING:\n'
            '    from app.models.item import Item\n\n'
            'async def update_async(*, item: "Item") -> None:\n    pass\n',
            encoding='utf-8',
        )
        result = _check_public_api_return_types(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 1

    def test_param_leak_baseline_downgrades_to_notice(self, tmp_path):
        """Baselined param leaks emit ::notice instead of ::error."""
        f = tmp_path / 'items.py'
        f.write_text(
            'from typing import TYPE_CHECKING\n'
            'if TYPE_CHECKING:\n'
            '    from app.models.item import Item\n\n'
            'async def update_async(item: "Item") -> None:\n    pass\n',
            encoding='utf-8',
        )
        baseline = {f'{_rel(f)}::update_async#item'}
        result = _check_public_api_return_types(tmp_path, baseline)
        assert len(result) == 1
        assert result[0].startswith('::notice')


# ── Guardrail 2b: CoreAPI async naming ──────────────────────────────────────


class TestCoreApiAsyncNamingGuardrail:
    """Tests for _check_coreapi_async_naming."""

    def test_a_public_coroutine_without_the_suffix_is_an_error(self, tmp_path):
        f = tmp_path / 'items.py'
        f.write_text(
            'class CoreItemsAPI:\n    async def create(self) -> None:\n        pass\n',
            encoding='utf-8',
        )
        result = _check_coreapi_async_naming(tmp_path)
        assert len(result) == 1
        assert result[0].startswith('::error')
        assert 'CoreItemsAPI.create()' in result[0]
        assert 'create_async' in result[0]

    @pytest.mark.parametrize(
        ('filename', 'source'),
        [
            pytest.param(
                'items.py',
                'class CoreItemsAPI:\n'
                '    async def create_async(self) -> None:\n        pass\n',
                id='suffixed-coroutine',
            ),
            pytest.param(
                'events.py',
                'class CoreEventsAPI:\n'
                '    def subscribe(self, handler) -> None:\n        pass\n',
                id='sync-method',
            ),
            pytest.param(
                'organizations.py',
                'async def _load_org() -> None:\n    pass\n'
                'class CoreOrganizationsAPI:\n'
                '    async def _refresh(self) -> None:\n        pass\n',
                id='private-coroutine',
            ),
            pytest.param(
                'llm.py',
                'class CoreLlmAPI:\n'
                '    async def extract_async(self) -> None:\n'
                '        async def log(response) -> None:\n            pass\n',
                id='nested-coroutine-is-not-facade-surface',
            ),
        ],
    )
    def test_async_naming_accepts_what_the_contract_allows(
        self, tmp_path, filename, source
    ):
        (tmp_path / filename).write_text(source, encoding='utf-8')
        assert _check_coreapi_async_naming(tmp_path) == []


# ── Guardrail 3: TOCTOU risk ────────────────────────────────────────────────


class TestToctouRiskGuardrail:
    """Tests for _check_toctou_risk."""

    def test_detects_select_mutation_without_lock(self, tmp_path):
        """select + db.add without with_for_update = TOCTOU error."""
        f = tmp_path / 'service.py'
        f.write_text(
            'async def transfer(db):\n'
            '    result = await db.execute(select(Item).where(Item.id == 1))\n'
            '    item = result.scalar_one()\n'
            '    item.quantity -= 5\n'
            '    await db.commit()\n',
            encoding='utf-8',
        )
        result = _check_toctou_risk(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 1
        assert 'transfer' in errors[0]

    def test_locked_select_not_flagged(self, tmp_path):
        """select(...).with_for_update() is safe — not flagged."""
        f = tmp_path / 'service.py'
        f.write_text(
            'async def transfer(db):\n'
            '    result = await db.execute(\n'
            '        select(Item).where(Item.id == 1).with_for_update()\n'
            '    )\n'
            '    item = result.scalar_one()\n'
            '    item.quantity -= 5\n'
            '    await db.commit()\n',
            encoding='utf-8',
        )
        result = _check_toctou_risk(tmp_path)
        assert result == []

    def test_acquire_advisory_lock_helper_counts_as_a_lock(self, tmp_path):
        """The helper wrapping ``pg_advisory_xact_lock`` must be recognised.

        Lock detection is textual, so extracting the raw SQL into
        ``core.db_utils.acquire_advisory_lock`` made 19 already-locked
        functions look unlocked and the whole check went red. Any future
        lock helper has to be added to ``_LOCK_PATTERNS`` as well — this
        test is what turns that omission into a failure here rather than a
        wall of false positives in CI.
        """
        f = tmp_path / 'service.py'
        f.write_text(
            'async def upsert(db, org_id):\n'
            "    await acquire_advisory_lock(db, f'x:{org_id}')\n"
            '    result = await db.execute(select(Item).where(Item.id == 1))\n'
            '    item = result.scalar_one()\n'
            '    item.quantity -= 5\n'
            '    await db.commit()\n',
            encoding='utf-8',
        )
        result = _check_toctou_risk(tmp_path)
        assert [r for r in result if r.startswith('::error')] == []

    def test_baselined_toctou_emits_notice(self, tmp_path):
        """Baselined TOCTOU functions emit ::notice."""
        f = tmp_path / 'service.py'
        f.write_text(
            'async def transfer(db):\n'
            '    result = await db.execute(select(Item).where(Item.id == 1))\n'
            '    item = result.scalar_one()\n'
            '    item.quantity -= 5\n'
            '    await db.commit()\n',
            encoding='utf-8',
        )
        from app.core.architecture_lint._constants import _rel

        key = f'{_rel(f)}:1:transfer'
        result = _check_toctou_risk(tmp_path, baseline={key})
        errors = [r for r in result if r.startswith('::error')]
        notices = [r for r in result if r.startswith('::notice')]
        assert errors == []
        assert len(notices) == 1


class TestStaleBaselineEntries:
    """A baseline entry that matches no finding is reported, not carried."""

    def test_entry_matching_nothing_is_an_error(self):
        from app.core.architecture_lint._quality_checks_baseline_ratchet import (
            _check_stale_entries,
        )

        result = _check_stale_entries({'a.py:1:f', 'b.py:2:g'}, {'a.py:1:f'}, 'x.txt')

        assert len(result) == 1
        assert result[0].startswith('::error file=app/core/x.txt')
        assert 'b.py:2:g' in result[0]

    def test_every_entry_live_is_silent(self):
        from app.core.architecture_lint._quality_checks_baseline_ratchet import (
            _check_stale_entries,
        )

        assert _check_stale_entries({'a.py:1:f'}, {'a.py:1:f', 'c.py:3:h'}, 'x') == []

    def test_toctou_detections_are_the_keys_a_baseline_must_match(self, tmp_path):
        from app.core.architecture_lint._quality_checks_toctou import (
            collect_toctou_risks,
        )

        (tmp_path / 'service.py').write_text(
            'async def transfer(db):\n'
            '    result = await db.execute(select(Item).where(Item.id == 1))\n'
            '    item = result.scalar_one()\n'
            '    item.quantity -= 5\n'
            '    await db.commit()\n',
            encoding='utf-8',
        )

        keys = set(collect_toctou_risks(tmp_path))

        assert len(keys) == 1
        assert next(iter(keys)).endswith(':1:transfer')


# ── Test hygiene: skips inside test bodies ───────────────────────────────────


class TestTestSkipRegistry:
    """Tests for _check_test_skips.

    Eleven of fifteen skips in the suite fired in every run, a tenant
    isolation test among them. The gate makes a new one either assert its
    precondition or name an owner and a date, and keeps the list from
    describing skips that are gone.
    """

    _SKIPPING_METHOD = (
        'import pytest\n\n'
        'class TestThing:\n'
        '    def test_waits(self):\n'
        '        pytest.skip("no data")\n'
    )

    def _write(self, root, body: str):
        root.mkdir(parents=True, exist_ok=True)
        path = root / 'test_demo.py'
        path.write_text(body, encoding='utf-8')
        return path

    def test_an_unregistered_skip_is_an_error_named_by_node_id(self, tmp_path):
        from app.core.architecture_lint._quality_checks_test_skips import (
            _check_test_skips,
        )

        path = self._write(tmp_path / 'tests', self._SKIPPING_METHOD)

        findings = _check_test_skips((tmp_path / 'tests',), set())

        assert len(findings) == 1
        assert findings[0].startswith('::error')
        assert f'{_rel(path)}::TestThing::test_waits' in findings[0]

    def test_a_registered_skip_is_a_notice(self, tmp_path):
        from app.core.architecture_lint._quality_checks_test_skips import (
            _check_test_skips,
        )

        path = self._write(tmp_path / 'tests', self._SKIPPING_METHOD)

        findings = _check_test_skips(
            (tmp_path / 'tests',), {f'{_rel(path)}::TestThing::test_waits'}
        )

        assert [f.split(' ', 1)[0] for f in findings] == ['::notice']

    def test_an_entry_whose_test_no_longer_skips_is_an_error(self, tmp_path):
        from app.core.architecture_lint._quality_checks_test_skips import (
            _check_test_skips,
        )

        path = self._write(tmp_path / 'tests', 'def test_asserts():\n    assert True\n')

        findings = _check_test_skips(
            (tmp_path / 'tests',), {f'{_rel(path)}::test_asserts'}
        )

        assert len(findings) == 1
        assert findings[0].startswith('::error')
        assert 'stale skip entry' in findings[0]

    def test_a_skip_in_a_helper_nested_inside_the_test_counts(self, tmp_path):
        """test_eager_loading hid its skips in a `_check` passed to run_sync."""
        from app.core.architecture_lint._quality_checks_test_skips import (
            _check_test_skips,
        )

        self._write(
            tmp_path / 'tests',
            'import pytest\n\n'
            'async def test_guard(session):\n'
            '    def _check(db):\n'
            '        pytest.skip("no uom")\n'
            '    await session.run_sync(_check)\n',
        )

        findings = _check_test_skips((tmp_path / 'tests',), set())

        assert len(findings) == 1
        assert '::test_guard' in findings[0]

    def test_fixtures_and_markers_are_not_scanned(self, tmp_path):
        from app.core.architecture_lint._quality_checks_test_skips import (
            _check_test_skips,
        )

        self._write(
            tmp_path / 'tests',
            'import pytest\n\n'
            '@pytest.fixture\n'
            'def storage_type():\n'
            '    pytest.skip("fixture says so to every user")\n\n'
            '@pytest.mark.skipif(True, reason="visible at the definition")\n'
            'def test_marked():\n'
            '    assert True\n',
        )

        assert _check_test_skips((tmp_path / 'tests',), set()) == []


# ---------------------------------------------------------------------------
# --quiet baseline summary (_print_baselined_counts)
# ---------------------------------------------------------------------------


class TestQuietBaselineSummary:
    """Under ``--quiet`` accepted debt is counted once, in the closing summary.

    Baselined notices are *accepted* debt, documented in a baseline file.
    Printing them line by line, and again in the closing summary under another
    label, trained reviewers to skim both; and a category missing from the
    closing summary was reported nowhere in the run's last lines.
    """

    NOTICE = '::notice file=app/a.py,title=Architecture: sync/async twin::foo()'

    def test_quiet_holds_back_the_per_file_notices(self, capsys):
        errors, notices = _emit_baselined([self.NOTICE], quiet=True)

        assert capsys.readouterr().out == ''
        assert errors == []
        assert notices == [self.NOTICE]

    def test_verbose_prints_per_file_notices_for_annotations(self, capsys):
        _emit_baselined([self.NOTICE, '::error title=X::boom'], quiet=False)

        assert capsys.readouterr().out.splitlines() == [
            '::error title=X::boom',
            self.NOTICE,
        ]

    def test_each_count_is_printed_once_with_its_baseline_file(self, capsys):
        _print_baselined_counts({'twin': [self.NOTICE] * 3, 'toctou': []})

        lines = capsys.readouterr().out.splitlines()
        assert lines == [
            '  (3 baselined sync/async twin(s) — app/core/sync_async_twin_baseline.txt)'
        ]

    def test_no_summary_line_is_a_workflow_command(self, capsys):
        _print_baselined_counts({key: [self.NOTICE] for key in _BASELINED_SUMMARY})

        out = capsys.readouterr().out.splitlines()
        assert len(out) == len(_BASELINED_SUMMARY)
        assert not any(line.lstrip().startswith('::') for line in out)

    def test_every_category_main_records_has_a_summary_entry(self):
        """A new ``baselined['x']`` assignment without a label is a gate that
        reports its debt nowhere."""
        tree = ast.parse(Path(lint_main.__file__).read_text(encoding='utf-8'))
        recorded = {
            node.slice.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == 'baselined'
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.slice, ast.Constant)
        }

        assert recorded - set(_BASELINED_SUMMARY) == set()
        assert set(_BASELINED_SUMMARY) - recorded == set()

    def test_every_pointer_names_a_file_that_exists(self):
        backend = Path(__file__).resolve().parents[2]

        missing = [
            baseline_file
            for _, baseline_file in _BASELINED_SUMMARY.values()
            if baseline_file and not (backend / baseline_file).is_file()
        ]

        assert missing == []


class TestServicesEscapeHatchMarker:
    """Guardrail: the escape-hatch marker is forbidden in Core app/services/."""

    def test_flags_standalone_marker_directive(self, tmp_path):
        services_root = tmp_path / 'services'
        services_root.mkdir()
        (services_root / 'valuation_service.py').write_text(
            '"""Service."""\n\n'
            '# architecture: allow_direct_db_access\n'
            '# reason: some aggregation query\n\n'
            'def f():\n    pass\n',
            encoding='utf-8',
        )

        errors = _check_services_escape_hatch_marker(services_root)

        assert len(errors) == 1
        assert 'valuation_service.py' in errors[0]
        assert '::error' in errors[0]
        assert 'line=3' in errors[0]

    @pytest.mark.parametrize(
        ('filename', 'source'),
        [
            # The marker appears only inside a docstring as prose, not as a
            # directive.
            pytest.param(
                'valuation_service.py',
                '"""\n'
                'Service.\n\n'
                'Note: this is NOT an escape-hatch — the\n'
                '``# architecture: allow_direct_db_access`` marker does not apply here.\n'
                '"""\n\n'
                'def f():\n    pass\n',
                id='marker-in-a-prose-docstring',
            ),
            pytest.param(
                'test_valuation.py',
                '# architecture: allow_direct_db_access\n',
                id='test-file',
            ),
        ],
    )
    def test_a_marker_that_is_not_a_directive_is_ignored(
        self, tmp_path, filename, source
    ):
        services_root = tmp_path / 'services'
        services_root.mkdir()
        (services_root / filename).write_text(source, encoding='utf-8')

        errors = _check_services_escape_hatch_marker(services_root)

        assert errors == []

    def test_flags_marker_with_leading_whitespace(self, tmp_path):
        services_root = tmp_path / 'services'
        services_root.mkdir()
        (services_root / 'inner' / 'sub').mkdir(parents=True)
        (services_root / 'inner' / 'sub' / 'analytics.py').write_text(
            'x = 1\n    # architecture: allow_direct_db_access\n',
            encoding='utf-8',
        )

        errors = _check_services_escape_hatch_marker(services_root)

        assert len(errors) == 1
        assert 'analytics.py' in errors[0]

    def test_missing_services_root_returns_empty(self, tmp_path):
        errors = _check_services_escape_hatch_marker(tmp_path / 'nonexistent')

        assert errors == []


# ── Guardrail 4: CoreAPI signature legality ──────────────────────────────────


class TestCoreApiSignatureLegalityGuardrail:
    """Tests for _check_coreapi_signature_legality."""

    def test_schemas_type_in_param_flagged(self, tmp_path):
        f = tmp_path / 'items.py'
        f.write_text(
            'from app.schemas.item import ItemCreate\n\n'
            'class CoreItemsAPI:\n'
            '    async def create_async(self, data: ItemCreate) -> None:\n        pass\n',
            encoding='utf-8',
        )
        result = _check_coreapi_signature_legality(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 1
        assert 'ItemCreate' in errors[0]
        assert 'app.schemas.item' in errors[0]
        assert 'CoreItemsAPI.create_async' in errors[0]

    @pytest.mark.parametrize(
        ('filename', 'source', 'illegal'),
        [
            # Only CursorPaginatedResponse is illegal — ItemDTO comes from
            # contracts.
            pytest.param(
                'items.py',
                'from app.core.contracts import ItemDTO\n'
                'from app.schemas.pagination import CursorPaginatedResponse\n\n'
                'class CoreItemsAPI:\n'
                '    async def search(self) -> CursorPaginatedResponse[ItemDTO]:\n'
                '        pass\n',
                'CursorPaginatedResponse',
                id='schemas-type-in-return',
            ),
            # TYPE_CHECKING imports are contract-visible too — still illegal.
            pytest.param(
                'categories.py',
                'from typing import TYPE_CHECKING\n'
                'if TYPE_CHECKING:\n'
                '    from app.schemas.category import CategoryUpdate\n\n'
                'class CoreCategoriesAPI:\n'
                '    async def update_async(self, data: CategoryUpdate) -> None:\n'
                '        pass\n',
                'CategoryUpdate',
                id='type-checking-import',
            ),
            pytest.param(
                'storage_types.py',
                'from app.i18n import Language\n\n'
                'class CoreStorageTypesAPI:\n'
                '    async def create_async(self, lang: Language | None = None) -> None:\n'
                '        pass\n',
                'Language',
                id='i18n-type',
            ),
            pytest.param(
                'queries.py',
                'from app.schemas.label_pool import LabelPoolCreate\n\n'
                'async def generate_pool_async(data: LabelPoolCreate) -> None:\n    pass\n',
                'LabelPoolCreate',
                id='module-level-function',
            ),
            # `from app.schemas import pagination` + `pagination.X` annotation.
            pytest.param(
                'items.py',
                'from app.schemas import pagination\n\n'
                'class CoreItemsAPI:\n'
                '    async def search(self) -> pagination.CursorPaginatedResponse:\n'
                '        pass\n',
                'pagination',
                id='module-attribute-root',
            ),
        ],
    )
    def test_an_illegal_type_in_a_facade_signature_is_flagged(
        self, tmp_path, filename, source, illegal
    ):
        f = tmp_path / filename
        f.write_text(source, encoding='utf-8')
        result = _check_coreapi_signature_legality(tmp_path)
        errors = [r for r in result if r.startswith('::error')]
        assert len(errors) == 1
        assert illegal in errors[0]

    @pytest.mark.parametrize(
        ('filename', 'source'),
        [
            pytest.param(
                'items.py',
                'from app.core.contracts import ItemDTO, UserContextDTO\n\n'
                'class CoreItemsAPI:\n'
                '    async def get_async(self, user: UserContextDTO) -> ItemDTO:\n'
                '        pass\n',
                id='contracts-dto',
            ),
            pytest.param(
                'storages.py',
                'from datetime import datetime\n'
                'from decimal import Decimal\n'
                'from pathlib import Path\n'
                'from typing import Any, Literal\n'
                'from uuid import UUID\n\n'
                'from sqlalchemy.ext.asyncio import AsyncSession\n\n'
                'class CoreStoragesAPI:\n'
                '    async def get_async(\n'
                '        self,\n'
                '        db: AsyncSession,\n'
                '        org_id: UUID,\n'
                '        *,\n'
                '        kind: Literal["a", "b"] = "a",\n'
                '    ) -> dict[str, Any] | None:\n'
                '        pass\n\n'
                '    async def stats(self, db: AsyncSession) -> tuple[datetime, Decimal, Path]:\n'
                '        pass\n',
                id='whitelisted-stdlib-and-session',
            ),
            pytest.param(
                'ai_connections.py',
                'class ConnectionStillBoundError(Exception):\n'
                '    pass\n\n'
                'class CoreAIConnectionsAPI:\n'
                '    async def delete(self) -> ConnectionStillBoundError | None:\n'
                '        pass\n',
                id='local-class',
            ),
            pytest.param(
                'items.py',
                'from app.schemas.item import ItemCreate\n\n'
                'class CoreItemsAPI:\n'
                '    def _to_model(self, data: ItemCreate) -> ItemCreate:\n        pass\n',
                id='private-method-exempt',
            ),
            pytest.param(
                '__init__.py',
                'from app.schemas.item import ItemCreate\n\n'
                'def create(data: ItemCreate) -> None:\n    pass\n',
                id='init-py-skipped',
            ),
        ],
    )
    def test_a_legal_facade_signature_is_not_flagged(self, tmp_path, filename, source):
        f = tmp_path / filename
        f.write_text(source, encoding='utf-8')
        result = _check_coreapi_signature_legality(tmp_path)
        assert result == []

    def test_baseline_downgrades_to_notice(self, tmp_path):
        f = tmp_path / 'items.py'
        f.write_text(
            'from app.schemas.item import ItemCreate\n\n'
            'class CoreItemsAPI:\n'
            '    async def create_async(self, data: ItemCreate) -> None:\n        pass\n',
            encoding='utf-8',
        )
        baseline = {f'{_rel(f)}::CoreItemsAPI.create_async::ItemCreate'}
        result = _check_coreapi_signature_legality(tmp_path, baseline)
        assert len(result) == 1
        assert result[0].startswith('::notice')


# ── Mixed-status assertion check (test hygiene) ─────────────────────────────


class TestMixedStatusAssertionCheck:
    """Tests for _check_mixed_status_assertions.

    An assertion that accepts a 2xx and a >= 400 at once passes whichever the
    endpoint does, and goes on passing through every change to it. Twenty-six
    of them were found in this suite; the gate exists so that the twenty-
    seventh has to be argued for in a diff instead of appearing quietly.
    """

    def _write(self, root, body: str):
        root.mkdir(parents=True, exist_ok=True)
        path = root / 'test_demo.py'
        path.write_text(body, encoding='utf-8')
        return path

    def test_flags_a_success_and_a_refusal_in_one_set(self, tmp_path):
        """The plain shape: an answer and a refusal accepted together."""
        from app.core.architecture_lint._quality_checks_test_hygiene import (
            _check_mixed_status_assertions,
        )

        root = tmp_path / 'tests'
        self._write(
            root,
            'def test_thing():\n    assert resp.status_code in (200, 400, 422)\n',
        )

        errors = _check_mixed_status_assertions((root,))

        assert len(errors) == 1
        assert errors[0].startswith('::error')
        assert 'test_thing' in errors[0]
        assert '[200, 400, 422]' in errors[0]

    def test_flags_the_same_shape_written_with_status_constants(self, tmp_path):
        """The spelling a grep for digits misses — four of the original set."""
        from app.core.architecture_lint._quality_checks_test_hygiene import (
            _check_mixed_status_assertions,
        )

        root = tmp_path / 'tests'
        self._write(
            root,
            'def test_thing():\n'
            '    assert r.status_code in (\n'
            '        status.HTTP_200_OK,\n'
            '        status.HTTP_404_NOT_FOUND,\n'
            '    )\n',
        )

        errors = _check_mixed_status_assertions((root,))

        assert len(errors) == 1
        assert '[200, 404]' in errors[0]

    @pytest.mark.parametrize(
        'body',
        [
            # `in (200, 201)` narrows a shape; it does not hedge a verdict.
            pytest.param(
                'def test_thing():\n    assert r.status_code in (200, 201)\n',
                id='a-set-of-successes',
            ),
            # Branching on the code is a decision, not a claim about it.
            pytest.param(
                'def test_thing():\n    if r.status_code in (200, 404):\n        pass\n',
                id='an-in-comparison-that-is-not-an-assertion',
            ),
        ],
    )
    def test_a_membership_test_is_not_a_mixed_assertion(self, tmp_path, body):
        from app.core.architecture_lint._quality_checks_test_hygiene import (
            _check_mixed_status_assertions,
        )

        root = tmp_path / 'tests'
        self._write(root, body)

        assert _check_mixed_status_assertions((root,)) == []

    def test_baseline_entry_downgrades_the_error_to_a_notice(self, tmp_path):
        """Keyed path::test_name, so it survives lines moving above it."""
        from app.core.architecture_lint._quality_checks_test_hygiene import (
            _check_mixed_status_assertions,
        )

        root = tmp_path / 'tests'
        path = self._write(
            root, 'def test_thing():\n    assert r.status_code in (200, 400)\n'
        )

        errors = _check_mixed_status_assertions((root,), {f'{_rel(path)}::test_thing'})

        assert len(errors) == 1
        assert errors[0].startswith('::notice')


def test_a_layer_check_reads_every_alias_of_an_import(tmp_path, monkeypatch):
    """The forbidden module can hide behind a harmless first alias.

    The contracts and public-API checks read only ``node.names[0]``, so
    ``import os, app.models.item`` named the ORM in its second alias and
    walked past both of them.
    """
    from app.core.architecture_lint._violations import _check_contracts_violations

    monkeypatch.chdir(tmp_path)
    contracts_root = tmp_path / 'contracts'
    contracts_root.mkdir()
    (contracts_root / 'mixed.py').write_text(
        'import os, app.models.item\n', encoding='utf-8'
    )

    errors = _check_contracts_violations(contracts_root)

    assert len(errors) == 1
    assert 'app.models.item' in errors[0]


def test_a_layer_check_ignores_type_checking_imports(tmp_path, monkeypatch):
    """A hint-only import under TYPE_CHECKING stays out of the layer scans."""
    from app.core.architecture_lint._violations import _check_public_api_violations

    monkeypatch.chdir(tmp_path)
    public_api_root = tmp_path / 'public_api'
    public_api_root.mkdir()
    (public_api_root / 'typed.py').write_text(
        'from typing import TYPE_CHECKING\n'
        'if TYPE_CHECKING:\n'
        '    import app.models.item\n',
        encoding='utf-8',
    )

    assert _check_public_api_violations(public_api_root) == []


def test_the_write_baseline_walk_skips_a_file_it_cannot_parse(tmp_path):
    """The walk for `--write-baseline` names what it can read and no more."""
    from app.core.architecture_lint._violations import (
        collect_module_import_violations,
    )

    modules_root = tmp_path / 'modules'
    modules_root.mkdir()
    (modules_root / 'broken.py').write_text('def (:\n', encoding='utf-8')
    (modules_root / 'leak.py').write_text(
        'from app.models.item import Item\n', encoding='utf-8'
    )

    violations = collect_module_import_violations(modules_root)

    assert [v.import_path for v in violations] == ['app.models.item']


def test_a_layer_check_skips_init_and_unparsable_files(tmp_path, monkeypatch):
    """`__init__.py` and a file the parser cannot read are both skipped."""
    from app.core.architecture_lint._violations import _check_contracts_violations

    monkeypatch.chdir(tmp_path)
    contracts_root = tmp_path / 'contracts'
    contracts_root.mkdir()
    (contracts_root / '__init__.py').write_text(
        'from app.models.item import Item\n', encoding='utf-8'
    )
    (contracts_root / 'broken.py').write_text('def (:\n', encoding='utf-8')

    assert _check_contracts_violations(contracts_root) == []


class TestRawHttpExceptionRatchet:
    """New raw ``raise HTTPException`` sites must be a decision.

    AGENTS.md §3 sends routers through the typed ``AppException`` classes;
    a raw ``HTTPException`` answers ``detail`` as a bare string, so the
    client gets a sentence and no code. The legacy population is frozen by
    a baseline keyed per site, not by a vanishing line number.
    """

    def _tree(self, tmp_path):
        root = tmp_path / 'app'
        root.mkdir()
        return root

    def test_a_new_raw_raise_is_an_error(self, tmp_path):
        from app.core.architecture_lint._quality_checks_raw_http_exception import (
            _check_raw_http_exceptions,
        )

        root = self._tree(tmp_path)
        (root / 'door.py').write_text(
            'from fastapi import HTTPException\n'
            '\n'
            'def open_the_door():\n'
            "    raise HTTPException(status_code=403, detail='no')\n",
            encoding='utf-8',
        )

        entries = _check_raw_http_exceptions([root])

        assert len(entries) == 1
        assert entries[0].startswith('::error ')
        assert 'door.py' in entries[0]
        assert 'open_the_door' in entries[0]

    def test_a_baselined_site_is_a_notice(self, tmp_path):
        from app.core.architecture_lint._quality_checks_raw_http_exception import (
            _check_raw_http_exceptions,
            _collect_raw_http_exceptions,
        )

        root = self._tree(tmp_path)
        (root / 'door.py').write_text(
            'from fastapi import HTTPException\n'
            '\n'
            'def open_the_door():\n'
            "    raise HTTPException(status_code=403, detail='no')\n",
            encoding='utf-8',
        )
        site = _collect_raw_http_exceptions([root])[0]

        entries = _check_raw_http_exceptions([root], baseline={site.key})

        assert len(entries) == 1
        assert entries[0].startswith('::notice ')

    def test_a_second_raise_in_a_baselined_function_is_not_covered(self, tmp_path):
        """The key is per site: ``@1`` doesn't shelter ``@2``."""
        from app.core.architecture_lint._quality_checks_raw_http_exception import (
            _check_raw_http_exceptions,
            _collect_raw_http_exceptions,
        )

        root = self._tree(tmp_path)
        (root / 'door.py').write_text(
            'from fastapi import HTTPException\n'
            '\n'
            'def open_the_door():\n'
            "    raise HTTPException(status_code=403, detail='no')\n"
            "    raise HTTPException(status_code=404, detail='gone')\n",
            encoding='utf-8',
        )
        first = _collect_raw_http_exceptions([root])[0]

        entries = _check_raw_http_exceptions([root], baseline={first.key})

        assert [entry.startswith('::error') for entry in entries] == [False, True]

    def test_a_typed_app_exception_is_not_a_finding(self, tmp_path):
        from app.core.architecture_lint._quality_checks_raw_http_exception import (
            _check_raw_http_exceptions,
        )

        root = self._tree(tmp_path)
        (root / 'door.py').write_text(
            'from app.core.exceptions import ForbiddenException\n'
            '\n'
            'def open_the_door():\n'
            '    raise ForbiddenException(message="no")\n',
            encoding='utf-8',
        )

        assert _check_raw_http_exceptions([root]) == []

    def test_prose_and_comments_do_not_count(self, tmp_path):
        """Only the AST counts: a raw raise named in a docstring is not one."""
        from app.core.architecture_lint._quality_checks_raw_http_exception import (
            _check_raw_http_exceptions,
        )

        root = self._tree(tmp_path)
        (root / 'door.py').write_text(
            'def open_the_door():\n'
            '    """Always use HTTPException, never raise HTTPException(403)."""\n'
            '    return 1\n',
            encoding='utf-8',
        )

        assert _check_raw_http_exceptions([root]) == []

    def test_test_files_and_the_linter_itself_are_skipped(self, tmp_path):
        from app.core.architecture_lint._quality_checks_raw_http_exception import (
            _check_raw_http_exceptions,
        )

        root = self._tree(tmp_path)
        tests = root / 'tests'
        tests.mkdir()
        (tests / 'test_door.py').write_text(
            "raise HTTPException(status_code=403, detail='no')\n",
            encoding='utf-8',
        )

        assert _check_raw_http_exceptions([root]) == []
