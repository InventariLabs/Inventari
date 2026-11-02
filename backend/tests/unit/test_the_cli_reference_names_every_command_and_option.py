"""docs/CLI.md must list every command of ``manage.py`` with every option it takes.

The reference was written command by command and then left behind as options
were added: ``module install`` grew ``--rev`` and ``--signature``, ``user
create-admin`` grew ``--name``, and the page still showed the bare name. The
reader of a reference copies the line, so a missing option is an option nobody
learns exists. The command tree is read from the Typer app itself — one source
for both — and each command's row in the page is held against it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import typer.main

from manage import app

_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_CLI_DOC = _ROOT / 'docs' / 'CLI.md'


def _leaf_commands(
    group: Any, prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], Any]]:
    found: list[tuple[tuple[str, ...], Any]] = []
    for name, command in sorted(group.commands.items()):
        path = (*prefix, name)
        if hasattr(command, 'commands'):  # Typer vendors its own click
            found += _leaf_commands(command, path)
        else:
            found.append((path, command))
    return found


def _rows() -> dict[str, str]:
    """The table rows of the page, keyed by the command path they document."""
    rows: dict[str, str] = {}
    for line in _CLI_DOC.read_text(encoding='utf-8').splitlines():
        match = re.match(r'\|\s*`manage\.py ([^`]*)`', line)
        if not match:
            continue
        words: list[str] = []
        for token in match.group(1).split():
            if not re.fullmatch(r'[a-z][a-z0-9-]*', token):
                break  # the first argument or option ends the command path
            words.append(token)
        key = ' '.join(words[:2])
        rows[key] = rows.get(key, '') + line  # a command may span several rows
    return rows


def test_every_command_has_a_row_with_all_its_options() -> None:
    assert _CLI_DOC.exists(), f'{_CLI_DOC} is not reachable from this tree'
    rows = _rows()
    commands = _leaf_commands(typer.main.get_command(app))  # type: ignore[arg-type]
    assert len(commands) > 30, 'the command tree was not read'

    missing_rows: list[str] = []
    missing_options: list[str] = []
    for path, command in commands:
        key = ' '.join(path)
        if key not in rows:
            if key != 'shell':  # documented in prose, not in a table
                missing_rows.append(key)
            continue
        for param in command.params:
            if param.param_type_name != 'option':
                continue
            spellings = [
                o
                for o in (*param.opts, *param.secondary_opts)
                if o.startswith('-') and o not in ('--help', '-h')
            ]
            # One spelling is enough: `-o` for `--output`, `--no-x` for `--x`.
            if spellings and not any(o in rows[key] for o in spellings):
                missing_options.append(f'{key} {spellings[-1]}')

    assert not missing_rows, 'commands without a row in docs/CLI.md: ' + ', '.join(
        missing_rows
    )
    assert not missing_options, (
        'options a command takes that its docs/CLI.md row does not show: '
        + ', '.join(missing_options)
    )
