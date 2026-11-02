"""Every top-level import under ``app/`` is a dependency pyproject declares.

``cryptography`` encrypts the secrets an organization stores and verifies
module signatures, yet no dependency named it: it reached the tree as
google-auth's transitive requirement, so the package that breaks decryption
and signature verification when it disappears was invisible in
``pyproject.toml``. This is the gate that says so — the audit that found it
found five packages at once, and the next one should cost a red test run, not
a publication-readiness pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_declared_imports import (
    _normalise,
    declared_distributions,
    imported_top_levels,
    installed_owners,
    is_test_file,
    undeclared_imports,
)

pytestmark = pytest.mark.unit


def test_the_tree_imports_nothing_pyproject_does_not_declare() -> None:
    """The green the gate exists for: every top-level import is owned.

    Fails on the file list of an import no declared dependency provides,
    which is how a dependency the tree cannot run without stays invisible
    to anyone reading ``pyproject.toml``.
    """
    imported = imported_top_levels()
    declared = declared_distributions()

    assert undeclared_imports(imported, declared, installed_owners()) == []


def test_an_import_no_declared_dependency_owns_is_named_with_its_files() -> None:
    """The refusal names the package and every file that imports it."""
    imported = {'requests': ['app/services/mailer.py', 'app/cli/commands_demo.py']}
    owners = {'requests': {'requests'}}  # installed, but only as somebody's requirement

    problems = undeclared_imports(imported, declared={'fastapi'}, owners=owners)

    assert problems == ['requests (app/cli/commands_demo.py, app/services/mailer.py)']


def test_declaring_the_package_is_what_turns_the_refusal_green() -> None:
    """The same import, once pyproject names the distribution that owns it."""
    imported = {'cryptography': ['app/services/crypto_service.py']}
    owners = {'cryptography': {'cryptography'}}

    assert undeclared_imports(imported, declared={'cryptography'}, owners=owners) == []


def test_a_module_of_this_repository_is_not_a_dependency(tmp_path: Path) -> None:
    """``import seed_demo_data`` runs from the backend root, not from PyPI."""
    (tmp_path / 'seed_demo_data.py').write_text('', encoding='utf-8')
    imported = {'seed_demo_data': ['app/cli/commands_demo.py']}

    assert (
        undeclared_imports(imported, declared=set(), owners={}, backend_dir=tmp_path)
        == []
    )


def test_a_package_only_the_test_group_names_is_still_declared() -> None:
    """The suite's files live under ``app/``; the file declares its groups too."""
    assert 'pytest' in declared_distributions()


def test_the_runtime_set_leaves_the_dependency_groups_out() -> None:
    """What the production image installs: ``uv export --no-dev``."""
    runtime = declared_distributions(runtime_only=True)

    assert 'fastapi' in runtime
    assert 'pytest' not in runtime
    assert 'pypdf' not in runtime


def test_the_suites_files_are_told_from_the_images() -> None:
    assert is_test_file('app/core/tests/unit/test_x.py')
    assert is_test_file('app/modules/nutrition/tests/conftest.py')
    assert is_test_file('app/core/module_test_plugin.py')
    assert not is_test_file('app/services/crypto_service.py')
    assert not is_test_file('app/modules/testing_things/service.py')


def test_a_production_file_importing_a_dev_only_package_is_named(
    tmp_path: Path,
) -> None:
    """``import pytest`` in a module that ships passes on a dev laptop, fails at start."""
    app = tmp_path / 'app'
    (app / 'services').mkdir(parents=True)
    (app / 'services' / 'tests').mkdir()
    (app / 'services' / 'crypto_service.py').write_text('import pytest\n')
    (app / 'services' / 'tests' / 'test_crypto.py').write_text('import pytest\n')
    owners = {'pytest': {'pytest'}}

    shipped = undeclared_imports(
        imported_top_levels(app, tests=False),
        declared_distributions(runtime_only=True),
        owners,
    )
    suite = undeclared_imports(
        imported_top_levels(app, tests=True), declared_distributions(), owners
    )

    assert shipped == ['pytest (app/services/crypto_service.py)']
    assert suite == []


def test_the_distribution_names_are_compared_the_way_pip_spells_them() -> None:
    """Case and punctuation are spelling, not identity — pip's rule (PEP 503)."""
    assert _normalise('PyJWT') == 'pyjwt' == _normalise('pyjwt')
    assert _normalise('zope.interface') == 'zope-interface'


def test_an_extras_and_pin_are_not_part_of_the_name() -> None:
    """``typer[all]>=0.27.1`` names the distribution ``typer``."""
    assert declared_distributions() >= {'typer', 'fastapi', 'sqlalchemy', 'uvicorn'}
