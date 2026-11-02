#!/usr/bin/env python3
"""Generate the refusal-code table of docs/api/ERRORS.md from the catalogue.

A business refusal is raised as ``ServiceRejectionError('<key>')`` (or built
as ``catalogue_refusal('<key>')`` where it must not be a ``ValueError``, and as
``catalogue_status_refusal('<key>', <status>)`` at a status other than 400) and answers
with the upper-cased key in ``detail.code``. The keys a client can meet are
therefore the first arguments of those raises — a literal, or the literals a
key chosen at run time is picked from — and their English
sentences are the catalogue's (``app.i18n``) — one source for both, so the
page cannot drift from what the API answers.

A ``CodedRejectionError`` (the focus-mode and profile-switch refusals) is the
exception: it keeps the lowercase machine code it was raised with
(``code='unknown_module'``), and that — not the upper-cased key — is what the
page lists for it.

The table sits between two markers in ``ERRORS.md``; everything around it is
hand-written. The script prints the whole page with the table refreshed.

Usage:
    docker compose exec -T backend python scripts/generate_error_codes.py > /tmp/ERRORS.md \
        && mv /tmp/ERRORS.md docs/api/ERRORS.md
    docker compose exec -T backend python scripts/generate_error_codes.py --check
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
# In the backend container the checkout is mounted read-only and named here.
_PROJECT_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT') or _BACKEND_DIR.parent)
DEFAULT_OUTPUT = _PROJECT_ROOT / 'docs' / 'api' / 'ERRORS.md'
BEGIN = '<!-- BEGIN GENERATED REFUSAL CODES (scripts/generate_error_codes.py) -->'
END = '<!-- END GENERATED REFUSAL CODES -->'


#: A refusal of this class (or a subclass) is raised as ``Error('<key>',
#: code='<wire code>')`` and answers that code instead of the upper-cased key.
_CODED_BUILDER = 'CodedRejectionError'

#: A refusal answers with its first argument as the code: these build one.
_REFUSAL_BUILDERS = {
    'ServiceRejectionError',
    'catalogue_refusal',
    'catalogue_status_refusal',
}


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _assignments(stmt: ast.AST):
    if isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                yield target.id, stmt.value
    elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
        if isinstance(stmt.target, ast.Name):
            yield stmt.target.id, stmt.value


def _parameters(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = fn.args
    return [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]


class _Source:
    """One parsed file: its module-level bindings, imports and each node's function."""

    def __init__(self, path: Path, tree: ast.Module) -> None:
        self.path = path
        self.tree = tree
        self.module_values: dict[str, list[ast.expr]] = {}
        for stmt in tree.body:
            for name, value in _assignments(stmt):
                self.module_values.setdefault(name, []).append(value)
        #: name -> last part of the module it is imported from
        self.imported = {
            alias.asname or alias.name: (node.module or '').rsplit('.', 1)[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.function_of: dict[ast.AST, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.class_of: dict[ast.AST, ast.ClassDef] = {}
        for node in ast.walk(tree):  # outer first, so the innermost wins
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for inner in ast.walk(node):
                    self.function_of[inner] = node
            elif isinstance(node, ast.ClassDef):
                for inner in ast.walk(node):
                    self.class_of[inner] = node


class _Keys:
    """Follow a refusal's first argument to the string literals it can hold.

    A key chosen at run time is still written somewhere as a literal: in the
    branches of a conditional, the values of a table of refusals, a local
    assignment, or the default of a parameter and the arguments its callers
    pass. Anything else is a key this script cannot name, and it says where.
    """

    def __init__(self, sources: list[_Source]) -> None:
        self.sources = sources
        self.unresolved: list[str] = []
        self.defined_in: dict[str, list[_Source]] = {}
        bases: dict[str, set[str]] = {}
        for source in sources:
            for node in ast.walk(source.tree):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    self.defined_in.setdefault(node.name, []).append(source)
                if isinstance(node, ast.ClassDef):
                    # By name: two modules may each define an ``ApprovalError``.
                    bases.setdefault(node.name, set()).update(
                        b.id for b in node.bases if isinstance(b, ast.Name)
                    )
        self.builders = set(_REFUSAL_BUILDERS)
        while (
            grown := {c for c, b in bases.items() if b & self.builders} - self.builders
        ):
            self.builders |= grown
        #: ``CodedRejectionError`` and its subclasses answer ``code=``, not the key.
        self.coded = {_CODED_BUILDER}
        while grown := {c for c, b in bases.items() if b & self.coded} - self.coded:
            self.coded |= grown

    def sites(self, source: _Source):
        """The calls of *source* whose first argument is a refusal's key.

        A subclass of ``ServiceRejectionError`` with its own ``__init__``
        takes other arguments; its key is what that ``__init__`` hands to
        ``super().__init__``. A caught refusal passed on by its ``.key`` was
        counted where it was raised.
        """
        for node in ast.walk(source.tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Attribute) and first.attr == 'key':
                continue
            name = _called_name(node)
            if isinstance(node.func, ast.Name) and name in self.builders:
                if name in _REFUSAL_BUILDERS or not self._has_own_init(name):
                    yield node
            elif (
                name == 'translated'
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in self.builders
            ):
                yield node  # ``ApprovalError.translated('<key>')``
            elif (
                name == '__init__'
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Call)
                and _called_name(node.func.value) == 'super'
                and (cls := source.class_of.get(node)) is not None
                and cls.name in self.builders - _REFUSAL_BUILDERS
            ):
                yield node

    def wire_codes(self, source: _Source, call: ast.Call) -> set[str | None]:
        """What the refusal built by *call* answers in ``detail.code``.

        ``None`` is the upper-cased key; a coded refusal answers the literals
        its ``code=`` argument can hold.
        """
        if _called_name(call) not in self.coded:
            return {None}
        passed = [k.value for k in call.keywords if k.arg == 'code']
        if not passed:
            self.unresolved.append(f'{source.path}:{call.lineno}')
            return set()
        return set(self.of(source, passed[0]))

    def _has_own_init(self, cls_name: str) -> bool:
        for source in self.defined_in.get(cls_name, []):
            for node in ast.walk(source.tree):
                if isinstance(node, ast.ClassDef) and node.name == cls_name:
                    return any(
                        isinstance(f, ast.FunctionDef) and f.name == '__init__'
                        for f in node.body
                    )
        return False

    def of(
        self, source: _Source, node: ast.expr, seen: frozenset = frozenset()
    ) -> set[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.IfExp):
            return self.of(source, node.body, seen) | self.of(source, node.orelse, seen)
        if isinstance(node, ast.Dict):
            return set().union(*(self.of(source, v, seen) for v in node.values))
        if isinstance(node, ast.Subscript):
            return self.of(source, node.value, seen)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'get'
        ):
            return self.of(source, node.func.value, seen)
        if isinstance(node, ast.Name) and (source.path, node.id) not in seen:
            return self._name(source, node, seen | {(source.path, node.id)})
        self.unresolved.append(f'{source.path}:{node.lineno}')
        return set()

    def _name(self, source: _Source, node: ast.Name, seen: frozenset) -> set[str]:
        fn = source.function_of.get(node)
        if fn is not None:
            local = [
                value
                for stmt in ast.walk(fn)
                for name, value in _assignments(stmt)
                if name == node.id
            ]
            if local:
                return set().union(*(self.of(source, v, seen) for v in local))
            if node.id in _parameters(fn):
                return self._parameter(source, fn, node.id, seen)
        if node.id in source.module_values:
            values = source.module_values[node.id]
            return set().union(*(self.of(source, v, seen) for v in values))
        self.unresolved.append(f'{source.path}:{node.lineno}')
        return set()

    def _parameter(self, source: _Source, fn, name: str, seen: frozenset) -> set[str]:
        args = fn.args
        positional = [a.arg for a in (*args.posonlyargs, *args.args)]
        defaults = dict(
            zip(
                positional[len(positional) - len(args.defaults) :],
                args.defaults,
                strict=True,
            )
        )
        defaults.update(
            {
                a.arg: d
                for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True)
                if d is not None
            }
        )
        keys = self.of(source, defaults[name], seen) if name in defaults else set()
        followed = name in defaults
        index = positional.index(name) if name in positional else None
        if index is not None and positional[:1] in (['self'], ['cls']):
            index -= 1
        callee = fn.name
        if callee == '__init__' and (cls := source.class_of.get(fn)) is not None:
            callee = cls.name
        for caller, call in self._callers(source, callee):
            passed = [k.value for k in call.keywords if k.arg == name]
            if not passed and index is not None and index < len(call.args):
                passed = [call.args[index]]
            for value in passed:
                followed = True
                keys |= self.of(caller, value, seen)
        if not followed:
            # No default and no call that passes it: the key comes from
            # somewhere this reader cannot see, so it stops rather than guess.
            self.unresolved.append(f'{source.path}:{fn.lineno}')
        return keys

    def _callers(self, home: _Source, name: str):
        """Calls of the function *name* defined in *home*.

        By name in its own file and in files that import it from there; by
        attribute (``svc.name(...)``) anywhere, but only when no other file
        defines a function of that name to confuse it with.
        """
        unique = len(self.defined_in.get(name, [])) == 1
        for source in self.sources:
            by_name = source is home or source.imported.get(name) == home.path.stem
            for node in ast.walk(source.tree):
                if not isinstance(node, ast.Call) or _called_name(node) != name:
                    continue
                if isinstance(node.func, ast.Name) and by_name:
                    yield source, node
                elif isinstance(node.func, ast.Attribute) and unique:
                    yield source, node


def raised_refusals(app_root: Path) -> set[tuple[str, str | None]]:
    """``(catalogue key, wire code)`` of every refusal the backend raises.

    The wire code is ``None`` where it is the upper-cased key — a refusal of
    ``CodedRejectionError`` answers the lowercase code it was raised with.
    Exits naming the raises whose key or code it cannot follow to a literal.
    """
    sources = []
    for path in sorted(app_root.rglob('*.py')):
        if 'tests' in path.relative_to(app_root).parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        sources.append(_Source(path.relative_to(app_root.parent), tree))
    follow = _Keys(sources)
    refusals: set[tuple[str, str | None]] = set()
    for source in sources:
        for call in follow.sites(source):
            codes = follow.wire_codes(source, call)
            for key in follow.of(source, call.args[0]):
                refusals |= {(key, code) for code in codes}
    if follow.unresolved:
        raise SystemExit(
            'Cannot tell which catalogue key these refusals raise — name it with a '
            'literal, a conditional of literals or a table of them:\n  '
            + '\n  '.join(sorted(set(follow.unresolved)))
        )
    return refusals


def build_block() -> str:
    from app.core.exceptions import rejection_code
    from app.i18n.service import get_error_message

    wire = sorted(
        (code or rejection_code(key), key)
        for key, code in raised_refusals(_BACKEND_DIR / 'app')
    )
    rows = []
    for code, key in wire:
        sentence = get_error_message(key, 'en').replace('|', '\\|')
        rows.append(f'| `{code}` | {sentence} |')
    return '\n'.join(
        [
            BEGIN,
            '| Code | English message |',
            '|---|---|',
            *rows,
            END,
        ]
    )


def replace_block(page: str, block: str) -> str:
    start = page.index(BEGIN)
    stop = page.index(END) + len(END)
    return page[:start] + block + page[stop:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--check',
        action='store_true',
        help='Exit 1 when the committed page differs from the generated one.',
    )
    args = parser.parse_args()

    page = DEFAULT_OUTPUT.read_text(encoding='utf-8')
    fresh = replace_block(page, build_block())
    if args.check:
        if fresh != page:
            print(f'CHECK FAILED: {DEFAULT_OUTPUT} is out of sync — regenerate it.')
            return 1
        print('CHECK OK: refusal codes are in sync.')
        return 0
    sys.stdout.write(fresh)
    return 0


if __name__ == '__main__':
    sys.exit(main())
