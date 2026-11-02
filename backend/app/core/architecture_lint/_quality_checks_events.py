"""Emissions that are not tied to the transaction they describe.

``emit`` is an XADD after the fact. Between the commit that changed the
data and the XADD that announces it there is a window, and a process that
dies inside it has changed the data and told nobody -- no retry, no
pending entry, nothing to reclaim, because nothing was ever published.
The window has a mirror image: an ``emit`` before a rollback announces
something that then did not happen, and the webhook goes out anyway.

``emit_transactional`` closes both. It writes the event to the outbox
inside the caller's transaction, so the event and the data commit or roll
back together, and a relay publishes what committed.

This check does not decide which call sites deserve which. It counts
them. The baseline holds the ones that were here when the gate was
written, and a new one has to be a decision somebody makes on purpose --
which is the only thing a ratchet can honestly enforce.

Keyed by ``path::function::event`` rather than by line number: the
baselined sites sit in files that get edited for unrelated reasons, and a
key that moves with them turns every refactor into a false alarm.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ._constants import _is_test_file, _rel, _rel_parts
from ._run_cache import once_per_run

#: Files where ``.emit(`` is the implementation of the bus, not a use of
#: it. The facades forward whatever a caller asked for and the bus itself
#: is what everything else calls.
_NOT_CALL_SITES = (
    ('core', '_event_bus.py'),
    ('core', 'events.py'),
    ('core', 'context.py'),
    ('core', 'public_api', 'events.py'),
    ('core', '_event_deprecations.py'),
)

#: Trees whose writes are the ones an event is supposed to be consistent
#: with. The API layer is included because a router that writes and emits
#: has exactly the same window.
_SCANNED = ('services', 'modules', 'api')


def _event_argument(node: ast.Call) -> str:
    """A stable name for the event being emitted, or ``<dynamic>``.

    ``SystemEvent.ITEM_CREATED``, ``'item.created'`` and a variable are the
    three shapes in the tree. The first two name the event; the third is
    honestly unnameable, and lumping those together per function is better
    than keying on a line number that moves.
    """
    if not node.args:
        return '<none>'
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    if isinstance(first, ast.Attribute):
        return first.attr
    if isinstance(first, ast.Name):
        return f'<{first.id}>'
    return '<dynamic>'


def _is_bare_emit(node: ast.AST) -> bool:
    """``something.emit_async(...)`` -- and not ``emit_transactional_async``.

    ``emit`` stays in the set: the raw ``event_bus.emit`` is the same window
    under its own name, and a module reaching for the bus directly is a call
    site the ratchet still has to see.
    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {'emit', 'emit_async'}
    )


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    """Line number -> name of the function that line belongs to.

    Widest range first, so a nested function overwrites its parent and the
    key names the function the call is actually written in.
    """
    spans = [
        (node.lineno, node.end_lineno or node.lineno, node.name)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and hasattr(node, 'end_lineno')
    ]
    owner: dict[int, str] = {}
    for start, end, name in sorted(spans, key=lambda s: s[0] - s[1]):
        for line in range(start, end + 1):
            owner[line] = name
    return owner


def _scanned_files(app_root: Path) -> list[Path]:
    files: list[Path] = []
    for tree_name in _SCANNED:
        root = app_root / tree_name
        if not root.is_dir():
            continue
        for py_file in sorted(root.rglob('*.py')):
            parts = _rel_parts(py_file, app_root)
            if _is_test_file(py_file, app_root) or '__pycache__' in parts:
                continue
            files.append(py_file)
    return files


@once_per_run
def collect_bare_emits(app_root: Path) -> dict[str, tuple[Path, int, str]]:
    """``{key: (file, line, event)}`` for every non-transactional emit."""
    found: dict[str, tuple[Path, int, str]] = {}
    for py_file in _scanned_files(app_root):
        if _rel_parts(py_file, app_root) in _NOT_CALL_SITES:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, OSError, UnicodeDecodeError, ValueError):
            continue
        owner = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if not _is_bare_emit(node):
                continue
            assert isinstance(node, ast.Call)
            event = _event_argument(node)
            function = owner.get(node.lineno, '<module>')
            key = f'{_rel(py_file)}::{function}::{event}'
            found.setdefault(key, (py_file, node.lineno, event))
    return found


def _check_bare_emit(app_root: Path, baseline: set[str] | None = None) -> list[str]:
    """Emit ``::error`` for a new emit that is not tied to a transaction."""
    baseline = baseline or set()
    errors: list[str] = []
    for key, (py_file, line, event) in sorted(collect_bare_emits(app_root).items()):
        severity = 'notice' if key in baseline else 'error'
        errors.append(
            f'::{severity} file={_rel(py_file)},line={line},'
            f'title=Architecture: emit outside the transaction::'
            f'{event} is published with emit() after the write commits, so a '
            f'crash in between loses it and a rollback after it announces '
            f'something that did not happen. Use '
            f'core_api.events.emit_transactional_async(db, ...) — it writes the '
            f'event to the outbox in the same transaction.'
        )
    return errors
