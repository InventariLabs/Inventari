#!/usr/bin/env python
"""Fail when a refusal puts a stored enum value inside a sentence.

Where this comes from. The 2026-11 QA round found a status code in a sentence
in several passes: "Cannot change status from MAINTENANCE to MAINTENANCE" (in
German too: the sentence was translated, the word inside it was the stored
code), the same in the attestation campaigns' status machine, "Type: SUPPLIER"
and "Usage: internal" in journal lines. A catalogue sentence that takes a
``{status}`` parameter and is handed the row's own ``status`` prints the
database's spelling in every language.

What it reads. Every non-test file under ``app/``. A refusal is a call to one
of ``REFUSAL_CALLS`` (``ServiceRejectionError``, ``get_error_message``, …), or
a ``raise`` of an exception class whose message is an f-string. A *stored
value* is an expression that names one: ``x.status``, ``x.status.value``,
``new_status``, ``doc.type.value`` — the last identifier (after ``.value`` /
``.name``) is, or ends in, one of ``STORED_NAMES``. One that is handed to
a keyword argument of a refusal, or interpolated into its f-string, is a
finding. A call around it (``status_label(x.status)``) is a resolver and
ends the finding: the value is put in words before it reaches the sentence.

The ledger. ``raw_stored_values_baseline.txt`` holds ``path::call(kw=expr)``
entries for the sites that still do this; the goal is an empty file and a new
site fails. ``--write-baseline`` rewrites it. Every entry is a screen that
shows a code where a word belongs.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / 'app'
BASELINE = Path(__file__).resolve().parent / 'raw_stored_values_baseline.txt'

REFUSAL_CALLS = frozenset(
    {
        'ServiceRejectionError',
        'get_error_message',
        'get_plural_error_message',
        'translated',
        'ValidationException',
        'ConflictException',
        'NotFoundException',
        'ForbiddenException',
        'BadRequestException',
    }
)

#: Exception classes whose f-string message is a sentence a reader sees.
SENTENCE_EXCEPTIONS = REFUSAL_CALLS | {'ValueError', 'HTTPException'}

#: The word a stored column or enum goes by, as the last part of a name.
STORED_NAMES = frozenset(
    {
        'status',
        'state',
        'kind',
        'usage',
        'type',
        'role',
        'mode',
        'stage',
        'reason_code',
        'severity',
        'priority',
    }
)


def _terminal(node: ast.expr) -> str | None:
    """The identifier a value expression ends in, ``.value`` / ``.name`` peeled."""
    while isinstance(node, ast.Attribute) and node.attr in {'value', 'name'}:
        node = node.value
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def is_stored_value(node: ast.expr) -> bool:
    """Whether ``node`` reads as a stored code, not a word."""
    name = _terminal(node)
    if name is None:
        return False
    name = name.lstrip('_').lower()
    return name in STORED_NAMES or any(name.endswith(f'_{w}') for w in STORED_NAMES)


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ''


def findings_in(rel: str, tree: ast.AST) -> set[str]:
    """``path::call(kw=expr)`` for each stored value a refusal interpolates."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _callee(node)
        if callee in REFUSAL_CALLS:
            for keyword in node.keywords:
                if keyword.arg and is_stored_value(keyword.value):
                    found.add(
                        f'{rel}::{callee}({keyword.arg}={ast.unparse(keyword.value)})'
                    )
        if callee in SENTENCE_EXCEPTIONS:
            for argument in [*node.args, *(k.value for k in node.keywords)]:
                if not isinstance(argument, ast.JoinedStr):
                    continue
                for part in argument.values:
                    if isinstance(part, ast.FormattedValue) and is_stored_value(
                        part.value
                    ):
                        found.add(f'{rel}::{callee}(f"{{{ast.unparse(part.value)}}}")')
    return found


def scan(app_root: Path = APP_ROOT) -> set[str]:
    found: set[str] = set()
    for path in sorted(app_root.rglob('*.py')):
        parts = path.relative_to(app_root).parts
        if (
            'tests' in parts
            or 'architecture_lint' in parts
            or path.name.startswith('test_')
        ):
            continue
        rel = 'app/' + '/'.join(parts)
        found |= findings_in(rel, ast.parse(path.read_text(encoding='utf-8')))
    return found


def baseline(path: Path = BASELINE) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.startswith('#')
    }


HEADER = (
    '# Refusals and journal sentences that interpolate a stored enum value\n'
    '# (scripts/check_raw_stored_values_in_refusals.py). Each line is a site that\n'
    "# prints the database's spelling of a status, type or usage where a word\n"
    '# belongs. Goal: empty. Refresh only with --write-baseline.\n'
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-baseline', action='store_true')
    args = parser.parse_args(argv)
    found = scan()
    if args.write_baseline:
        BASELINE.write_text(
            HEADER + ''.join(f'{e}\n' for e in sorted(found)), encoding='utf-8'
        )
        print(f'raw stored values in refusals: {len(found)} site(s) recorded')
        return 0
    new = sorted(found - baseline())
    if new:
        print(
            f'raw stored values in refusals: {len(new)} NEW site(s)\n', file=sys.stderr
        )
        for entry in new:
            print(f'  {entry}', file=sys.stderr)
        print(
            '\nPut the value in words before it enters the sentence: hand the\n'
            'refusal a catalogue word (or a keyed label function) instead of the\n'
            "row's own status/type/usage.",
            file=sys.stderr,
        )
        return 1
    stale = sorted(baseline() - found)
    if stale:
        print('fixed — remove from the baseline (--write-baseline):', file=sys.stderr)
        for entry in stale:
            print(f'  {entry}', file=sys.stderr)
        return 1
    print(f'raw stored values in refusals: {len(found)} site(s), all in the baseline')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
