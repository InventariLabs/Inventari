"""The three shipped example files say exactly what the backend reads.

Every name in `.env.example`, `.env.production.example` and
`backend/.env.example` is a contract with somebody's file the day the
repository opens: an operator copies one, sets the names it carries, and
expects the value to reach the process. The contract has two halves, and this
file checks both against the code rather than against itself:

* a name the backend reads — a `Settings` field, or an `os.getenv` /
  `os.environ` read outside `Settings` — that no example names is a setting
  nobody can discover; and
* a name in an example that nothing reads — not a setting, not interpolated by
  a compose file — is a line documenting itself and doing nothing.

`.env.example` is the field list (its own header says so), so it is also the
file that has to show each setting's default. The switches a test stack turns
on and no operator ever should are kept together in a marked section at the end
of it, so the section can be read as one decision and the rest of the file as
"set these".

The reads are collected from the shipped code under `backend/app`; a tests
directory inside a module is not shipped code, and the variables pytest sets
for itself are pytest's own business rather than configuration.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

from app.config import Settings

pytestmark = pytest.mark.unit

#: The checkout. `docker-compose.yml` mounts it at `/repo` and names it in
#: `INVENTARI_REPO_ROOT`; on the host it is three levels above this file.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

#: The three files an operator may copy from: the field list, the production
#: template, and the one a backend started inside `backend/` reads first.
_EXAMPLES = ('.env.example', '.env.production.example', 'backend/.env.example')

#: `NAME=` at the start of a line — commented-out entries included, since
#: uncommenting is what they are there for.
_ENTRY = re.compile(r'^\s*#?\s*([A-Z][A-Z0-9_]*)=')

#: Heading of the marked section at the end of `.env.example`.
_TEST_ONLY_HEADING = 'Test-only switches'

#: What a test stack turns on and an operator never does. Every one of them is
#: either a protection switched off or a hook handed to a test, which is why
#: they sit apart instead of among the settings an operator sets.
_TEST_ONLY = frozenset(
    {
        'INVENTARI_VALIDATION_CACHE_DIR',
        'LOAD_TESTING',
        'LOAD_TESTING_ACK_UNSAFE',
        'QA_FAULT_INJECTION',
        'TESTING',
        'TESTING_ACK_UNSAFE',
    }
)

#: Values an example deliberately shows instead of the default: secrets this
#: installation has to generate (their placeholder is a refusal, not a value),
#: the connection strings built out of them, an entry shown in the form it is
#: written in rather than as a value, the model the production template
#: suggests for a demo of the AI screen, and the source link the production
#: stack fills in when the example leaves it empty.
_NOT_THE_DEFAULT = frozenset(
    {
        'DATABASE_URL',
        'DB_PASSWORD',
        'FERNET_SALT',
        'LLM_MODEL',
        'MODULE_SIGNING_PUBLIC_KEYS',
        'PRODUCTS_DATABASE_URL',
        'PRODUCTS_DB_PASSWORD',
        'SECRET_KEY',
        'SOURCE_CODE_URL',
    }
)


def _example_names() -> dict[str, set[str]]:
    """Names each example carries, one set per file."""
    found: dict[str, set[str]] = {}
    for example in _EXAMPLES:
        text = (_REPO_ROOT / example).read_text(encoding='utf-8')
        found[example] = {
            match.group(1)
            for line in text.splitlines()
            if (match := _ENTRY.match(line))
        }
    return found


def _settings_fields() -> set[str]:
    return {
        name for name, field in Settings.model_fields.items() if not field.is_required()
    }


def _read_key(node: ast.AST, constants: dict[str, str]) -> str | None:
    """The environment name one node reads, or None when it reads none by name."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        receiver = node.func.value
        is_env = (
            isinstance(receiver, ast.Name) and receiver.id in {'os', 'environ'}
        ) or (isinstance(receiver, ast.Attribute) and receiver.attr == 'environ')
        if is_env and node.func.attr in {'getenv', 'get'} and node.args:
            return _literal(node.args[0], constants)
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
        value = node.value
        is_env = (isinstance(value, ast.Name) and value.id == 'environ') or (
            isinstance(value, ast.Attribute) and value.attr == 'environ'
        )
        if is_env:
            return _literal(node.slice, constants)
    return None


def _literal(node: ast.AST, constants: dict[str, str]) -> str | None:
    """A name written as a string, or as a module-level constant holding one
    — which is how the demo commands name their marker variable."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _environment_reads() -> set[str]:
    """Names the shipped backend reads from the environment outside `Settings`."""
    found: set[str] = set()
    for path in sorted((_REPO_ROOT / 'backend/app').rglob('*.py')):
        if 'tests' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        constants = {
            node.targets[0].id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        for node in ast.walk(tree):
            name = _read_key(node, constants)
            # pytest's own variables: no stack and no operator sets them.
            if name and not name.startswith('PYTEST_'):
                found.add(name)
    return found


def _interpolated_by_compose() -> set[str]:
    """Names a compose file substitutes out of `.env` — a reader like any other."""
    found: set[str] = set()
    for path in sorted(_REPO_ROOT.glob('docker-compose*.yml')):
        text = path.read_text(encoding='utf-8')
        found.update(re.findall(r'\$\{([A-Z][A-Z0-9_]+)', text))
    return found


def _shown_values(example: str) -> dict[str, str]:
    """The value each entry of one example shows (empty for a commented one)."""
    shown: dict[str, str] = {}
    for line in (_REPO_ROOT / example).read_text(encoding='utf-8').splitlines():
        match = _ENTRY.match(line)
        if match:
            shown[match.group(1)] = line.split('=', 1)[1].strip()
    return shown


def _shows_the_default(shown: str, default: object) -> bool:
    """Does the value in the example say what the code falls back to?"""
    if default is None:
        return shown == ''
    if isinstance(default, bool):
        return shown.lower() == str(default).lower()
    if isinstance(default, int):
        return shown.isdigit() and int(shown) == default
    if isinstance(default, float):
        try:
            return float(shown) == default
        except ValueError:
            return False
    return shown == str(default)


def test_the_files_this_measures_are_here() -> None:
    """A missing file would make the checks below measure less than they say."""
    for example in _EXAMPLES:
        assert (_REPO_ROOT / example).is_file(), (
            f'{example} is not reachable: run on the host, or point '
            'INVENTARI_REPO_ROOT at the checkout (docker-compose.yml mounts it).'
        )
    names = _example_names()
    assert all(names.values()), 'an example with no NAME= line is measured as empty'
    # The other checks are set differences, so both sides have to be non-empty
    # or they pass over nothing.
    assert 'DATABASE_URL' in _settings_fields()
    assert 'DEFAULT_LANGUAGE' in _environment_reads()


def test_the_seed_profile_is_not_read_any_more() -> None:
    """`.env.example` offered `SEED_PROFILE` as "used on first startup and
    `make db-seed`" while startup seeded only units of measure and `db seed`
    seeded `clean_core` regardless — a variable an operator could set and watch
    nothing happen. The example dropped it, and the read that made it look live
    went with it: the profile an organization gets is chosen when it is
    onboarded, not by an environment variable.

    Should a start-up path ever read a profile of its own, this is the assertion
    to delete — and the example to name it in again, with what it does.
    """
    assert 'SEED_PROFILE' not in _environment_reads()


def test_every_variable_the_backend_reads_is_named_in_an_example() -> None:
    """The half an operator meets: a setting they cannot find the name of."""
    read = _settings_fields() | _environment_reads()
    named = set().union(*_example_names().values())

    missing = sorted(read - named)
    assert not missing, (
        f'{missing} read by the backend (Settings or os.getenv) and named in none '
        'of .env.example, .env.production.example, backend/.env.example. Name it '
        'in .env.example with the value the code falls back to, and put it in the '
        'marked test-only section if a test stack is what turns it on.'
    )


def test_every_name_in_an_example_is_read_by_something() -> None:
    """The other half: a line in an example that reaches no reader documents
    nothing — which is how a variable becomes a promise nobody keeps."""
    named = set().union(*_example_names().values())
    read = _settings_fields() | _environment_reads() | _interpolated_by_compose()

    unread = sorted(named - read)
    assert not unread, (
        f'{unread} named in the example files and read by nothing: no Settings '
        'field, no os.getenv in the backend, no compose file interpolates them. '
        'Drop them from the example, or point them at the code or stack that '
        'reads them.'
    )


@pytest.mark.parametrize('example', _EXAMPLES)
def test_an_example_shows_the_default_of_every_setting_it_names(example: str) -> None:
    """What `.env.example` promises on its own head: the values are the field
    list, so a reader can see the default without running the code."""
    shown = _shown_values(example)
    mismatched = [
        name
        for name, field in Settings.model_fields.items()
        if name in shown
        and name not in _NOT_THE_DEFAULT
        and not field.is_required()
        and not _shows_the_default(shown[name], field.default)
    ]

    assert not mismatched, (
        f'{example} shows { {name: shown[name] for name in mismatched} } where the '
        'code falls back to something else — the example stops being the way an '
        'operator learns a default. Either show the default, or add the name to '
        '_NOT_THE_DEFAULT with the reason it is not one.'
    )


def test_the_test_only_switches_live_in_the_marked_section() -> None:
    """Test-only switches sit in one marked section of `.env.example`, so an
    operator copying the file reads them as a single decision: leave them out."""
    lines = (_REPO_ROOT / '.env.example').read_text(encoding='utf-8').splitlines()
    headings = [index for index, line in enumerate(lines) if _TEST_ONLY_HEADING in line]

    assert len(headings) == 1, (
        f'expected exactly one {_TEST_ONLY_HEADING!r} heading in .env.example, '
        f'found {len(headings)}'
    )
    heading = headings[0]

    def _names(text_lines: list[str]) -> set[str]:
        return {match.group(1) for line in text_lines if (match := _ENTRY.match(line))}

    section = _names(lines[heading + 1 :])
    elsewhere = _names(lines[:heading])

    assert section == _TEST_ONLY, (
        f'the marked section holds {sorted(section)}, expected '
        f'{sorted(_TEST_ONLY)}: a switch a test stack owns belongs in it, and an '
        'operator-facing setting does not.'
    )
    assert not elsewhere & _TEST_ONLY, (
        f'{sorted(elsewhere & _TEST_ONLY)} set outside the marked section: a '
        'test-only switch has one place, so it can be read as one decision.'
    )
