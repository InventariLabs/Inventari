"""Public-API ORM leak check (Guardrail 2).

Catches PublicAPI methods that return ORM models or accept them as
parameters instead of DTOs — leaking the ORM to module callers breaks the
CoreAPI abstraction. Only public functions/methods (names not starting with
``_``) are checked: private helpers are Core-internal and may handle ORM
objects before converting them to DTOs.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ._constants import _rel


def re_search_word(text: str, word: str) -> bool:
    """Check if *word* appears as a whole word in *text*."""
    return re.search(rf'\b{re.escape(word)}\b', text) is not None


def _param_annotations(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[str, str]]:
    """Return ``(param_name, annotation_source)`` for every annotated parameter."""
    args = node.args
    params: list[tuple[str, str]] = []
    for arg in (
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        args.vararg,
        args.kwarg,
    ):
        if arg is not None and arg.annotation is not None:
            params.append((arg.arg, ast.unparse(arg.annotation)))
    return params


def _check_public_api_return_types(  # noqa: C901 - existing complexity/size
    public_api_dir: Path, baseline: set[str] | None = None
) -> list[str]:
    """Emit ``::error`` when CoreAPI methods leak ORM models in signatures.

    Public API methods (``app/core/public_api/*.py``) must expose only DTO
    types (``*DTO``) in return annotations and parameter annotations — never
    raw SQLAlchemy model classes (``Item``, ``User``, etc.). Leaking a model
    to modules breaks the abstraction. Private helpers (``_``-prefixed) are
    Core-internal and exempt.
    """
    baseline = baseline or set()
    errors: list[str] = []
    model_names: set[str] = set()
    for py_file in sorted(public_api_dir.rglob('*.py')):
        if py_file.name == '__init__.py':
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, OSError):
            continue

        # Collect names imported from app.models.*
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith('app.models')
            ):
                for alias in node.names:
                    model_names.add(alias.asname or alias.name)

    if not model_names:
        return errors

    # Check signatures in public_api functions
    for py_file in sorted(public_api_dir.rglob('*.py')):
        if py_file.name == '__init__.py':
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Private helpers are Core-internal — they may handle ORM objects
            # before converting them to DTOs.
            if node.name.startswith('_'):
                continue
            rel = _rel(py_file)
            if node.returns is not None:
                return_src = ast.unparse(node.returns)
                for model_name in model_names:
                    if re_search_word(return_src, model_name):
                        key = f'{rel}::{node.name}'
                        severity = 'notice' if key in baseline else 'error'
                        errors.append(
                            f'::{severity} file={rel},title=Architecture: CoreAPI model leak::'
                            f'{node.name}() returns ORM model {model_name} '
                            f'instead of a DTO. Use model_validate() to convert '
                            f'before returning.'
                        )
            for param_name, param_src in _param_annotations(node):
                for model_name in model_names:
                    if re_search_word(param_src, model_name):
                        key = f'{rel}::{node.name}#{param_name}'
                        severity = 'notice' if key in baseline else 'error'
                        errors.append(
                            f'::{severity} file={rel},title=Architecture: CoreAPI model leak::'
                            f'{node.name}() accepts ORM model {model_name} as '
                            f'parameter "{param_name}". Accept a DTO or an id '
                            f'and load the model inside Core instead.'
                        )
    return errors


def _iter_public_async_defs(
    node: ast.AST, prefix: str = ''
) -> list[tuple[str, ast.AsyncFunctionDef]]:
    """``(qualname, def)`` for public coroutines, methods and module functions.

    Private (``_``-prefixed) helpers are Core-internal, and nested functions
    are implementation details — neither is part of the facade surface.
    """
    found: list[tuple[str, ast.AsyncFunctionDef]] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            found.extend(_iter_public_async_defs(child, f'{prefix}{child.name}.'))
        elif isinstance(child, ast.AsyncFunctionDef) and not child.name.startswith('_'):
            found.append((f'{prefix}{child.name}', child))
    return found


def _check_coreapi_async_naming(public_api_dir: Path) -> list[str]:
    """Emit ``::error`` for a public CoreAPI coroutine without the ``_async`` suffix.

    The facade's naming rule is that a method a caller has to await says so in
    its name. Without the rule a coroutine named ``create`` reads like the
    synchronous call it is not: a module author who follows the convention
    writes the call without ``await`` and gets a coroutine object back.
    """
    errors: list[str] = []
    for py_file in sorted(public_api_dir.rglob('*.py')):
        if py_file.name == '__init__.py':
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, OSError):
            continue
        rel = _rel(py_file)
        for qualname, _node in _iter_public_async_defs(tree):
            if qualname.rsplit('.', 1)[-1].endswith('_async'):
                continue
            errors.append(
                f'::error file={rel},title=Architecture: CoreAPI async naming::'
                f'{qualname}() is a coroutine without the `_async` suffix. '
                f'A method a caller must await says so in its name — rename '
                f'{qualname}() to {qualname}_async().'
            )
    return errors
