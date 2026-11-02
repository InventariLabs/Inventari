"""Unit tests for validate_i18n() in app.cli.module_validator."""

import json

import pytest

from app.cli.module_validator import validate_i18n
from app.i18n import SUPPORTED_LANGUAGES

ALL_LANGS = list(SUPPORTED_LANGUAGES)


def _manifest(module_type: str = 'core') -> str:
    return json.dumps(
        {'name': 'test_mod', 'version': '1.0.0', 'module_type': module_type}
    )


def _write_i18n(module_dir, langs: list[str]) -> None:
    i18n_dir = module_dir / 'i18n'
    i18n_dir.mkdir()
    for lang in langs:
        (i18n_dir / f'{lang}.json').write_text('{}', encoding='utf-8')


# -- Tests ------------------------------------------------------------------


@pytest.mark.unit
def test_core_module_all_languages_no_errors(tmp_path):
    """Core module with all 5 languages produces no results."""
    mod = tmp_path / 'test_mod'
    mod.mkdir()
    (mod / 'manifest.json').write_text(_manifest('core'), encoding='utf-8')
    _write_i18n(mod, ALL_LANGS)

    results = validate_i18n(mod)

    assert results == []


@pytest.mark.unit
def test_core_module_missing_fr_returns_error(tmp_path):
    """Core module missing fr.json → ('error', ...) for each missing lang."""
    mod = tmp_path / 'test_mod'
    mod.mkdir()
    (mod / 'manifest.json').write_text(_manifest('core'), encoding='utf-8')
    _write_i18n(mod, ['en', 'pl', 'de', 'es'])  # fr missing

    results = validate_i18n(mod)

    assert len(results) == 1
    severity, msg = results[0]
    assert severity == 'error'
    assert 'fr.json' in msg


@pytest.mark.unit
def test_community_module_with_english_only_reports_nothing(tmp_path):
    """A community package owes English only: the other languages are not findings."""
    mod = tmp_path / 'test_mod'
    mod.mkdir()
    (mod / 'manifest.json').write_text(_manifest('community'), encoding='utf-8')
    _write_i18n(mod, ['en'])

    results = validate_i18n(mod)

    assert results == []


@pytest.mark.unit
def test_any_module_missing_en_returns_error(tmp_path):
    """Missing en.json is always an error regardless of module_type."""
    for mtype in ('core', 'official', 'community'):
        mod = tmp_path / f'mod_{mtype}'
        mod.mkdir()
        (mod / 'manifest.json').write_text(_manifest(mtype), encoding='utf-8')
        _write_i18n(mod, ['pl', 'de', 'fr', 'es'])  # en missing

        results = validate_i18n(mod)

        en_errors = [r for r in results if 'en.json' in r[1]]
        assert en_errors, f'{mtype}: expected en.json error'
        assert en_errors[0][0] == 'error', f'{mtype}: en.json must be error severity'


@pytest.mark.unit
def test_missing_i18n_directory_core(tmp_path):
    """Missing i18n/ dir on core module → ('error', ...)."""
    mod = tmp_path / 'test_mod'
    mod.mkdir()
    (mod / 'manifest.json').write_text(_manifest('core'), encoding='utf-8')

    results = validate_i18n(mod)

    assert len(results) == 1
    severity, msg = results[0]
    assert severity == 'error'
    assert 'missing i18n/' in msg


@pytest.mark.unit
def test_missing_i18n_directory_community(tmp_path):
    """Missing i18n/ dir on community module → ('warning', ...)."""
    mod = tmp_path / 'test_mod'
    mod.mkdir()
    (mod / 'manifest.json').write_text(_manifest('community'), encoding='utf-8')

    results = validate_i18n(mod)

    assert len(results) == 1
    severity, msg = results[0]
    assert severity == 'warning'
    assert 'missing i18n/' in msg


@pytest.mark.unit
def test_missing_manifest_defaults_to_community(tmp_path):
    """No manifest.json → treated as community (warning severity)."""
    mod = tmp_path / 'test_mod'
    mod.mkdir()
    # No manifest.json, no i18n/ either

    results = validate_i18n(mod)

    assert len(results) == 1
    severity, msg = results[0]
    assert severity == 'warning'
    assert 'missing i18n/' in msg


@pytest.mark.unit
def test_malformed_manifest_defaults_to_community(tmp_path):
    """Invalid JSON in manifest.json → treated as community."""
    mod = tmp_path / 'test_mod'
    mod.mkdir()
    (mod / 'manifest.json').write_text('{bad json', encoding='utf-8')

    results = validate_i18n(mod)

    assert len(results) == 1
    severity, _ = results[0]
    assert severity == 'warning'


@pytest.mark.unit
def test_official_module_missing_lang_returns_error(tmp_path):
    """Official module missing a non-english lang → error."""
    mod = tmp_path / 'test_mod'
    mod.mkdir()
    (mod / 'manifest.json').write_text(_manifest('official'), encoding='utf-8')
    _write_i18n(mod, ['en', 'pl', 'de', 'es'])  # fr missing

    results = validate_i18n(mod)

    assert len(results) == 1
    severity, msg = results[0]
    assert severity == 'error'
    assert 'fr.json' in msg
