"""Core services never import the ``core_api`` facade.

The facade exists for modules. A service going through it loops back
(``services → core_api → services``) and hides the dependency between two
services behind a middleman: the reader of ``items/_stock_quant.py`` cannot
see that it calls ``stock_moves_service`` and ``valuation_service``, because
the import says ``core_api``. The one-number state model (ADR-022) turns
those doors into direct imports (inside the functions, as today, because the
import cycle is why the facade was used); without a rule, the next change
quietly brings the facade back.

The list of places that may still import the facade is empty, and a new line
in it is a service that went back through the middleman. A place is keyed
``path::Class::function`` — the innermost function holding the import,
``<module>`` at module level — never by line, which moves whenever anything
above it is edited. Two findings, both blocking:

- a place with no entry in ``app/core/services_public_api_import_baseline.txt``
  — import the service it calls directly, inside the function when the
  import cycle demands it;
- an entry with nothing left behind it — delete the line, then rewrite the
  sizes, so the room a paid debt leaves cannot be spent by the next one.

Docstrings that mention the facade are prose, not imports, and the suite
under ``app/services/**`` may use the facade the way any test may.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from pathlib import Path

from ._constants import _is_test_file, _rel, _rel_parts

#: The facade this rule is about. Submodules count: they are the same door.
_FACADE = 'app.core.public_api'
#: Its package: ``from app.core import public_api`` is the same door.
_FACADE_PARENT = 'app.core'


def _resolve_import(node: ast.ImportFrom, package: tuple[str, ...]) -> str:
    """The dotted module a ``from`` import reads, relative imports included.

    ``from app.core.public_api import x`` names the module outright; inside
    ``app/services``, ``from ..core.public_api import x`` is the same door
    spelled relative — Python resolves it against the file's package, and so
    does this. A bare ``from . import public_api`` names a submodule of the
    file's own package, not the facade.
    """
    parts = tuple((node.module or '').split('.')) if node.module else ()
    if not node.level:
        return '.'.join(parts)
    base = package[: len(package) - (node.level - 1)]
    return '.'.join((*base, *parts))


def _from_spelling(node: ast.ImportFrom) -> str:
    names = ', '.join(alias.name for alias in node.names)
    return f'from {"." * node.level}{node.module or ""} import {names}'


def _imports_facade(stmt: ast.stmt, package: tuple[str, ...]) -> str | None:
    """The import statement spelled as source, or None when it is not one.

    The facade has four spellings, each legal relative as well:
    ``from app.core.public_api import x`` and ``from
    app.core.public_api.stock import x`` name the module outright; ``import
    app.core.public_api[.x]`` is the same dependency as a dotted name;
    ``from app.core import public_api`` imports it as a name from its parent
    package. ``from app.core import db_facade`` and friends are other doors
    and not this rule's business.
    """
    if isinstance(stmt, ast.ImportFrom):
        module = _resolve_import(stmt, package)
        if module == _FACADE or module.startswith(_FACADE + '.'):
            return _from_spelling(stmt)
        if module == _FACADE_PARENT and any(
            alias.name == 'public_api' for alias in stmt.names
        ):
            return _from_spelling(stmt)
        return None
    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            if alias.name == _FACADE or alias.name.startswith(_FACADE + '.'):
                return f'import {alias.name}'
    return None


def _imports_by_scope(
    tree: ast.Module, package: tuple[str, ...]
) -> Iterator[tuple[str, int, str]]:
    """``(scope, line, what)`` for every facade import, scope named with its classes."""

    def visit(node: ast.AST, scope: tuple[str, ...]) -> Iterator[tuple[str, int, str]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                yield from visit(child, (*scope, child.name))
                continue
            if isinstance(child, ast.Import | ast.ImportFrom):
                what = _imports_facade(child, package)
                if what is not None:
                    yield '::'.join(scope) or '<module>', child.lineno, what
                continue
            yield from visit(child, scope)

    yield from visit(tree, ())


def collect_facade_imports(services_root: Path) -> dict[str, tuple[Path, int, str]]:
    """``{key: (file, line, what)}``, the first import of each place."""
    found: dict[str, tuple[Path, int, str]] = {}
    if not services_root.is_dir():
        return found
    app_root = services_root.parent
    for py_file in sorted(services_root.rglob('*.py')):
        if '__pycache__' in _rel_parts(py_file, services_root):
            continue
        if _is_test_file(py_file, services_root):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, OSError, UnicodeDecodeError, ValueError):
            continue
        package = ('app', *_rel_parts(py_file, app_root)[:-1])
        for scope, line, what in _imports_by_scope(tree, package):
            found.setdefault(f'{_rel(py_file)}::{scope}', (py_file, line, what))
    return found


def _check_services_facade_imports(
    services_root: Path, baseline: Iterable[str] = ()
) -> list[str]:
    """A finding per unlisted place, and one per listed place that is gone."""
    listed = set(baseline)
    found = collect_facade_imports(services_root)
    findings: list[str] = []
    for key, (py_file, line, what) in sorted(found.items()):
        severity = 'notice' if key in listed else 'error'
        scope = key.split('::', 1)[1]
        findings.append(
            f'::{severity} file={_rel(py_file)},line={line},'
            f'title=Architecture: service imports the core_api facade::{scope} '
            f'imports {what}. The facade is for modules; a service going '
            f'through it loops back (services → core_api → services) and hides '
            f'the dependency between two services behind a middleman — import '
            f'the service it calls directly, inside the function when the '
            f'import cycle demands it.'
        )
    for key in sorted(listed - set(found)):
        findings.append(
            f'::error file=app/core/services_public_api_import_baseline.txt,'
            f'title=Architecture: paid facade debt still listed::{key} no '
            f'longer imports the core_api facade (or no longer exists). '
            f'Delete the entry and run --write-baseline-sizes.'
        )
    return findings
