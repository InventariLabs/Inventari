"""Sync/async function twin check (Guardrail 1).

A twin is when the same module defines both ``foo()`` and ``foo_async()``
(or ``foo_sync()``). The sync variant should be deleted — async-only is
the project rule (AGENTS.md §Sync/Async).

A pair split across two files counts only when one half drives the other:
the async door offloads the sync implementation through ``run_sync`` /
``run_sync_in_thread`` and imports it from the module that defines it.
Names that merely rhyme — a bare name used outside an offload, an
unimported name, two halves that never meet — are not a pair, and
blocking on them would make this gate read vocabulary instead of calls.

Baselined twins emit ``::notice`` so they stay visible without blocking.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ._constants import _is_test_file, _rel, _rel_parts
from ._run_cache import once_per_run

_OFFLOAD_CALLS = frozenset({'run_sync', 'run_sync_in_thread'})


@dataclass(frozen=True)
class _FileFacts:
    """What the twin rules ask of one file.

    ``kinds`` is every function it defines and ``offloads`` maps a
    function to the ``(published name, source module)`` pairs it hands to
    ``run_sync`` / ``run_sync_in_thread``. A pair carries the binding, not
    just the name: the published name is what the defining module calls
    the function, so the search never depends on which spelling the call
    site chose, and the source keeps apart two modules that publish the
    same name — ``from a import get_x_sync as ax`` beside ``from b import
    get_x_sync as bx`` is two bindings, and an offload of one is no
    evidence about the other. ``offloads`` is per file on purpose: it
    answers "does this file know *that* function", which is what separates
    a pair from a coincidence.
    """

    rel: Path
    module: str
    kinds: dict[str, str]
    offloads: dict[str, set[tuple[str, str]]]


@dataclass(frozen=True)
class _TreeIndex:
    defs: dict[str, dict[str, set[Path]]]
    files: dict[Path, _FileFacts]


@once_per_run
def _collect_defs(app_root: Path) -> _TreeIndex:
    """Every function definition in the tree, plus what each file knows.

    ``defs`` maps a name to its kinds and the files holding them; ``files``
    carries each file's module and the per-file facts. The rules below ask
    questions across files (does this file define the base? did this
    function import and offload the sibling?), and a flat name list cannot
    answer those.
    """
    defs: dict[str, dict[str, set[Path]]] = {}
    files: dict[Path, _FileFacts] = {}
    for py_file in sorted(app_root.rglob('*.py')):
        if _is_test_file(py_file, app_root) or '__pycache__' in _rel_parts(
            py_file, app_root
        ):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, OSError):
            continue
        facts = _file_facts(py_file, tree, app_root)
        files[facts.rel] = facts
        for name, kind in facts.kinds.items():
            defs.setdefault(name, {}).setdefault(kind, set()).add(facts.rel)
    return _TreeIndex(defs=defs, files=files)


def _file_facts(py_file: Path, tree: ast.AST, app_root: Path) -> _FileFacts:
    parts = _rel_parts(py_file, app_root)
    package = parts[:-1]
    module = '.'.join(
        package if parts[-1] == '__init__.py' else (*package, py_file.stem)
    )
    bindings = _import_bindings(tree, package)
    kinds: dict[str, str] = {}
    offloads: dict[str, set[tuple[str, str]]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kinds[node.name] = (
                'async' if isinstance(node, ast.AsyncFunctionDef) else 'sync'
            )
            offloads[node.name] = {
                binding
                for name in _offloaded_names(node)
                for binding in bindings.get(name, ())
            }
    return _FileFacts(
        rel=_rel(py_file),
        module=module,
        kinds=kinds,
        offloads=offloads,
    )


def _import_bindings(
    scope: ast.AST, package: tuple[str, ...]
) -> dict[str, set[tuple[str, str]]]:
    """What a file imports from other modules, under which local spelling.

    ``bindings`` maps a local spelling to the ``(published name, source
    module)`` pairs a ``from`` import bound it to — keyed by the spelling
    the file uses at the call site, because that is what an offload writes,
    and carrying the source with the name so two modules publishing the
    same function stay two bindings. ``from x import get_y`` binds
    ``get_y`` to ``('get_y', 'x')``; ``... import get_y as gy`` binds
    ``gy`` to the same pair.

    Only ``from`` imports bind a function name; ``import a.b`` binds ``a``,
    which cannot be the bare name of a sibling.
    """
    bindings: dict[str, set[tuple[str, str]]] = {}
    for node in ast.walk(scope):
        if not isinstance(node, ast.ImportFrom):
            continue
        source = _resolve_import(node, package)
        if source is None:
            continue
        for alias in node.names:
            if alias.name == '*':
                continue
            bindings.setdefault(alias.asname or alias.name, set()).add(
                (alias.name, source)
            )
    return bindings


def _resolve_import(node: ast.ImportFrom, package: tuple[str, ...]) -> str | None:
    """The dotted module a ``from`` import reads, relative imports included.

    ``from app.services.x import foo`` and, inside ``app/services``,
    ``from .x import foo`` are the same import — the ``app.`` prefix is the
    directory the tree is rooted at, not part of any name below it. A bare
    ``from . import foo`` names a submodule or a re-export and nothing else,
    so it resolves to no module at all.
    """
    if not node.module:
        return None
    parts = tuple(node.module.split('.'))
    if not node.level:
        return '.'.join(parts[1:] if parts[:1] == ('app',) else parts)
    base = package[: len(package) - (node.level - 1)]
    return '.'.join((*base, *parts))


def _is_offload(func: ast.AST) -> bool:
    """``run_sync`` / ``run_sync_in_thread``, called bare or as a method."""
    if isinstance(func, ast.Name):
        return func.id in _OFFLOAD_CALLS
    return isinstance(func, ast.Attribute) and func.attr in _OFFLOAD_CALLS


def _offloaded_names(scope: ast.AST) -> set[str]:
    """The names this function hands to an offload call.

    ``db.run_sync(get_x_sync)`` and ``run_sync_in_thread(lambda:
    _render_pdf_sync(html))`` are the two spellings in the corpus; a name
    sitting anywhere inside the argument counts, because the lambda *is*
    the offload.
    """
    names: set[str] = set()
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call) or not _is_offload(node.func):
            continue
        arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
        for argument in arguments:
            names.update(
                child.id
                for child in ast.walk(argument)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
            )
    return names


def _defines_sync(index: _TreeIndex, facts: _FileFacts, name: str) -> bool:
    return facts.rel in index.defs.get(name, {}).get('sync', set())


def _drives(
    index: _TreeIndex, facts: _FileFacts, door: str, target: str
) -> Path | None:
    """The file whose sync ``target`` this door offloads, if any.

    The offload call is half the evidence and the binding is the other
    half: ``db.run_sync(get_x_sync)`` names *some* ``get_x_sync``, and only
    the binding says it is the one defined over there rather than a local,
    a parameter, or another module's function with the same spelling. The
    binding keeps its source, so an alias of one module's ``get_x_sync``
    cannot stand for another's.
    """
    drives = facts.offloads.get(door, set())
    for rel in index.defs.get(target, {}).get('sync', set()):
        if (target, index.files[rel].module) in drives:
            return rel
    return None


def _driven_elsewhere(
    index: _TreeIndex, facts: _FileFacts, target: str, door: str
) -> bool:
    """Does an async ``door`` in another file offload this file's ``target``?"""
    for rel in index.defs.get(door, {}).get('async', set()):
        if _drives(index, index.files[rel], door, target) == facts.rel:
            return True
    return False


def _twin_sibling(
    index: _TreeIndex, n: str, base: str, facts: _FileFacts
) -> str | None:
    """The other half of this twin, if ``n`` has one.

    Three shapes say yes: the base is a plain ``def`` in the same file; the
    async door offloads a sync half it imported from the file defining it;
    or ``n`` is the sync half of a ``_sync``/``_async`` pair whose base was
    never written, and the async half sits beside it or drives it. An async
    base is a naming alias, not a twin.
    """
    if _defines_sync(index, facts, base):
        return base
    if not n.endswith('_sync'):
        # `n` is the door. It drives the base, or — with no base written —
        # its own _sync sibling, which is how the split timeline pair is
        # spelled. `n` itself is a definition, never its own sibling.
        for target in (base, base + '_sync'):
            if target != n and _drives(index, facts, n, target):
                return target
        return None
    # `n` is the sync half: the async sibling sits in this file...
    if base + '_async' in facts.kinds:
        return base + '_async'
    # ...or drives it from its own.
    if _driven_elsewhere(index, facts, n, base + '_async'):
        return base + '_async'
    return None


def _base_of(n: str) -> str | None:
    for suffix in ('_async', '_sync'):
        if n.endswith(suffix) and len(n) > len(suffix):
            return n[: -len(suffix)]
    return None


def _check_sync_async_function_twins(
    app_root: Path, baseline: set[str] | None = None
) -> list[str]:
    """Emit ``::error`` for function-level sync/async twins.

    Three shapes are twins: ``foo`` and ``foo_async`` (or ``foo_sync``) in
    one file — the original rule; the pair split across files, where the
    async door offloads the sync implementation it imported from the file
    defining it (``get_activity_timeline_async`` wrapping
    ``get_activity_timeline_sync``); and ``foo_sync``/``foo_async`` with no
    ``foo`` written anywhere, related the same way. A shared name that
    never reaches an offload, or reaches one without the import, is a
    coincidence — coincidence is not a call, and it is not a finding.

    The base must be a plain ``def`` — an async base makes the pair a
    naming alias (one name delegating to the ``_async`` spelling), not a
    twin, so it is nobody's finding.

    Baselined twins emit ``::notice`` so they stay visible without blocking.
    """
    baseline = baseline or set()
    errors: list[str] = []
    for rel, n, sibling in _iter_function_twins(app_root):
        severity = 'notice' if f'{rel}::{n}' in baseline else 'error'
        errors.append(
            f'::{severity} file={rel},title=Architecture: sync/async twin::'
            f'{n}() is a twin of {sibling}(). Delete the sync variant or '
            f'merge into a single async function.'
        )
    return errors


def _iter_function_twins(app_root: Path) -> Iterator[tuple[Path, str, str]]:
    """``(file, name, sibling)`` for every function that has a twin."""
    index = _collect_defs(app_root)
    for n in sorted(index.defs):
        base = _base_of(n)
        if base is None:
            continue
        for rel, facts in index.files.items():
            if n not in facts.kinds:
                continue
            sibling = _twin_sibling(index, n, base, facts)
            if sibling is not None:
                yield rel, n, sibling


def collect_twin_keys(app_root: Path) -> set[str]:
    """Baseline keys (``file::name``) for every current twin."""
    return {f'{rel}::{n}' for rel, n, _ in _iter_function_twins(app_root)}
