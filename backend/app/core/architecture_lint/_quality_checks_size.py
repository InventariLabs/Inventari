"""Sync/async pair checks.

Two checks live here:

- ``_check_sync_async_file_pairs`` — detect foo_sync.py / foo_async.py twins.
- ``_check_sync_async_function_pairs`` — detect module-level sync+async
  functions sharing the same name (mirror API in wrapper classes is OK).

File-size checks were removed from this linter entirely: the backend branch
was replaced by function-level ruff metrics (C901 / PLR0915) and the frontend
branch by ESLint function-level metrics (``complexity`` /
``max-lines-per-function``).
"""

from __future__ import annotations

import ast
from pathlib import Path

from ._constants import _is_test_file, _rel, _rel_parts


def _check_sync_async_file_pairs(app_root: Path) -> list[str]:
    """Detect foo_sync.py / foo_async.py file pairs — emit ::notice (non-blocking)."""
    warnings: list[str] = []
    seen_async: dict[Path, Path] = {}

    for py_file in sorted(app_root.rglob('*_async.py')):
        if _is_test_file(py_file, app_root):
            continue
        seen_async[py_file.parent / py_file.name.replace('_async.py', '')] = py_file

    for py_file in sorted(app_root.rglob('*_sync.py')):
        if _is_test_file(py_file, app_root):
            continue
        stem = py_file.parent / py_file.name.replace('_sync.py', '')
        if stem in seen_async:
            async_file = seen_async[stem]
            rel_sync = py_file.relative_to(Path.cwd())
            rel_async = async_file.relative_to(Path.cwd())
            warnings.append(
                f'::notice file={rel_sync},title=Architecture: sync/async file pair detected::'
                f'Found {rel_sync.name} alongside {rel_async.name}. '
                f'Prefer async-only; delete the sync variant or merge into a single async file. '
                f'One of the pair is redundant; the async one is the one to keep.'
            )
    return warnings


def _check_sync_async_function_pairs(app_root: Path) -> list[str]:
    """Detect module-level sync/async function pairs with same name.

    Only free functions defined directly at module top level are compared.
    Methods inside classes are deliberately ignored: wrapper classes
    (e.g. ``AsyncModuleScopedSession``) are a legitimate pattern, and a
    single class cannot hold two methods of the same name anyway — so any
    same-name sync/async collision across classes is an intentional
    mirrored API, not the duplication anti-pattern.
    """
    warnings: list[str] = []
    for py_file in sorted(app_root.rglob('*.py')):
        if _is_test_file(py_file, app_root) or '__pycache__' in _rel_parts(
            py_file, app_root
        ):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        sync_funcs = {
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        async_funcs = {
            node.name for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
        }
        pairs = (sync_funcs & async_funcs) - {'__init__'}
        if pairs:
            rel = _rel(py_file)
            names = ', '.join(sorted(pairs))
            warnings.append(
                f'::warning file={rel},title=Code quality: sync/async function pairs::'
                f'{rel} has sync+async functions with same name: {names}. '
                f'Prefer async-only; remove sync variants.'
            )
    return warnings
