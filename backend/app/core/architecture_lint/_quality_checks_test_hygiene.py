"""An assertion that admits a success and a refusal at once cannot fail.

``assert resp.status_code in (200, 400, 422)`` passes when the endpoint
answers, passes when it refuses, and passes when somebody changes which of
those it does. It reads like cover and is none: twenty-six of them were
found in this suite, and every one had been green through every change to
the code beneath it.

The shape is not always visible to a grep, which is half of why they
accumulated: four of the twenty-six were spelled with ``status.HTTP_*``
constants and missed by a scan that looked for digits. This check parses
instead, so both spellings count the same.

Only test files are scanned, and only ``in`` comparisons inside an
``assert``. A production ``if code in (200, 404)`` is a branch, not a
claim, and a test that deliberately accepts several *successes*
(``in (200, 201)``) is narrowing a shape rather than hedging a verdict —
neither is the thing that cannot fail. The finding is a 2xx and a >= 400
in the same set: the one combination where the assertion has stopped
choosing.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from ._constants import _rel

#: ``status.HTTP_404_NOT_FOUND`` -> 404. The prefix is fixed by starlette.
_HTTP_CONST = re.compile(r'^HTTP_(\d{3})_')


def _status_code(node: ast.AST) -> int | None:
    """The HTTP code an element stands for, written either way."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Attribute):
        match = _HTTP_CONST.match(node.attr)
        if match:
            return int(match.group(1))
    return None


def _mixed_codes(compare: ast.Compare) -> list[int]:
    """Codes of an ``x in (...)`` that holds both an answer and a refusal."""
    if not compare.ops or not isinstance(compare.ops[0], ast.In):
        return []
    container = compare.comparators[0]
    if not isinstance(container, ast.Tuple | ast.List | ast.Set):
        return []
    codes = [
        code
        for code in (_status_code(elt) for elt in container.elts)
        if code is not None
    ]
    if len(codes) < 2:
        return []
    if any(200 <= code < 300 for code in codes) and any(code >= 400 for code in codes):
        return sorted(codes)
    return []


def _test_functions(
    tree: ast.Module,
) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef
        ) and node.name.startswith('test'):
            yield node


def _check_mixed_status_assertions(
    roots: Iterable[Path], baseline: set[str] | None = None
) -> list[str]:
    """Emit a finding per assertion that accepts a 2xx and a 4xx together.

    Keyed by ``path::test_name`` rather than by line, because a line number
    moves whenever anything above it is edited and a baseline keyed on one
    would go stale without anybody touching the finding.
    """
    baseline = baseline or set()
    findings: list[str] = []

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
            for func in _test_functions(tree):
                for node in ast.walk(func):
                    if not isinstance(node, ast.Assert):
                        continue
                    for compare in ast.walk(node.test):
                        if not isinstance(compare, ast.Compare):
                            continue
                        codes = _mixed_codes(compare)
                        if not codes:
                            continue
                        key = f'{rel}::{func.name}'
                        severity = 'notice' if key in baseline else 'error'
                        findings.append(
                            f'::{severity} file={rel},line={node.lineno},'
                            f'title=Test hygiene: assertion cannot fail::'
                            f'{func.name} accepts {codes} — a success and a '
                            f'refusal in one set, so it passes whichever the '
                            f'endpoint does. Name the one code the application '
                            f'returns; if the scenario genuinely reaches two, '
                            f'the test does not pin its own starting state.'
                        )
    return findings
