"""A test that skips itself has to say why, who answers for it, and until when.

``pytest.skip()`` inside a test body turns a missing precondition into a
yellow ``s`` in a line of green dots, and nobody reads that line. Fifteen
were in this suite; eleven fired in every run. One asked for a route that
had never existed and skipped on the 404, so tenant isolation of product
templates was checked by nothing. Another looked for a template directory
under a path that had been wrong since the day it was written. Both were
green for months.

Most of those tests could set their own precondition, and now do. What is
left skips because of where it runs — the three documentation-drift tests that
used to sit here read a repository the backend container now mounts — and those
are written down in
``app/core/test_skip_baseline.txt``, one entry per test, with an owner and an
expiry, because an environmental reason is also a premise that stops being
true without anyone noticing.

Two findings, both blocking:

- a ``pytest.skip()`` call in a test that has no entry — make the test assert
  its precondition, or register the reason;
- an entry whose test no longer skips — the list may not describe code that
  is gone, or it becomes the next thing nobody reads.

Registered skips come out as ``::notice``. Fixtures and helpers outside test
functions are not scanned: a fixture that skips says so to every test that
uses it, and ``skipif`` markers are visible at the definition.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from ._constants import _rel


def _first_pytest_skip(func: ast.AST) -> ast.Call | None:
    """The first ``pytest.skip(...)`` anywhere inside *func*, nested helpers included."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'skip'
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'pytest'
        ):
            return node
    return None


def _tests_with_node_ids(
    tree: ast.Module,
) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Top-level tests and test methods, named the way pytest names them."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(
                    member, ast.FunctionDef | ast.AsyncFunctionDef
                ) and member.name.startswith('test'):
                    yield f'{node.name}::{member.name}', member
        elif isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef
        ) and node.name.startswith('test'):
            yield node.name, node


def _check_test_skips(roots: Iterable[Path], registered: set[str]) -> list[str]:
    """Emit a finding per unregistered skip and per entry with no skip behind it.

    Keyed by pytest node id without a line number: an entry keyed on a line
    stops matching the moment anything above it is edited.
    """
    findings: list[str] = []
    skipping: set[str] = set()

    for root in roots:
        if not root.exists():
            continue
        for py_file in sorted(root.rglob('test_*.py')):
            if '__pycache__' in py_file.parts:
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding='utf-8'))
            except (SyntaxError, OSError, UnicodeDecodeError, ValueError):
                continue
            rel = _rel(py_file)
            for node_id, func in _tests_with_node_ids(tree):
                call = _first_pytest_skip(func)
                if call is None:
                    continue
                key = f'{rel}::{node_id}'
                skipping.add(key)
                if key in registered:
                    findings.append(
                        f'::notice file={rel},line={call.lineno},'
                        f'title=Test hygiene: registered skip::{node_id}'
                    )
                    continue
                findings.append(
                    f'::error file={rel},line={call.lineno},'
                    f'title=Test hygiene: unregistered skip::{node_id} calls '
                    f'pytest.skip() with no entry in app/core/test_skip_baseline.txt. '
                    f'If the test can set up what it is waiting for, do that and '
                    f'assert it; a skip on missing data passes when the feature is '
                    f'gone. If the reason is the environment, register it: '
                    f'"{key} | owner=<who> | expires=<YYYY-MM-DD> | <reason>".'
                )

    for key in sorted(registered - skipping):
        findings.append(
            f'::error file=app/core/test_skip_baseline.txt,'
            f'title=Test hygiene: stale skip entry::{key} no longer skips '
            f'(or no longer exists). Delete the entry.'
        )
    return findings
