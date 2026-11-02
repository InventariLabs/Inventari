"""Unit tests for Core isolation lint + period-guard registry."""

import pytest

from app.core.architecture_lint._quality_checks_core_isolation import (
    _check_core_module_imports,
)
from app.core.period_guard import (
    check_period_not_closed,
    clear_period_guard,
    register_period_guard,
)

CORE_WITH_MODULE_IMPORT = """
from app.modules.warehouse.inventory_period_service import check_period_not_closed_async
"""

CORE_WITH_PLAIN_IMPORT = """
import app.modules.warehouse
"""

CORE_CLEAN = """
from app.core.period_guard import check_period_not_closed
from app.core.contracts import ItemDTO
"""


def _write(tmp_path, name, content):
    target = tmp_path / name
    target.write_text(content)
    return target


class TestCoreModuleImports:
    def test_flags_import_from_app_modules(self, tmp_path):
        _write(tmp_path, 'periods.py', CORE_WITH_MODULE_IMPORT)
        errors = _check_core_module_imports(tmp_path)
        assert len(errors) == 1
        assert errors[0].startswith('::error')
        assert 'app.modules.warehouse' in errors[0]

    def test_flags_plain_import_app_modules(self, tmp_path):
        _write(tmp_path, 'periods.py', CORE_WITH_PLAIN_IMPORT)
        errors = _check_core_module_imports(tmp_path)
        assert len(errors) == 1

    def test_passes_core_only_imports(self, tmp_path):
        _write(tmp_path, 'periods.py', CORE_CLEAN)
        assert _check_core_module_imports(tmp_path) == []

    def test_real_core_tree_is_clean(self):
        from app.core.architecture_lint._constants import CORE_DIR

        assert _check_core_module_imports(CORE_DIR) == []


class TestPeriodGuardRegistry:
    @pytest.fixture(autouse=True)
    def _reset_registry(self):
        """An empty registry for the test, and the real guard back afterwards.

        The warehouse module registers its guard once, when it is imported.
        Leaving the registry cleared took the period lock off every test
        that ran after this class on the same worker — five 409s that came
        back 200 — and whether any did depended on the collection order.
        """
        from app.core import period_guard

        before = period_guard._guard
        clear_period_guard()
        yield
        if before is None:
            clear_period_guard()
        else:
            register_period_guard(before)

    @pytest.mark.asyncio
    async def test_noop_when_unregistered(self):
        await check_period_not_closed(None, None, None)  # must not raise

    @pytest.mark.asyncio
    async def test_delegates_to_registered_guard(self):
        calls = []

        async def guard(db, org_id, doc_date):
            calls.append((db, org_id, doc_date))

        register_period_guard(guard)
        await check_period_not_closed('db', 'org', 'date')
        assert calls == [('db', 'org', 'date')]

    @pytest.mark.asyncio
    async def test_guard_exception_propagates(self):
        from app.core.exceptions import PeriodClosedError

        async def guard(db, org_id, doc_date):
            raise PeriodClosedError('closed')

        register_period_guard(guard)
        with pytest.raises(PeriodClosedError):
            await check_period_not_closed(None, None, None)


class TestIsolationLintScope:
    """The rule covers app/services and app/api, not only app/core.

    Every violation found had to be fixed in services or api, so a lint confined
       to app/core/ was guarding the one place that was already clean.
    """

    def test_violation_in_a_scanned_dir_is_reported(self, tmp_path):
        from app.core.architecture_lint._quality_checks_core_isolation import (
            _check_core_module_imports,
        )

        scanned = tmp_path / 'services'
        scanned.mkdir()
        (scanned / 'thing.py').write_text(
            'from app.modules.recipes.recipes_api import recipes_api\n'
        )

        assert _check_core_module_imports(scanned)

    def test_gated_exceptions_are_allowed(self):
        from app.core.architecture_lint._quality_checks_core_isolation import (
            _is_gated_exception,
        )

        assert _is_gated_exception(
            'app/services/onboarding_service.py', 'app.modules.warehouse'
        )
        # Same file, a module it is not cleared for.
        assert not _is_gated_exception(
            'app/services/onboarding_service.py', 'app.modules.recipes'
        )

    def test_the_real_tree_is_clean(self):
        """Regression: the four inversions must stay inverted."""
        from pathlib import Path

        from app.core.architecture_lint._constants import CORE_DIR
        from app.core.architecture_lint._quality_checks_core_isolation import (
            _check_core_module_imports,
        )

        errors: list[str] = []
        for name in ('core', 'services', 'api'):
            target = Path(CORE_DIR).parent / name
            if target.is_dir():
                errors += _check_core_module_imports(target)

        assert errors == []
