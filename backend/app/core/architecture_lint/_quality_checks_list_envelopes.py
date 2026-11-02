"""Guardrail: every list endpoint answers with a documented pagination envelope.

``docs/subsystems/PAGINATION.md`` names three envelopes —
``PaginatedResponse``, ``KeysetPaginatedResponse``, ``CursorPaginatedResponse``
— and ``app.schemas.pagination`` holds them. A route declares
``response_model=list[...]`` instead and FastAPI publishes the list as a bare
JSON array: a client cannot page it, and its screen falls over before the
organization reaches a few thousand rows. Wrapping it later changes the
response type, which is why every list moved in one release.

A route answers with an envelope or carries
``# list-envelope-exception: <reason>`` in its registration — a list that is
not a collection of rows (a bulk result, a fixed vocabulary) says why here,
next to the route, where the next reader finds it.

A list reaches the client three ways, and the scan reads all of them:
``response_model=list[X]``, an optional list (``list[X] | None``,
``Optional[list[X]]``), and a decorated handler annotated ``-> list[X]`` with
no ``response_model``, from which FastAPI infers the model.

The scan is AST-based: a ``response_model=list[...]`` named in a docstring is
prose, not a finding.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ._constants import _is_test_file, _rel_parts
from ._quality_checks_transaction_ownership import _enclosing_qualname

EXCEPTION_MARKER = 'list-envelope-exception:'
_EXCEPTION_MIN_REASON_WORDS = 3

_ROUTE_METHODS = frozenset({'get', 'post', 'put', 'patch', 'delete', 'head', 'options'})
_ROUTE_REGISTRARS = frozenset({'add_api_route', 'add_route'})


@dataclass(frozen=True)
class BareListRoute:
    """One route registration whose ``response_model`` is a bare list.

    ``ordinal`` is the 1-based position of this registration among the
    registrations of the same function, so a second bare list added next to a
    baselined one is a new, uncovered site rather than a free rider.
    """

    rel_path: str
    qualname: str
    ordinal: int
    lineno: int

    @property
    def key(self) -> str:
        return f'{self.rel_path}::{self.qualname}@{self.ordinal}'


def _is_route_registration(node: ast.Call) -> bool:
    """Is this call a ``@router.get(...)`` style registration or ``add_api_route``?"""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    return func.attr in _ROUTE_METHODS or func.attr in _ROUTE_REGISTRARS


def _is_bare_list_annotation(node: ast.expr | None) -> bool:
    """Is *node* a list — ``list[...]``, ``list``, ``List[...]`` or an optional one?

    ``list[X] | None``, ``Optional[list[X]]`` and ``Union[list[X], None]``
    publish the same array (or ``null``) a plain list does, so an optional
    wrapper does not hide it.
    """
    if isinstance(node, ast.Name):
        return node.id in {'list', 'List'}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_bare_list_annotation(node.left) or _is_bare_list_annotation(
            node.right
        )
    if isinstance(node, ast.Subscript):
        value = node.value
        name = value.id if isinstance(value, ast.Name) else None
        if name is None and isinstance(value, ast.Attribute):
            name = value.attr
        if name in {'list', 'List'}:
            return True
        if name in {'Optional', 'Union'}:
            members = (
                node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            )
            return any(_is_bare_list_annotation(member) for member in members)
    return False


def _response_model_keyword(node: ast.Call) -> ast.keyword | None:
    for keyword in node.keywords:
        if keyword.arg == 'response_model':
            return keyword
    return None


def _exception_reason(source_lines: list[str], node: ast.Call) -> str | None:
    """The reason written in the registration, or ``None`` when there is none."""
    start = node.lineno - 1
    end = getattr(node, 'end_lineno', node.lineno)
    for line in source_lines[start:end]:
        column = line.find(EXCEPTION_MARKER)
        if column < 0:
            continue
        return line[column + len(EXCEPTION_MARKER) :].strip()
    return None


def _decorated_functions(
    tree: ast.AST,
) -> dict[int, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Map each decorator expression to the function it decorates.

    A route registered with a decorator and no ``response_model`` takes its
    model from the function's return annotation, so the check reads it there.
    """
    functions: dict[int, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                functions[id(decorator)] = node
    return functions


def _decorator_owners(tree: ast.AST) -> dict[int, str]:
    """Map each decorator expression to the function or class it decorates.

    ``_enclosing_qualname`` answers by line range, and a decorator sits above
    its function's ``def`` line — outside that range. Without this map every
    decorated route is keyed ``<module>@N``, which tells the next reader
    nothing about which endpoint moved.
    """
    owners: dict[int, str] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                name = f'{prefix}{child.name}'
                for decorator in child.decorator_list:
                    owners[id(decorator)] = name
                visit(child, f'{name}.')
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f'{prefix}{child.name}'
                for decorator in child.decorator_list:
                    owners[id(decorator)] = name
                visit(child, f'{name}.')
            else:
                visit(child, prefix)

    visit(tree, '')
    return owners


def collect_bare_list_routes(roots: list[Path]) -> list[BareListRoute]:
    """Every bare-list route registration under *roots*, tests excluded.

    A registration that carries ``# list-envelope-exception: <reason>`` with a
    sentence after the marker is not a finding; the marker with no reason is,
    because an exception nobody explained is a suppression.
    """
    routes: list[BareListRoute] = []
    for root in roots:
        if not root.is_dir():
            continue
        for py_file in sorted(root.rglob('*.py')):
            rel = _rel_parts(py_file, root)
            if _is_test_file(py_file, root) or '__pycache__' in rel:
                continue
            try:
                source = py_file.read_text(encoding='utf-8')
                tree = ast.parse(source)
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            source_lines = source.splitlines()
            owners = _decorator_owners(tree)
            decorated = _decorated_functions(tree)
            candidates: list[ast.Call] = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not _is_route_registration(node):
                    continue
                response_model = _response_model_keyword(node)
                published: ast.expr | None
                if response_model is not None:
                    published = response_model.value
                else:
                    # FastAPI infers the model from the return annotation.
                    function = decorated.get(id(node))
                    published = function.returns if function else None
                if not _is_bare_list_annotation(published):
                    continue
                reason = _exception_reason(source_lines, node)
                if (
                    reason is not None
                    and len(reason.split()) >= _EXCEPTION_MIN_REASON_WORDS
                ):
                    continue
                candidates.append(node)
            candidates.sort(key=lambda call: (call.lineno, call.col_offset))
            ordinals: dict[str, int] = {}
            for call in candidates:
                qualname = owners.get(id(call)) or _enclosing_qualname(
                    tree, call.lineno
                )
                ordinals[qualname] = ordinals.get(qualname, 0) + 1
                routes.append(
                    BareListRoute(
                        rel_path='/'.join(rel),
                        qualname=qualname,
                        ordinal=ordinals[qualname],
                        lineno=call.lineno,
                    )
                )
    return routes


def _check_list_envelopes(roots: list[Path]) -> list[str]:
    """Emit an ``::error`` per route whose ``response_model`` is a list.

    Args:
        roots: the directories to scan (``app/api`` and ``app/modules``).

    Returns:
        list[str]: GitHub-PR-formatted annotations.
    """
    entries: list[str] = []
    for route in collect_bare_list_routes(roots):
        entries.append(
            f'::error '
            f'{route.rel_path}:{route.lineno}: {route.qualname} answers '
            f'with a bare list (response_model=list[...] or a list return '
            f'annotation) — a list endpoint answers with a '
            f'documented envelope (PaginatedResponse.from_full_list, or a '
            f'keyset/cursor page for a list that grows); see '
            f'docs/subsystems/PAGINATION.md. A list that is not a collection '
            f'of rows carries a "# list-envelope-exception: <reason>" comment '
            f'in its registration.'
        )
    return entries
