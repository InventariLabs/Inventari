"""The history-comment gate counts narration in comments and docstrings only."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_history_comments.py'


@pytest.fixture(scope='module')
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_history_comments', _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The phrases are split so that this file carries none of them in a comment.
USED = 'used' + ' to'
FORMER = 'former' + 'ly'


@pytest.mark.parametrize(
    'source',
    [
        f'# The row {USED} print eight characters.\n',
        f'x = 1  # {FORMER} a list\n',
        f'"""The module docstring: it {USED} raise."""\n',
        f'def f():\n    """A helper that {FORMER} lived elsewhere."""\n',
        f'class C:\n    """\n    Two lines.\n    The rule {USED} differ.\n    """\n',
    ],
)
def test_narration_in_a_python_comment_or_docstring_is_counted(
    gate: ModuleType, source: str
) -> None:
    assert gate.count_history_lines('a.py', source) == 1


@pytest.mark.parametrize(
    'source',
    [
        f"label = 'it {USED} be'\n",
        f'{FORMER} = 1\n',
        f'def f():\n    return "{FORMER}"\n',
        f'def f():\n    x = """{FORMER}"""\n    return x\n',
        f'# The helper is {USED} build the key.\n',
        '# A document that no longer exists is skipped.\n',
        '# The rule names the constraint.\n',
    ],
)
def test_a_literal_an_identifier_or_a_present_tense_use_is_not_counted(
    gate: ModuleType, source: str
) -> None:
    assert gate.count_history_lines('a.py', source) == 0


@pytest.mark.parametrize(
    'source, expected',
    [
        (f'// The row {USED} print eight characters.\n', 1),
        (f'/* {FORMER}\n * once\n * the old code */\nconst x = 1;\n', 2),
        (f'const a = 1; // {FORMER} two\n// {USED} three\n', 2),
        (f'{{/* the label {USED} wrap */}}\n', 1),
        (f"const s = 'a // {FORMER}';\n", 0),
        (f'const s = "{USED} /* {FORMER} */";\n', 0),
        (f'const t = `x ${{a}} // {FORMER} ${{b}}`;\n', 0),
        (f'const {FORMER} = 1;\nconst r = /[/]{FORMER}/;\n', 0),
        # a quote inside a comment does not open a string
        (f"// it's fine\n// {USED} x\n", 1),
        (f'const a = b / c; // {FORMER}\n', 1),
    ],
)
def test_typescript_comments_are_read_and_literals_are_not(
    gate: ModuleType, source: str, expected: int
) -> None:
    assert gate.count_history_lines('a.ts', source) == expected


def test_a_file_above_its_baseline_or_new_with_a_hit_fails(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        gate, 'tracked_files', lambda trees: ['grew.py', 'new.py', 'fine.py']
    )
    sources = {
        'grew.py': f'# {FORMER} a\n# {USED} b\n',
        'new.py': f'# {FORMER} a\n',
        'fine.py': '# it names the constraint\n',
    }
    monkeypatch.setattr(gate, '_ROOT', tmp_path)
    for name, text in sources.items():
        (tmp_path / name).write_text(text)
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps({'files': {'grew.py': 1, 'fine.py': 0}}))
    monkeypatch.setattr(gate, 'BASELINE', baseline)

    failures, _ = gate.check(['backend'])

    assert [message.split(':')[0] for message in failures] == ['grew.py', 'new.py']


def test_a_file_below_its_baseline_passes_with_a_notice(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gate, 'tracked_files', lambda trees: ['a.py'])
    monkeypatch.setattr(gate, '_ROOT', tmp_path)
    (tmp_path / 'a.py').write_text('# clean\n')
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps({'files': {'backend/app/a.py': 3}}))
    monkeypatch.setattr(gate, 'BASELINE', baseline)

    failures, notices = gate.check(['backend'])

    assert failures == []
    assert notices == ['backend/app/a.py: 0 now, 3 recorded.']


def test_a_comment_is_reported_on_its_own_line_after_jsx_text_and_division(
    gate: ModuleType,
) -> None:
    # An apostrophe in JSX text, a closing tag and a division must not swallow
    # a newline: a finding names the line the comment is on.
    source = (
        "const a = <p>don't</p>;\n"
        'const b = c / d;\n'
        'const e = <i>x</i>;\n'
        f'// it {USED} be\n'
    )
    assert list(gate.typescript_comment_lines(source)) == [4]
