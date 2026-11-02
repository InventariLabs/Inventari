"""`module validate` must apply i18n severity, not just check manifests.

`validate_i18n` already knew that missing pl/de/fr/es is an error for core and
official modules and nothing at all for community ones — but nothing called it from
the CLI, so `module validate` passed a module with no translations at all. Its
own unit tests (test_module_validator_i18n.py) cover the severity rules; these
cover the wiring and, most importantly, the exit code a CI job reads.
"""

import json

import pytest
from typer.testing import CliRunner

from app.i18n import SUPPORTED_LANGUAGES
from manage import app

runner = CliRunner()


def _module(base, name: str, module_type: str, langs: list[str]):
    mod = base / name
    (mod / 'i18n').mkdir(parents=True)
    (mod / 'manifest.json').write_text(
        json.dumps({'name': name, 'version': '1.0.0', 'module_type': module_type}),
        encoding='utf-8',
    )
    for lang in langs:
        (mod / 'i18n' / f'{lang}.json').write_text('{}', encoding='utf-8')
    return mod


@pytest.mark.unit
class TestModuleValidateI18n:
    def test_community_module_with_only_english_passes(self, tmp_path):
        """The whole point: one language must be enough for a community author."""
        _module(tmp_path, 'demo_mod', 'community', ['en'])

        result = runner.invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path)]
        )

        assert result.exit_code == 0
        # Not even a warning: a line per language the package chose not to
        # ship reads as a problem above "validation passed".
        assert 'missing i18n' not in result.output

    def test_official_module_with_only_english_fails(self, tmp_path):
        """Official modules ship with the product — an untranslated string is a bug."""
        _module(tmp_path, 'demo_off', 'official', ['en'])

        result = runner.invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path)]
        )

        assert result.exit_code == 1
        assert 'missing i18n/pl.json' in result.output

    def test_missing_english_fails_even_for_community(self, tmp_path):
        _module(tmp_path, 'demo_mod', 'community', ['pl'])

        result = runner.invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path)]
        )

        assert result.exit_code == 1
        assert 'en.json' in result.output

    def test_complete_module_passes_without_warnings(self, tmp_path):
        _module(tmp_path, 'demo_mod', 'community', list(SUPPORTED_LANGUAGES))

        result = runner.invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path)]
        )

        assert result.exit_code == 0
        assert 'missing i18n' not in result.output
