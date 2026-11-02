"""A permission's action comes from one vocabulary, or the manifest says why not.

A permission key is stored by name in every organization's roles, so a word
chosen badly is renamed later only by a data migration in every installation.
The vocabulary is written in the schema, ``module validate`` and ``module
install`` warn about an action outside it, and the one way to keep such an
action is to give the reason in the manifest itself.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli.module_validator import validate_permission_actions
from app.core.module_manifest_schema import PERMISSION_ACTIONS
from manage import app

runner = CliRunner()

_MODULES = Path(__file__).resolve().parents[2] / 'app' / 'modules'


def _module(base: Path, name: str, **manifest: object) -> Path:
    mod = base / name
    mod.mkdir(parents=True)
    body = {'name': name, 'version': '1.0.0', 'module_type': 'community', **manifest}
    (mod / 'manifest.json').write_text(json.dumps(body), encoding='utf-8')
    (mod / 'i18n').mkdir()
    (mod / 'i18n' / 'en.json').write_text('{}', encoding='utf-8')
    return mod


def test_the_vocabulary_is_the_seven_actions_the_modules_use():
    assert PERMISSION_ACTIONS == {
        'read',
        'write',
        'manage',
        'approve',
        'configure',
        'consume',
        'extract',
    }


def test_actions_from_the_vocabulary_are_silent(tmp_path):
    mod = _module(
        tmp_path,
        'noticeboard',
        permissions=['noticeboard:read', 'noticeboard:write', 'items:read'],
    )
    assert validate_permission_actions(mod) == []


def test_an_action_outside_the_vocabulary_is_named_in_a_warning(tmp_path):
    mod = _module(tmp_path, 'noticeboard', permissions=['noticeboard:pin_notes'])
    [warning] = validate_permission_actions(mod)
    assert 'noticeboard' in warning
    assert '"noticeboard:pin_notes"' in warning
    assert 'permission_action_exceptions' in warning


def test_a_core_key_listed_as_a_dependency_is_not_the_modules_word(tmp_path):
    mod = _module(tmp_path, 'noticeboard', permissions=['org:settings:write'])
    assert validate_permission_actions(mod) == []


def test_an_exception_with_its_reason_silences_the_warning(tmp_path):
    mod = _module(
        tmp_path,
        'noticeboard',
        permissions=['noticeboard:pin_notes'],
        permission_action_exceptions={
            'noticeboard:pin_notes': 'Pinning is granted apart from writing.'
        },
    )
    assert validate_permission_actions(mod) == []


def test_an_exception_without_a_reason_explains_nothing(tmp_path):
    mod = _module(
        tmp_path,
        'noticeboard',
        permissions=['noticeboard:pin_notes'],
        permission_action_exceptions={'noticeboard:pin_notes': '  '},
    )
    [warning] = validate_permission_actions(mod)
    assert 'uses an action outside the vocabulary' in warning


@pytest.mark.parametrize(
    'named',
    ['noticeboard:pin_notes', 'noticeboard:read'],
    ids=['a key the module does not define', 'a key in the vocabulary'],
)
def test_an_exception_that_explains_no_key_is_named(tmp_path, named):
    mod = _module(
        tmp_path,
        'noticeboard',
        permissions=['noticeboard:read'],
        permission_action_exceptions={named: 'Why.'},
    )
    [warning] = validate_permission_actions(mod)
    assert f'permission_action_exceptions names "{named}"' in warning


@pytest.mark.parametrize(
    'module_dir',
    sorted(p.parent for p in _MODULES.glob('*/manifest.json')),
    ids=lambda p: p.name,
)
def test_every_shipped_module_keeps_to_the_vocabulary(module_dir):
    assert validate_permission_actions(module_dir) == []


def test_module_validate_warns_and_still_passes(tmp_path):
    _module(tmp_path, 'noticeboard', permissions=['noticeboard:pin_notes'])
    result = runner.invoke(app, ['module', 'validate', '--base-path', str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert 'noticeboard:pin_notes' in result.output


def test_module_install_warns_and_still_installs(tmp_path, capsys):
    from app.cli.module_packaging import _validate_copied_backend

    mod = _module(tmp_path, 'noticeboard', permissions=['noticeboard:pin_notes'])
    _validate_copied_backend(mod)
    assert 'noticeboard:pin_notes' in capsys.readouterr().out
