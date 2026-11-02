"""The refusal-code page names the keys a raise chooses at run time.

The generator collected only a literal first argument of
``ServiceRejectionError``. A raise that picks its key — from a conditional,
a table of refusals, or a parameter its callers fill — answered a code the
page never listed, and the drift check still said the page was in sync: the
outbound URL guard's ``LLM_BASE_URL_PRIVATE`` was one. The keys of such a
raise are as static as a literal one, only written a step away, so the
generator follows them; a raise it cannot follow fails the generator rather
than leaving a code off the page.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'generate_error_codes.py'


def _generator():
    spec = importlib.util.spec_from_file_location('generate_error_codes', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _keys(app_root: Path) -> set[str]:
    return {key for key, _ in _generator().raised_refusals(app_root)}


def _app(tmp_path: Path, body: str) -> Path:
    app_root = tmp_path / 'app'
    app_root.mkdir()
    (app_root / 'thing_service.py').write_text(body, encoding='utf-8')
    return app_root


def test_a_literal_key_is_collected(tmp_path: Path) -> None:
    app = _app(tmp_path, "raise ServiceRejectionError('thing_gone')\n")

    assert _keys(app) == {'thing_gone'}


def test_a_refusal_built_for_a_router_is_collected(tmp_path: Path) -> None:
    app = _app(tmp_path, "raise catalogue_refusal('thing_unreadable', field='file')\n")

    assert _keys(app) == {'thing_unreadable'}


def test_both_branches_of_a_chosen_key_are_collected(tmp_path: Path) -> None:
    app = _app(
        tmp_path,
        'def guard(reason):\n'
        "    key = 'thing_loopback' if reason == 'loopback' else 'thing_private'\n"
        '    raise ServiceRejectionError(key, host=1)\n',
    )

    assert _keys(app) == {'thing_loopback', 'thing_private'}


def test_every_value_of_a_refusal_table_is_collected(tmp_path: Path) -> None:
    app = _app(
        tmp_path,
        "_REFUSALS = {'IN': 'thing_in', 'OUT': 'thing_out'}\n"
        'def guard(kind, status):\n'
        '    raise ServiceRejectionError(_REFUSALS[kind])\n'
        'def press(status):\n'
        '    already = _REFUSALS.get(status)\n'
        '    if already is not None:\n'
        '        raise ServiceRejectionError(already)\n',
    )

    assert _keys(app) == {'thing_in', 'thing_out'}


def test_a_key_parameter_is_read_from_its_default_and_its_callers(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path,
        "def refuse(value, *, refusal='thing_default'):\n"
        '    raise ServiceRejectionError(refusal)\n'
        'def parse(value, error_key):\n'
        '    raise ServiceRejectionError(error_key)\n'
        "refuse(1, refusal='thing_by_keyword')\n"
        "parse(1, 'thing_by_position')\n",
    )

    assert _keys(app) == {
        'thing_default',
        'thing_by_keyword',
        'thing_by_position',
    }


def test_a_subclass_of_the_refusal_is_followed(tmp_path: Path) -> None:
    app = _app(
        tmp_path,
        'class SchemaError(ServiceRejectionError):\n'
        '    pass\n'
        'class HeldError(ServiceRejectionError):\n'
        "    def __init__(self, owner, key='thing_held'):\n"
        '        super().__init__(key, owner=owner)\n'
        "raise SchemaError('thing_not_a_number')\n"
        "raise SchemaError.translated('thing_by_factory')\n"
        "raise HeldError('Ann', key='thing_held_elsewhere')\n",
    )

    assert _keys(app) == {
        'thing_not_a_number',
        'thing_by_factory',
        'thing_held',
        'thing_held_elsewhere',
    }


def test_a_key_the_generator_cannot_follow_fails_it(tmp_path: Path) -> None:
    app = _app(
        tmp_path,
        'def guard(row):\n    raise ServiceRejectionError(row.reason)\n',
    )

    with pytest.raises(SystemExit, match=r'thing_service\.py:2'):
        _keys(app)


def test_a_key_parameter_nobody_fills_fails_it(tmp_path: Path) -> None:
    # No default and no call that passes it: the page could not list the key,
    # and the check used to say it was in sync all the same.
    app = _app(
        tmp_path,
        'def refuse(key):\n    raise ServiceRejectionError(key)\n',
    )

    with pytest.raises(SystemExit, match=r'thing_service\.py:1'):
        _keys(app)


def test_a_coded_refusal_is_listed_by_its_own_code(tmp_path: Path) -> None:
    # The focus and profile refusals answer the lowercase code they pass as
    # ``code=``, not the upper-cased key: the page has to name what is on the wire.
    app = _app(
        tmp_path,
        'class CodedRejectionError(ServiceRejectionError):\n'
        '    pass\n'
        'class FocusError(CodedRejectionError):\n'
        '    pass\n'
        "raise FocusError('thing_unregistered', code='unknown_thing', module='x')\n"
        "raise ServiceRejectionError('thing_gone')\n",
    )

    refusals = _generator().raised_refusals(app)

    assert refusals == {
        ('thing_unregistered', 'unknown_thing'),
        ('thing_gone', None),
    }


def test_a_coded_refusal_picks_up_every_code_a_conditional_can_choose(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path,
        'class CodedRejectionError(ServiceRejectionError):\n'
        '    pass\n'
        'def refuse(late):\n'
        "    code = 'too_late' if late else 'too_early'\n"
        "    raise CodedRejectionError('thing_timing', code=code)\n",
    )

    assert _generator().raised_refusals(app) == {
        ('thing_timing', 'too_late'),
        ('thing_timing', 'too_early'),
    }


def test_a_coded_refusal_whose_code_cannot_be_followed_fails_it(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path,
        'class CodedRejectionError(ServiceRejectionError):\n'
        '    pass\n'
        'def refuse(row):\n'
        "    raise CodedRejectionError('thing_timing', code=row.code)\n",
    )

    with pytest.raises(SystemExit, match=r'thing_service\.py:4'):
        _generator().raised_refusals(app)


def test_the_real_focus_and_profile_refusals_are_listed_by_their_wire_codes() -> None:
    refusals = _generator().raised_refusals(SCRIPT.parents[1] / 'app')

    assert ('focus_mode_module_unregistered', 'unknown_module') in refusals
    assert ('profile_switch_unknown_modules', 'unknown_module') in refusals
    assert ('module_dependency_cycle', None) in refusals
    assert ('focus_mode_module_unregistered', None) not in refusals
