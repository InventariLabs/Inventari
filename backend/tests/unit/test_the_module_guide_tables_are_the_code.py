"""The module guide's tables are read against the code they describe.

A pass over the guide found the same two faults again and again: a table that
named a few members of a set as if it were the set (the CLI commands, the
capabilities), and a name the code no longer has or never had (a method of the
Core facade, the table the safety scan reads for its exemption). Both are
checkable without judgement, so they are checked on every run instead of by the
next reader:

* the CLI table lists exactly the ``module`` commands the CLI registers;
* the capability table lists exactly the capabilities the manifest accepts;
* every method a ``core_api`` table names exists on that namespace, and the
  class named in its heading is the namespace's class;
* every name the guide cites from ``module_safety.py`` exists there, and the
  table the guide says lifts the ``app.`` bans is the one the scan reads;
* the trusted-key setting reads, for a real key, every form the guide says it
  reads.

The tables for the facade are deliberately not held to *completeness*: the
guide says they list what a module reaches for most and points at
``docs/subsystems/CORE_API.md`` for the rest.
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import pytest
import typer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.cli._module_signing import _trusted_keys
from app.cli.commands_module import module_app
from app.config import settings
from app.core import module_safety, module_safety_analysis
from app.core.module_manifest_schema import ManifestCapability
from app.core.public_api import core_api


def _repo_root() -> Path:
    return Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))


def _guide() -> str:
    return (_repo_root() / 'MODULES_GUIDE.md').read_text(encoding='utf-8')


def _section(text: str, heading_prefix: str) -> str:
    """The body of the section whose heading starts with *heading_prefix*,
    up to the next heading of the same or a higher level."""
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(heading_prefix)), None
    )
    assert start is not None, f'MODULES_GUIDE.md has no heading {heading_prefix!r}'
    level = len(heading_prefix) - len(heading_prefix.lstrip('#'))
    body: list[str] = []
    for line in lines[start + 1 :]:
        m = re.match(r'^(#+) ', line)
        if m and len(m.group(1)) <= level:
            break
        body.append(line)
    return '\n'.join(body)


@pytest.mark.unit
def test_the_cli_table_lists_every_module_command() -> None:
    table = _section(_guide(), '## 🔧 CLI Commands')
    listed = set(re.findall(r'^\| `module ([a-z-]+)', table, re.MULTILINE))

    registered = {
        command.name or typer.main.get_command_name(command.callback.__name__)
        for command in module_app.registered_commands
        if command.callback is not None
    }

    assert listed == registered, (
        f'in the guide only: {sorted(listed - registered)}; '
        f'registered only: {sorted(registered - listed)}'
    )


@pytest.mark.unit
def test_the_capability_table_lists_every_capability_the_manifest_accepts() -> None:
    table = _section(_guide(), '### Available Capabilities')
    listed = set(re.findall(r'^\| `([a-z]+)` \|', table, re.MULTILINE))

    assert listed == {c.value for c in ManifestCapability}


_NAMED_IN_MODULE_SAFETY = re.compile(
    r'\b(TRUSTED_[A-Z_]+|REPO_SHIPPED_MODULES|CORE_EXEMPTIONS|ALWAYS_ON_MODULES'
    r'|FORBIDDEN_[A-Z_]+|MODULE_IMPORT_SURFACE|CAPABILITY_MAP)\b'
)


@pytest.mark.unit
def test_every_trust_table_the_guide_cites_exists_and_the_scan_reads_the_right_one() -> (
    None
):
    guide = _guide()
    cited = set(_NAMED_IN_MODULE_SAFETY.findall(guide))

    assert cited, 'the guide cites no table of module_safety.py — nothing to check'
    missing = sorted(name for name in cited if not hasattr(module_safety, name))
    assert not missing, f'module_safety.py has no {missing}'

    # The scan lifts the ``app.`` bans for the trusted names that are also
    # shipped here (``TRUSTED_SHIPPED_MODULES``), never for the wider
    # ``TRUSTED_CORE_MODULES``, which holds feature names with no directory.
    # A guide that names the wider set as the one that lifts them tells an author
    # that a directory called ``items`` is trusted.
    assert 'TRUSTED_SHIPPED_MODULES' in cited
    assert 'TRUSTED_CORE_MODULES' not in cited
    assert hasattr(module_safety_analysis, 'TRUSTED_SHIPPED_MODULES')


_CORE_API_HEADING = re.compile(r'^### `core_api\.(\w+)` — `(\w+)`', re.MULTILINE)
_FIRST_COLUMN = re.compile(r'^\| `([a-z_0-9]+)` \|', re.MULTILINE)
_OTHER_ROW = re.compile(r'^\| `core_api\.(\w+)` \| (.*)$', re.MULTILINE)
_METHOD_TOKEN = re.compile(r'`([a-z][a-z_0-9]*)(?:\([^`]*\))?`')


def _core_api_namespace(name: str) -> object:
    assert hasattr(core_api, name), f'core_api has no namespace {name!r}'
    return getattr(core_api, name)


@pytest.mark.unit
def test_every_core_api_method_the_guide_names_exists() -> None:
    guide = _guide()
    headings = _CORE_API_HEADING.findall(guide)
    assert len(headings) >= 5, 'the guide documents no core_api namespaces'

    problems: list[str] = []
    for namespace, class_name in headings:
        target = _core_api_namespace(namespace)
        if type(target).__name__ != class_name:
            problems.append(
                f'core_api.{namespace} is {type(target).__name__}, not {class_name}'
            )
        body = _section(guide, f'### `core_api.{namespace}`')
        for method in _FIRST_COLUMN.findall(body):
            if not hasattr(target, method):
                problems.append(f'core_api.{namespace}.{method} does not exist')

    # The "Other sub-APIs" table: a method is a lowercase token in the row.
    for namespace, description in _OTHER_ROW.findall(guide):
        target = _core_api_namespace(namespace)
        for method in _METHOD_TOKEN.findall(description):
            if not hasattr(target, method):
                problems.append(f'core_api.{namespace}.{method} does not exist')

    assert not problems, '\n'.join(problems)


def _real_public_key() -> str:
    """A public key as the guide's key-generation command prints it: 44
    Base64 characters, the last of them the padding ``=``."""
    raw = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return base64.b64encode(raw).decode()


@pytest.mark.unit
def test_the_trusted_key_setting_reads_every_form_the_guide_says_it_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claim about what a setting accepts is only as good as the value it was
    tried with. The guide's wording is checked against a real, padded key: the
    ``key_id=<key>`` entries it teaches, separated by commas or by newlines, and
    a bare key, which the guide says is not trusted."""
    first, second = _real_public_key(), _real_public_key()
    for separator in (',', '\n'):
        monkeypatch.setattr(
            settings,
            'MODULE_SIGNING_PUBLIC_KEYS',
            f'first={first}{separator}second={second}',
        )
        assert set(_trusted_keys()) == {'first', 'second'}, (
            f'entries separated by {separator!r} must each be trusted'
        )

    # The guide says a key listed without an id is not trusted, and the
    # setting agrees for a real, padded key.
    assert re.search(r'a key listed without one is not\s+trusted', _guide())
    monkeypatch.setattr(settings, 'MODULE_SIGNING_PUBLIC_KEYS', first)
    assert _trusted_keys() == {}
