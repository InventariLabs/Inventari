"""A manifest icon the frontend cannot draw is reported, not accepted in silence.

``DynamicIcon`` draws a closed list of Lucide icons and falls back to a package
icon for any other name. A community module cannot add to that list, so the
author is told at ``module validate`` and ``module install`` time, with the
icon named and the accepted names in reach.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli.module_validator import validate_manifest_icon
from app.core.manifest_icons import is_drawable_icon
from manage import app

runner = CliRunner()


def _module(base: Path, name: str, icon: str | None) -> Path:
    mod = base / name
    mod.mkdir(parents=True)
    manifest: dict = {
        'name': name,
        'version': '1.0.0',
        'module_type': 'community',
        'capabilities': [],
    }
    if icon is not None:
        manifest['icon'] = icon
    (mod / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (mod / 'i18n').mkdir()
    (mod / 'i18n' / 'en.json').write_text('{}', encoding='utf-8')
    return mod


@pytest.mark.parametrize(
    ('icon', 'drawable'),
    [
        ('shopping-cart', True),
        ('ShoppingCart', True),
        ('shopping_cart', True),
        ('bar-chart-3', True),
        ('sticky-note', False),
        ('', False),
    ],
)
def test_is_drawable_icon_follows_the_frontend_lookup(icon, drawable):
    assert is_drawable_icon(icon) is drawable


def test_an_icon_the_frontend_cannot_draw_is_named_in_a_warning(tmp_path):
    mod = _module(tmp_path, 'noticeboard', 'sticky-note')
    [warning] = validate_manifest_icon(mod)
    assert 'noticeboard' in warning
    assert '"sticky-note"' in warning


def test_a_drawable_or_absent_icon_is_silent(tmp_path):
    assert validate_manifest_icon(_module(tmp_path, 'drawable', 'wrench')) == []
    assert validate_manifest_icon(_module(tmp_path, 'bare', None)) == []


def test_an_unreadable_manifest_is_left_to_the_manifest_check(tmp_path):
    mod = tmp_path / 'broken'
    mod.mkdir()
    (mod / 'manifest.json').write_text('{', encoding='utf-8')
    assert validate_manifest_icon(mod) == []


def test_module_validate_warns_and_still_passes(tmp_path):
    _module(tmp_path, 'noticeboard', 'sticky-note')
    result = runner.invoke(app, ['module', 'validate', '--base-path', str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert 'sticky-note' in result.output


def test_module_install_warns_and_still_installs(tmp_path, capsys):
    from app.cli.module_packaging import _validate_copied_backend

    mod = _module(tmp_path, 'noticeboard', 'sticky-note')
    _validate_copied_backend(mod)
    assert 'sticky-note' in capsys.readouterr().out
