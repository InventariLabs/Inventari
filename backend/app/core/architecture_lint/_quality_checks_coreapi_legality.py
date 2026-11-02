"""CoreAPI facade signature legality check (Guardrail 4).

Every type named in a public CoreAPI method signature must be importable
from a source a community module may legally reference: ``app.core.*``
(contracts, public_api), the Python stdlib typing surface, or
``AsyncSession``. Types from ``app.schemas`` / ``app.i18n`` / ``app.models``
/ ``app.services`` make the facade unusable for external modules — importing
them trips the module-boundary linter, so the caller is left duck-typing.
With ``from __future__ import annotations`` such leaks never crash at
runtime, which is why they need a dedicated lint gate.

Baselined findings emit ``::notice``; new findings emit ``::error`` and fail
the lint run. Baseline keys have the form
``relative/path.py::ClassName.method::TypeName``.
"""

from __future__ import annotations

import ast
import builtins as _builtins_module
from collections.abc import Iterator
from pathlib import Path

from ._constants import _rel

# Modules a community module may import from in type annotations.
_ALLOWED_IMPORT_PREFIXES = (
    'app.core',
    'typing',
    'typing_extensions',
    'collections',
    'datetime',
    'uuid',
    'decimal',
    'pathlib',
    'io',
    'enum',
    'builtins',
)
# sqlalchemy is Core-internal; only the session handle is signature-legal.
_ALLOWED_SQLALCHEMY_MODULE = 'sqlalchemy.ext.asyncio'
_ALLOWED_SQLALCHEMY_NAMES = frozenset({'AsyncSession'})
# pydantic models themselves belong in contracts; only the base class is
# acceptable in signatures (e.g. generic helpers).
_ALLOWED_PYDANTIC_NAMES = frozenset({'BaseModel'})

_BUILTINS = set(dir(_builtins_module)) | {'None'}


def _module_level_names(tree: ast.Module) -> set[str]:
    """Names defined at module top level (classes, aliases, TypeVars...)."""
    names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
    return names


def _import_sources(tree: ast.AST) -> dict[str, str]:
    """Map every imported name to its source module.

    TYPE_CHECKING imports are included on purpose: they are still part of
    the contract a caller must satisfy to type-check against the facade.
    """
    sources: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # Relative imports stay inside app.core.public_api — always legal.
            module = 'app.core.public_api' if node.level else (node.module or '')
            for alias in node.names:
                sources[alias.asname or alias.name] = module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                sources[alias.asname or alias.name] = alias.name
    return sources


def _is_allowed(name: str, module: str) -> bool:
    if any(module == p or module.startswith(p + '.') for p in _ALLOWED_IMPORT_PREFIXES):
        return True
    if module == _ALLOWED_SQLALCHEMY_MODULE:
        return name in _ALLOWED_SQLALCHEMY_NAMES
    if module == 'pydantic':
        return name in _ALLOWED_PYDANTIC_NAMES
    return False


def _annotation_names(expr: ast.AST) -> set[str]:
    """All bare names referenced by an annotation expression.

    Attribute roots are included (``pagination.X`` yields ``pagination``);
    string constants (Literal values, forward-ref contents) are not names
    and are skipped by construction.
    """
    return {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}


def _iter_public_functions(
    node: ast.AST, prefix: str = ''
) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Yield ``(qualname, funcdef)`` for public module functions and methods.

    Private (``_``-prefixed) callables are Core-internal and exempt; nested
    functions are implementation details and are not descended into.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _iter_public_functions(child, prefix + child.name + '.')
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not child.name.startswith('_'):
                yield prefix + child.name, child


def _func_annotations(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    args = func.args
    annotations: list[ast.AST] = []
    for arg in (
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        args.vararg,
        args.kwarg,
    ):
        if arg is not None and arg.annotation is not None:
            annotations.append(arg.annotation)
    if func.returns is not None:
        annotations.append(func.returns)
    return annotations


def _check_coreapi_signature_legality(
    public_api_dir: Path, baseline: set[str] | None = None
) -> list[str]:
    """Emit ``::error`` when CoreAPI signatures reference non-importable types.

    Public methods of ``app/core/public_api/*.py`` may only annotate with
    types a community module can legally import (see module docstring).
    Findings present in *baseline* are downgraded to ``::notice``.
    """
    baseline = baseline or set()
    findings: list[str] = []
    for py_file in sorted(public_api_dir.rglob('*.py')):
        if py_file.name == '__init__.py':
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, OSError):
            continue

        sources = _import_sources(tree)
        local_names = _module_level_names(tree)
        rel = _rel(py_file)

        for qualname, func in _iter_public_functions(tree):
            reported: set[str] = set()
            for annotation in _func_annotations(func):
                for name in _annotation_names(annotation):
                    if name in _BUILTINS or name in local_names or name in reported:
                        continue
                    module = sources.get(name)
                    if module is None:
                        # Unresolved (forward ref to a name never imported) —
                        # not a legality finding; broken refs are mypy's job.
                        continue
                    if _is_allowed(name, module):
                        continue
                    reported.add(name)
                    key = f'{rel}::{qualname}::{name}'
                    severity = 'notice' if key in baseline else 'error'
                    findings.append(
                        f'::{severity} file={rel},'
                        f'title=Architecture: CoreAPI signature legality::'
                        f"{qualname}() references '{name}' from '{module}' in "
                        f'its signature. Community modules cannot import this '
                        f'type — expose a DTO from app.core.contracts instead.'
                    )
    return findings
