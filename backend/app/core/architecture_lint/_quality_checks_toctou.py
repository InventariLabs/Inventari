"""TOCTOU risk check (Guardrail 3) and its pattern-matching helpers.

TOCTOU = Time-Of-Check-Time-Of-Use. Detects the read-modify-write pattern
``select()`` followed by ``db.add()/delete/setattr/.field =`` without
``with_for_update()``, ``pg_advisory_xact_lock`` or the
``acquire_advisory_lock`` helper that wraps it.

The pattern helpers (``_has_select``, ``_has_mutation``, ``_has_lock`` …)
live here because they are only used by ``_check_toctou_risk`` and pulling
them out would force callers to import from a separate module for what is
logically one check.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ._constants import _is_test_file, _rel, _rel_parts
from ._run_cache import once_per_run

# Matched textually against the function body, so a lock taken through a
# helper has to be named here too — otherwise extracting the raw SQL into a
# shared function silently blinds this check and 19 already-locked functions
# start reporting as new TOCTOU risks.
_LOCK_PATTERNS = (
    'with_for_update',
    'pg_advisory_xact_lock',
    'acquire_advisory_lock',
)
_TOCTOU_ADMIN_PATTERNS = (
    'seed_',
    'cleanup_',
    'deduplicate_',
    'purge_',
    '_migrate',
    'migrate_',
)


def _strip_comments(src: str) -> str:
    """Remove # comments from source for TOCTOU pattern matching."""
    lines = src.split('\n')
    cleaned = []
    for line in lines:
        ci = line.find('#')
        if ci >= 0:
            in_str, sc = False, None
            for i, c in enumerate(line):
                if c in '"\'' and (i == 0 or line[i - 1] != '\\'):
                    if not in_str:
                        in_str, sc = True, c
                    elif c == sc:
                        in_str = False
            if not in_str:
                line = line[:ci]
        cleaned.append(line)
    return '\n'.join(cleaned)


def _has_select(text: str) -> bool:
    return re.search(r'\bselect\s*\(', text) is not None


def _has_mutation(text: str) -> bool:
    return bool(
        re.search(
            r'\bdb\.add\s*\(|\bdb\.delete\s*\(|\bsetattr\s*\('
            r'|\.status\s*[-+]?=\s*[^=]|\.quantity\s*[-+]?=\s*[^=]',
            text,
        )
    )


def _has_lock(text: str) -> bool:
    return any(p in text for p in _LOCK_PATTERNS)


def _is_delete_pk(text: str) -> bool:
    pk = bool(re.search(r'select\s*\(\s*\w+\s*\)\s*\.where\s*\(\s*\w+\.id\s*==', text))
    return pk and 'db.delete(' in text and 'db.add(' not in text


def _is_state_machine(text: str) -> bool:
    guard = bool(re.search(r'\.status\s*(?:==|!=)\s*[\'"]\w+[\'"]', text))
    terminal = bool(
        re.search(
            r'\.status\s*=\s*[\'"](?:cancelled|completed|archived|deleted|skipped)',
            text,
        )
    )
    if not (guard and terminal):
        return False
    return not bool(re.search(r'\bdb\.add\s*\(|event_bus\.|notify_|\.emit\s*\(', text))


def _is_admin_func(name: str) -> bool:
    return any(p in name.lower() for p in _TOCTOU_ADMIN_PATTERNS)


@once_per_run
def collect_toctou_risks(modules_root: Path) -> dict[str, tuple[str, int, str]]:
    """``{key: (rel, line, function)}`` for every unlocked select + mutation.

    Excludes: tests, pure deletes by PK, state-machine transitions, admin ops.
    """
    found: dict[str, tuple[str, int, str]] = {}
    for py_file in sorted(modules_root.rglob('*.py')):
        if _is_test_file(py_file, modules_root) or '__pycache__' in _rel_parts(
            py_file, modules_root
        ):
            continue
        try:
            src = py_file.read_text(encoding='utf-8')
            tree = ast.parse(src)
        except (SyntaxError, OSError):
            continue
        lines = _strip_comments(src).split('\n')
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) or not hasattr(node, 'end_lineno'):
                continue
            body = '\n'.join(lines[node.lineno - 1 : node.end_lineno])
            if not (_has_select(body) and _has_mutation(body)):
                continue
            if (
                _has_lock(body)
                or _is_delete_pk(body)
                or _is_state_machine(body)
                or _is_admin_func(node.name)
            ):
                continue
            rel = str(_rel(py_file))
            found[f'{rel}:{node.lineno}:{node.name}'] = (rel, node.lineno, node.name)
    return found


def _check_toctou_risk(
    modules_root: Path, baseline: set[str] | None = None
) -> list[str]:
    """Emit ``::error`` for read-modify-write functions without row locking.

    Detects the TOCTOU (Time-Of-Check-Time-Of-Use) pattern:
    ``select()`` followed by ``db.add()/delete/setattr/.field =`` without
    ``with_for_update()`` or ``pg_advisory_xact_lock``.

    Baselined functions emit ``::notice``.
    """
    baseline = baseline or set()
    errors: list[str] = []
    for key, (rel, line, name) in collect_toctou_risks(modules_root).items():
        severity = 'notice' if key in baseline else 'error'
        errors.append(
            f'::{severity} file={rel},line={line},'
            f'title=Architecture: TOCTOU risk::'
            f'{name}() does select + mutation without '
            f'with_for_update(). Use core_api or add '
            f'.with_for_update() to prevent race conditions.'
        )
    return errors
