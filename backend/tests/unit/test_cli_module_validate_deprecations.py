"""`module validate` names the deprecated core_api surface a module uses.

A deprecation window is a migration deadline, not a refusal: the module
keeps working until the removal release, and the runtime warns on every
call. What the author owed earlier than that is the report — which method,
replaced by what, removed when, at which line. The scan rides beside the
safety scan at validate and install time; a module that calls only the
for_org replacements stays silent.
"""

import json

import pytest
from typer.testing import CliRunner

from app.cli.module_validator import validate_deprecated_core_api
from manage import app

runner = CliRunner()


def _module(base, name: str, module_type: str = 'community'):
    mod = base / name
    mod.mkdir(parents=True)
    (mod / 'manifest.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': '1.0.0',
                'module_type': module_type,
                'capabilities': [],
            }
        ),
        encoding='utf-8',
    )
    (mod / 'i18n').mkdir()
    (mod / 'i18n' / 'en.json').write_text('{}', encoding='utf-8')
    return mod


@pytest.fixture
def _synthetic_deprecation(monkeypatch):
    """Register throwaway entries the scan can name.

    The register stands empty — the unscoped file-storage surface left the
    facade without a window — so the scan's only honest test double is
    the set this file adds and takes back out, one entry per method the
    fixtures below reference. The class name is the one
    ``deprecated_facade_chains`` matches against; the methods themselves
    do not have to exist for a static scan.
    """
    from app.core._core_api_deprecations import (
        DEPRECATED_CORE_API,
        CoreApiDeprecation,
    )

    for method in ('save', 'get', 'get_url', 'delete', 'exists'):
        qualifier = f'CoreFileStorageAPI.{method}'
        monkeypatch.setitem(
            DEPRECATED_CORE_API,
            qualifier,
            CoreApiDeprecation(
                qualifier,
                f'CoreFileStorageAPI.{method}_for_org_async',
                'test-only synthetic entry',
            ),
        )


@pytest.mark.unit
class TestDeprecatedCoreApiScan:
    def test_a_direct_call_is_named_with_method_version_and_line(
        self, tmp_path, _synthetic_deprecation
    ):
        mod = _module(tmp_path, 'probe_mod')
        service = mod / 'store.py'
        service.write_text(
            'async def stash():\n'
            '    return await core_api.file_storage.save("p", b"x")\n',
            encoding='utf-8',
        )

        findings = validate_deprecated_core_api(mod)

        assert len(findings) == 1
        assert 'core_api.file_storage.save' in findings[0]
        assert 'removal in release 0.13.0' in findings[0]
        assert 'CoreFileStorageAPI.save_for_org_async' in findings[0]
        assert 'store.py:2' in findings[0]

    def test_a_bare_reference_counts_as_usage_too(
        self, tmp_path, _synthetic_deprecation
    ):
        """A method handed around is as retired as one called: the handler
        would fire the runtime warning the day it runs."""
        mod = _module(tmp_path, 'probe_mod')
        (mod / 'handlers.py').write_text(
            'delete_path = core_api.file_storage.delete\n',
            encoding='utf-8',
        )

        findings = validate_deprecated_core_api(mod)

        assert len(findings) == 1
        assert 'core_api.file_storage.delete' in findings[0]

    def test_tests_directories_are_not_reported(self, tmp_path, _synthetic_deprecation):
        """The scan's own fixtures plant deprecated calls on purpose; the
        safety scan exempts tests/ and this one keeps the same rule."""
        mod = _module(tmp_path, 'probe_mod')
        tests_dir = mod / 'tests'
        tests_dir.mkdir()
        (tests_dir / 'test_store.py').write_text(
            'core_api.file_storage.save("p", b"x")\n', encoding='utf-8'
        )

        assert validate_deprecated_core_api(mod) == []

    def test_a_module_on_the_for_org_replacements_stays_silent(
        self, tmp_path, _synthetic_deprecation
    ):
        mod = _module(tmp_path, 'probe_mod')
        (mod / 'store.py').write_text(
            'async def stash(org, module):\n'
            '    return await core_api.file_storage.save_for_org_async(\n'
            '        org, module, "p", b"x"\n'
            '    )\n',
            encoding='utf-8',
        )

        assert validate_deprecated_core_api(mod) == []

    def test_an_empty_register_reports_nothing(self, tmp_path):
        """Nothing registered is nothing to migrate: the scan stays quiet,
        which is its state until the next deprecation is registered."""
        mod = _module(tmp_path, 'probe_mod')
        (mod / 'store.py').write_text(
            'async def stash():\n'
            '    return await core_api.file_storage.save("p", b"x")\n',
            encoding='utf-8',
        )

        assert validate_deprecated_core_api(mod) == []

    def test_validate_reports_as_warning_and_stays_green(
        self, tmp_path, _synthetic_deprecation
    ):
        """The window is time, not a ban: usage warns, the gate passes."""
        mod = _module(tmp_path, 'probe_mod')
        (mod / 'store.py').write_text(
            'core_api.file_storage.exists("p")\n', encoding='utf-8'
        )

        result = runner.invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path)]
        )

        assert result.exit_code == 0, result.output
        assert 'deprecated core_api.file_storage.exists' in result.output
        assert 'removal in release 0.13.0' in result.output
