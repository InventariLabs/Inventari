"""The single AST safety scanner shared by the runtime loader and the CLI.

Two copies of this scan used to exist — ``app.core.module_validator`` for module
discovery and ``app.cli.module_validator`` for ``manage.py module validate`` and
the packaging pipeline. They were written from the same design but drifted, and
the drift was not cosmetic: the fix that made symbol-level bans actually fire
landed only in the runtime copy, so ``from app.core.events import event_bus``
was rejected when a module loaded yet passed the CLI gate that runs *before*
installation. The stricter check sat behind the weaker one.

Rather than patch the copy, both callers now share this scanner. What stayed
per-caller is only the wording: the registry reports violations relative to the
module, the CLI prefixes each line with the module name for output that lists
many modules at once. Findings are returned structured so each side can format
them without the logic being duplicated again.

Paths are not the only ban. An object in ``FORBIDDEN_OBJECTS`` (the raw event
bus) is reachable through every app module that imports it for its own use, so
besides matching import paths the scan records each ``app.`` name a module
reaches — ``from X import a``, an attribute on an imported module, a relative
import that climbs out of ``app/modules/`` — and resolves it against the
running code, refusing whatever turns out to *be* a banned object.

The edge of that rule: the scan refuses a banned object reached by import,
attribute, literal ``getattr``, or by an app module handed over as a value
(``vars(m)``, ``m.__dict__``, ``globals()``, a list holding it), which counts
as reading every name the module holds — so a harmless-looking ``hasattr(m, x)``
or ``print(m)`` on such a module is refused too. It does not claim to stop
reflection through non-module objects (a function's ``__globals__``,
``inspect.getmodule``, ``gc``, ``sys.modules``): that is beyond a static scan,
and per ADR-019 there is no runtime guard — certification is the protection.

Note on the failure mode: parsing an unexpected file raises broadly here and is
reported as a finding rather than propagated. The CLI copy previously caught
only ``OSError``/``SyntaxError``, so an oddity like a bad encoding aborted the
whole validation run instead of failing that one module. A safety gate that
crashes is a gate that gets skipped.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import tempfile
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Literal

from app.core.logging import get_logger
from app.core.module_safety import (
    CAPABILITY_MAP,
    CORE_EXEMPTIONS,
    FORBIDDEN_CALLS,
    FORBIDDEN_IMPORT_PREFIXES,
    FORBIDDEN_OBJECTS,
    MODULE_IMPORT_SURFACE,
    REPO_SHIPPED_MODULES,
    SHIPPED_ONLY_OBJECTS,
    TRUSTED_SHIPPED_MODULES,
)

logger = get_logger(__name__)

#: Bump when the scan's rules change, so cached verdicts from the old rules
#: are not served. Derived from the policy constants themselves, so editing
#: FORBIDDEN_IMPORT_PREFIXES or the capability map invalidates entries without
#: anyone having to remember to.
_POLICY_VERSION = repr(
    (
        sorted(FORBIDDEN_IMPORT_PREFIXES),
        sorted(FORBIDDEN_CALLS),
        sorted((k, sorted(v)) for k, v in CAPABILITY_MAP.items()),
        sorted((k, sorted(v)) for k, v in CORE_EXEMPTIONS.items()),
        sorted(TRUSTED_SHIPPED_MODULES),
        sorted(MODULE_IMPORT_SURFACE),
    )
)

FindingKind = Literal[
    'parse_error',
    'forbidden_import',
    'off_surface_import',
    'undeclared_capability',
    'forbidden_call',
]


@dataclass(frozen=True)
class SafetyFinding:
    """One problem found in one file.

    ``subject`` is whatever the finding is about — the import path, the called
    name, or the parser's own message. ``capability`` is set only for
    ``undeclared_capability``. ``hint`` carries the way out when there is one
    (``off_surface_import`` names the SDK), so both reporters say the same
    sentence without each inventing it.
    """

    kind: FindingKind
    rel_path: Path
    subject: str
    lineno: int | None = None
    capability: str | None = None
    hint: str | None = None


@dataclass(frozen=True)
class _AppReference:
    """A dotted ``app.`` name one statement reaches, through the file's imports.

    Kept apart from the findings because what it names is decided by the code
    outside the module: the cache stores the reference, and whether it is a
    banned object is answered fresh on every scan.
    """

    path: str
    rel_path: Path
    lineno: int


def _is_test_file(file_path: Path, module_dir: Path) -> bool:
    """A test is a path INSIDE the module that runs through tests/.

    Matched relative to the module root on purpose: matching absolute
    parts made any checkout under a directory named ``tests`` turn the
    whole scan off — a clean report over a tree nobody read.
    """
    return 'tests' in file_path.relative_to(module_dir).parts


def _absolute_base(node: ast.ImportFrom, package: tuple[str, ...]) -> str:
    """The dotted module a ``from`` import names, resolved from its dots.

    ``from ...models.item import Item`` in ``app.modules.x`` is
    ``app.models.item``; matching the relative remainder instead let a module
    walk past every path ban by writing dots.
    """
    if not node.level:
        return node.module or ''
    keep = max(len(package) - (node.level - 1), 0)
    return '.'.join((*package[:keep], *([node.module] if node.module else [])))


def _imported_names(
    node: ast.Import | ast.ImportFrom, package: tuple[str, ...] = ()
) -> list[str]:
    """Every dotted name an import statement brings into scope.

    For ``from X import a, b`` that is ``X`` plus any ``X.a`` that a ban names
    directly — a ban may target a symbol rather than a module, and the symbol
    lives in the alias, not in ``node.module``.

    Symbol-level names are added only when the module itself is not already
    banned. The exemption lists match names exactly, so emitting
    ``app.models.item.Item`` alongside ``app.models.item`` would slip past an
    exemption written for the module and revoke it.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]

    base = _absolute_base(node, package)
    names = [base]
    if base and not _is_forbidden(base):
        names += [
            f'{base}.{alias.name}'
            for alias in node.names
            if _is_forbidden(f'{base}.{alias.name}')
        ]
    return names


def _is_forbidden(name: str) -> bool:
    """Whether *name* is a ``FORBIDDEN_IMPORT_PREFIXES`` entry or inside one.

    Bounded by the dot, as the capability map is (``_names_module``): a bare
    prefix match refused ``socketserver`` as ``socket`` and
    ``subprocess_tee`` as ``subprocess``.
    """
    return any(_names_module(name, banned) for banned in FORBIDDEN_IMPORT_PREFIXES)


def _absolute_module(node: ast.ImportFrom, rel_path: Path) -> str | None:
    """The absolute name a ``from`` import reads, relative ones included.

    A module lives at ``app.modules.<name>``, so three dots from its root
    are ``app`` itself — a road the path ban, which reads ``node.module``
    as written, never saw.
    """
    if not node.level:
        return node.module
    package = ['app', 'modules', *rel_path.parent.parts]
    if node.level > len(package):
        return None
    base = package[: len(package) - node.level + 1]
    return '.'.join([*base, node.module] if node.module else base)


def _value_leaves(value: ast.expr) -> list[ast.expr]:
    """The expressions a conditional or walrus value may evaluate to."""
    if isinstance(value, ast.IfExp):
        return _value_leaves(value.body) + _value_leaves(value.orelse)
    if isinstance(value, ast.BoolOp):
        return [leaf for v in value.values for leaf in _value_leaves(v)]
    if isinstance(value, ast.NamedExpr):
        return _value_leaves(value.value)
    return [value]


def _target_pairs(target: ast.expr, value: ast.expr) -> list[tuple[str, ast.expr]]:
    """``(name, value)`` for a store target. Attribute stores key as ``.attr``."""
    if isinstance(target, ast.Name):
        return [(target.id, value)]
    if isinstance(target, ast.Attribute):
        return [(f'.{target.attr}', value)]
    if not (
        isinstance(target, ast.Tuple | ast.List)
        and isinstance(value, ast.Tuple | ast.List)
    ):
        return []
    targets, values = list(target.elts), list(value.elts)
    star = next((i for i, t in enumerate(targets) if isinstance(t, ast.Starred)), None)
    if star is None:
        if len(targets) != len(values) or any(
            isinstance(v, ast.Starred) for v in values
        ):
            return []
        return [
            pair
            for t, v in zip(targets, values, strict=True)
            for pair in _target_pairs(t, v)
        ]
    # ``a, *rest, z = ...``: the elements outside the star pair up by position
    # from each end; the star name may hold any of those in between.
    before, after = targets[:star], targets[star + 1 :]
    pairs: list[tuple[str, ast.expr]] = []
    for t, v in zip(before, values, strict=False):
        if isinstance(v, ast.Starred):
            break
        pairs += _target_pairs(t, v)
    for t, v in zip(reversed(after), reversed(values), strict=False):
        if isinstance(v, ast.Starred):
            break
        pairs += _target_pairs(t, v)
    rest = targets[star]
    if isinstance(rest, ast.Starred):
        for v in values[len(before) : len(values) - len(after)]:
            pairs += _target_pairs(
                rest.value, v.value if isinstance(v, ast.Starred) else v
            )
    return pairs


def _class_pairs(node: ast.ClassDef) -> list[tuple[str, ast.expr]]:
    """``class H: e = events`` binds ``H.e``, which ``H.e.x`` reads back."""
    return [
        (f'{node.name}.{name}', value)
        for stmt in node.body
        if isinstance(stmt, ast.Assign | ast.AnnAssign) and stmt.value is not None
        for target in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target])
        for name, value in _target_pairs(target, stmt.value)
        if not name.startswith('.')
    ]


def _match_pairs(node: ast.Match) -> list[tuple[str, ast.expr]]:
    """A capture nested in ``|`` or a sequence pattern may hold the subject or,
    for a literal sequence, any element of it."""
    subjects = [node.subject]
    if isinstance(node.subject, ast.Tuple | ast.List):
        subjects += node.subject.elts
    return [
        (sub.name, subject)
        for case in node.cases
        for sub in ast.walk(case.pattern)
        if isinstance(sub, ast.MatchAs | ast.MatchStar) and sub.name
        for subject in subjects
    ]


def _binding_pairs(tree: ast.AST) -> list[tuple[str, ast.expr]]:
    """Every ``(name, value)`` binding Python lets a file write.

    Assignment (unpacked too), walrus, ``for`` over a literal container,
    parameter and lambda defaults, and a ``match`` capture of the subject.
    """
    pairs: list[tuple[str, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                pairs += _target_pairs(target, node.value)
        elif isinstance(node, ast.AnnAssign | ast.NamedExpr):
            if node.value is not None:
                pairs += _target_pairs(node.target, node.value)
        elif isinstance(node, ast.For | ast.AsyncFor):
            it = node.iter
            elements = (
                it.elts if isinstance(it, ast.Tuple | ast.List | ast.Set) else [it]
            )
            for element in elements:
                pairs += _target_pairs(node.target, element)
        elif isinstance(node, ast.arguments):
            positional = [*node.posonlyargs, *node.args]
            for arg, default in zip(
                positional[len(positional) - len(node.defaults) :],
                node.defaults,
                strict=True,
            ):
                pairs.append((arg.arg, default))
            pairs += [
                (arg.arg, default)
                for arg, default in zip(node.kwonlyargs, node.kw_defaults, strict=True)
                if default is not None
            ]
        elif isinstance(node, ast.ClassDef):
            pairs += _class_pairs(node)
        elif isinstance(node, ast.Match):
            pairs += _match_pairs(node)
    return pairs


def _chain_paths(
    node: ast.expr,
    bindings: dict[str, set[str]],
) -> set[str]:
    """Append an attribute chain to the name's already resolved candidates."""
    attrs: list[str] = []
    while True:
        if isinstance(node, ast.Attribute):
            attrs.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Call) and (attr := _literal_getattr_name(node)):
            attrs.append(attr)  # ``getattr(m, "x")`` is ``m.x`` spelled as data
            node = node.args[0]
        else:
            break
    if not isinstance(node, ast.Name):
        return set()
    attrs.reverse()
    bases = bindings.get(node.id, set())
    paths = {'.'.join([base, *attrs]) for base in bases}
    if attrs:
        # An attribute store (``self.e = events``) binds ``.e`` for any receiver.
        paths |= {
            '.'.join([base, *attrs[1:]]) for base in bindings.get(f'.{attrs[0]}', set())
        }
        # A class attribute read through the class: ``H.e`` is bound as a name.
        paths |= {
            '.'.join([base, *attrs[1:]])
            for base in bindings.get(f'{node.id}.{attrs[0]}', set())
        }
    return paths


def _literal_getattr_name(node: ast.Call) -> str | None:
    """The attribute name of ``getattr(obj, "name")``, when it is a literal."""
    if (
        isinstance(node.func, ast.Name)
        and node.func.id == 'getattr'
        and len(node.args) >= 2
    ):
        name = node.args[1]
        if isinstance(name, ast.Constant) and isinstance(name.value, str):
            return name.value
    return None


def _follow_aliases(tree: ast.AST, bindings: dict[str, set[str]]) -> None:
    """Resolve candidate sets once per file, without enumerating alias routes.

    Rebinding never erases a possible module. Propagate paths until no name
    gains a candidate, so later bindings and cycles need no recursive walk.
    """
    aliases: dict[str, list[ast.expr]] = {}
    for name, value in _binding_pairs(tree):
        aliases.setdefault(name, []).extend(_value_leaves(value))
    # The previous traversal stopped at a repeated assignment. Its paths
    # therefore contain at most all the attributes written in alias values.
    # Keep that finite ceiling: a dotted cycle must not grow paths forever.
    max_depth = max(
        (path.count('.') for paths in bindings.values() for path in paths),
        default=0,
    ) + sum(
        isinstance(node, ast.Attribute)
        or (isinstance(node, ast.Call) and _literal_getattr_name(node) is not None)
        for values in aliases.values()
        for value in values
        for node in ast.walk(value)
    )
    changed = True
    while changed:
        changed = False
        for name, values in aliases.items():
            paths = bindings.setdefault(name, set())
            before = len(paths)
            for value in values:
                paths.update(
                    path
                    for path in _chain_paths(value, bindings)
                    if path.count('.') <= max_depth
                )
            changed |= len(paths) != before


def _app_references(tree: ast.AST, rel_path: Path) -> list[_AppReference]:
    """Every ``app.`` name the file reaches that the path ban has not judged.

    Imports and assignments supply roots for the attribute chains. Only the
    outermost link of a chain is recorded — resolution
    walks it link by link. A name bound by a statement the path ban already
    covers is left to that ban, so one reach is one finding.
    """
    bindings: dict[str, set[str]] = {}
    references: list[_AppReference] = []
    inner: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden(alias.name):
                    continue
                root = alias.name.split('.')[0]
                bindings.setdefault(alias.asname or root, set()).add(
                    alias.name if alias.asname else root
                )
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_module(node, rel_path)
            if base is None:
                continue
            for alias in node.names:
                target = f'{base}.{alias.name}'
                if node.level == 0 and _is_forbidden(target):
                    continue
                if alias.name != '*':
                    bindings.setdefault(alias.asname or alias.name, set()).add(target)
                references.append(_AppReference(target, rel_path, node.lineno))
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            inner.add(id(node.value))

    _follow_aliases(tree, bindings)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and id(node) not in inner:
            paths = _chain_paths(node, bindings)
        elif isinstance(node, ast.Call) and _literal_getattr_name(node):
            paths = _chain_paths(node, bindings)
        else:
            continue
        references += [_AppReference(p, rel_path, node.lineno) for p in paths]

    references += _namespace_escapes(tree, rel_path, bindings)

    return [r for r in references if r.path.startswith('app.')]


# Module attributes that read the namespace by a name given as data.
_NAMESPACE_ACCESSORS = frozenset({'__dict__', '__getattribute__'})
_SCOPE_READERS = frozenset({'globals', 'locals', 'vars'})


def _namespace_escapes(
    tree: ast.AST, rel_path: Path, bindings: dict[str, set[str]]
) -> list[_AppReference]:
    """References for every way a module's whole namespace leaves the file.

    ``vars(events)``, ``events.__dict__``, ``m = [events]``, ``getattr(events,
    name)``: each hands the module over as a value, so which attribute is read
    afterwards is data the scan cannot follow. The supported boundary is that
    a module reached from ``app.`` is used by attribute (or literal
    ``getattr``) only; any other use counts as reading *all* of its names, and
    is refused when one of them is a ``FORBIDDEN_OBJECTS`` entry.
    """
    followed: set[int] = set()  # expressions whose use is read link by link
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr not in _NAMESPACE_ACCESSORS:
            followed.add(id(node.value))
        elif (
            isinstance(node, ast.Call)
            and (attr := _literal_getattr_name(node))
            and attr not in _NAMESPACE_ACCESSORS
        ):
            followed.add(id(node.args[0]))
        elif isinstance(node, ast.Assign) and all(
            isinstance(t, ast.Name) for t in node.targets
        ):
            followed.add(id(node.value))  # a rebinding; _follow_aliases walks it
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and isinstance(
            node.target, ast.Name
        ):
            if node.value is not None:
                followed.add(id(node.value))
    refs: list[_AppReference] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Name, ast.Attribute))
            and isinstance(node.ctx, ast.Load)
            and id(node) not in followed
        ) or (
            isinstance(node, ast.Call)
            and _literal_getattr_name(node)
            and id(node) not in followed
        ):
            paths = _chain_paths(node, bindings)
        else:
            continue
        refs += [_AppReference(f'{p}.**', rel_path, node.lineno) for p in paths]
    for node in ast.walk(tree):
        # ``globals()['events']`` hands over every module the file imported
        # as data, with no Name load to follow.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _SCOPE_READERS
            and not node.args
        ):
            refs += [
                _AppReference(f'{p}.**', rel_path, node.lineno)
                for paths in bindings.values()
                for p in paths
            ]
    return refs


_MISSING = object()


def _repository_module(name: str) -> object | None:
    """Import *name* if it is repository code, else ``None``.

    Never a module directory the repository does not ship: resolving a name
    must not execute the code the scan is there to judge, nor another
    dropped module's.
    """
    parts = name.split('.')
    if parts[:2] == ['app', 'modules'] and len(parts) > 2:
        if parts[2] not in REPO_SHIPPED_MODULES:
            return None
    try:
        return importlib.import_module(name)
    except ImportError:
        return None  # a name that does not import here holds nothing here


def _banned_in_namespace(
    module: ModuleType, banned: list[object], seen: set[int] | None
) -> str | None:
    """The dotted name of a banned object held in *module* or a module it holds.

    A whole-namespace read (``vars()``, ``__dict__``, a computed ``getattr``)
    exposes every name the module holds, not just what ``__all__`` or a star
    import would, and reaches its submodules' namespaces next, so the search
    covers all names and follows module-valued ones inside ``app.``. A star
    import is narrower: *seen* is ``None`` and only the exports are searched.
    """
    if seen is None:
        exported: list[str] = getattr(module, '__all__', None) or [
            n for n in vars(module) if not n.startswith('_')
        ]
        for name in exported:
            if any(getattr(module, name, None) is b for b in banned):
                return name
        return None
    seen.add(id(module))
    held = vars(module)
    for name, value in held.items():
        if any(value is b for b in banned):
            return name
    for name, child in held.items():
        if (
            inspect.ismodule(child)
            and child.__name__.startswith('app.')
            and id(child) not in seen
            and (found := _banned_in_namespace(child, banned, seen))
        ):
            return f'{name}.{found}'
    return None


def _resolve_banned(path: str, banned: list[object]) -> str | None:
    """The prefix of *path* that is a banned object, or ``None``.

    Walked the way Python binds it: an attribute of the module so far, else
    its submodule. The walk goes through modules only — a banned object is
    held in a module namespace, and reading attributes of arbitrary objects
    would run their code.
    """
    parts = path.split('.')
    current: object | None = _repository_module('app')
    for depth in range(2, len(parts) + 1):
        if not inspect.ismodule(current):
            return None
        part = parts[depth - 1]
        if part in ('*', '**'):
            prefix = '.'.join(parts[: depth - 1])
            if found := _banned_in_namespace(
                current, banned, set() if part == '**' else None
            ):
                return f'{prefix}.{found}'
            return None
        name = '.'.join(parts[:depth])
        current = getattr(current, part, _MISSING)
        if current is _MISSING:
            current = _repository_module(name)
        if any(current is b for b in banned):
            return name
    return None


def _banned_object_findings(
    module_name: str, references: list[_AppReference]
) -> list[SafetyFinding]:
    """References that resolve to a ``FORBIDDEN_OBJECTS`` entry, or to a
    ``SHIPPED_ONLY_OBJECTS`` one from a module this repository does not ship."""
    dotted_names = (
        [] if module_name in TRUSTED_SHIPPED_MODULES else [*FORBIDDEN_OBJECTS]
    )
    if module_name not in REPO_SHIPPED_MODULES:
        dotted_names += SHIPPED_ONLY_OBJECTS
    if not dotted_names or not references:
        return []
    banned: list[object] = []
    for dotted in dotted_names:
        owner, _, attr = dotted.rpartition('.')
        banned.append(getattr(importlib.import_module(owner), attr))

    exemptions = CORE_EXEMPTIONS.get(module_name, [])
    findings: list[SafetyFinding] = []
    seen: set[tuple[Path, int, str]] = set()
    for ref in references:
        subject = _resolve_banned(ref.path, banned)
        if subject is None or subject in exemptions:
            continue
        if (ref.rel_path, ref.lineno, subject) in seen:
            continue
        seen.add((ref.rel_path, ref.lineno, subject))
        findings.append(
            SafetyFinding(
                kind='forbidden_import',
                rel_path=ref.rel_path,
                subject=subject,
                lineno=ref.lineno,
            )
        )
    return findings


def _callable_aliases(tree: ast.AST) -> dict[str, set[str]]:
    """Local names bound to policed callables under another spelling.

    ``from importlib import import_module as im`` and ``im = import_module``
    both call the forbidden function, and the call matcher only sees ``im``.
    A name keeps a *set* of sources, like ``_follow_aliases``: rebinding one
    name to two policed callables must keep both. Sets only grow, so the loop
    ends; a single value per name would flip between the two forever.
    """
    # The getters are followed too: ``g = getattr`` and a bound ``attrgetter``
    # fetch a policed callable by name, which the call matcher cannot see.
    policed = {*FORBIDDEN_CALLS, 'open', *_GETTERS}
    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname and alias.name in policed:
                    aliases.setdefault(alias.asname, set()).add(alias.name)
    pairs = _binding_pairs(tree)
    changed = True
    while changed:
        changed = False
        for name, value in pairs:
            sources = {
                s
                for s in _callable_sources(value, aliases)
                if s in policed or s.startswith(_FETCHES)
            }
            if not sources <= aliases.get(name, set()):
                aliases.setdefault(name, set()).update(sources)
                changed = True
    return aliases


_CALLABLE_CARRIERS = frozenset({'map', 'filter', 'partial'})
_GETTERS = frozenset({'getattr', 'attrgetter'})
# ``attrgetter("x")`` is not ``x`` yet, only a promise to read it from whatever
# it is called with; the source carries that pending name under this prefix.
_FETCHES = 'attrgetter:'
# Methods that hand back an element of their receiver, as ``d[k]`` does.
_ELEMENT_READERS = frozenset({'get', 'pop', 'setdefault', '__getitem__'})


def _callable_sources(node: ast.expr, aliases: dict[str, set[str]]) -> set[str]:
    """The callable names *node* may evaluate to, under any alias spelling."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id, set()) | {node.id}
    if isinstance(node, ast.Attribute):
        return _attribute_sources(node.value, node.attr, aliases)
    if isinstance(node, ast.Subscript):
        return _callable_sources(node.value, aliases)
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return {s for e in node.elts for s in _callable_sources(e, aliases)}
    if isinstance(node, ast.Dict):
        return {s for v in node.values for s in _callable_sources(v, aliases)}
    if isinstance(node, ast.Call):
        return _call_result_sources(node, aliases)
    return {
        s
        for leaf in _value_leaves(node)
        if leaf is not node
        for s in _callable_sources(leaf, aliases)
    }


def _call_result_sources(node: ast.Call, aliases: dict[str, set[str]]) -> set[str]:
    """The callable names a call may *return*, as opposed to the ones it runs."""
    # ``partial(fn, ...)`` evaluates to a callable that runs *fn*.
    if _carrier_name(node) == 'partial' and node.args:
        return _callable_sources(node.args[0], aliases)
    called = _callable_sources(node.func, aliases)
    found: set[str] = set()
    # ``getattr(importlib, 'import_module')`` is the callable itself, under
    # whatever name or module path ``getattr`` is reached by.
    if 'getattr' in called and (name := _literal_arg(node, 1)):
        found |= _attribute_sources(node.args[0], name, aliases)
    if 'attrgetter' in called and (name := _literal_arg(node, 0)):
        found.add(_FETCHES + name.rpartition('.')[2])
    receiver = node.args[0] if node.args else node.func
    for source in called:
        if source.startswith(_FETCHES):
            found |= _attribute_sources(receiver, source[len(_FETCHES) :], aliases)
    # ``d.get('i')`` reads an element, like ``d['i']``; a default may be it too.
    if isinstance(node.func, ast.Attribute) and node.func.attr in _ELEMENT_READERS:
        found |= _callable_sources(node.func.value, aliases)
        found |= {s for arg in node.args[1:] for s in _callable_sources(arg, aliases)}
    return found


def _literal_arg(node: ast.Call, index: int) -> str | None:
    if len(node.args) > index:
        arg = node.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _attribute_sources(
    receiver: ast.expr, attr: str, aliases: dict[str, set[str]]
) -> set[str]:
    found = aliases.get(f'.{attr}', set()) | {attr}
    if isinstance(receiver, ast.Name):
        # A class attribute read through the class: ``H.fn`` is bound as ``H.fn``.
        found |= aliases.get(f'{receiver.id}.{attr}', set())
    return found


def _carrier_name(node: ast.Call) -> str | None:
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, 'attr', None)
    return name if name in _CALLABLE_CARRIERS else None


def _called_names(node: ast.Call, aliases: dict[str, set[str]]) -> set[str]:
    names = _callable_sources(node.func, aliases)
    if _carrier_name(node) and node.args:
        # ``map(fn, ...)`` and ``partial(fn, ...)`` run *fn* without naming a call.
        names |= _callable_sources(node.args[0], aliases)
    return names


def _names_module(name: str, trigger: str) -> bool:
    """Whether *name* is the trigger module or a module inside it.

    A bare prefix match read ``opening_stock_service`` as ``open`` and
    ``system_health`` as ``sys``; the boundary is the dot, not the letter.
    """
    return name == trigger or name.startswith(trigger + '.')


def on_module_import_surface(name: str, module_name: str) -> bool:
    """Whether an ``app.`` import *name* is on the declared module surface.

    Three prefixes are the promise — ``app.core.contracts``,
    ``app.core.public_api`` and ``app.core.module_sdk`` — and a module always
    owns its own package. The check is the dot boundary, not the letters:
    ``app.core.contracts_something`` is another module, not ``contracts``.

    The scan applies this to a module the repository does not ship, where no
    human review stands between the author and the running process. A shipped
    module predates the door: its current reaches are frozen in
    ``module_import_surface_baseline.txt`` and the architecture lint holds it
    to that list instead.
    """
    allowed = (*MODULE_IMPORT_SURFACE, f'app.modules.{module_name}')
    return any(name == prefix or name.startswith(prefix + '.') for prefix in allowed)


def _stays_on_the_surface(
    node: ast.Import | ast.ImportFrom,
    name: str,
    module_name: str,
    required_modules: Collection[str],
) -> bool:
    """Whether an ``app.`` import *name* reaches only what the module may reach.

    ``from app.core import module_sdk`` names ``app.core``, which is off the
    surface, and binds ``app.core.module_sdk``, which is on it — the module
    ``import app.core.module_sdk`` binds. So a ``from`` import whose package is
    off the surface is judged by what each of its names binds; one name off
    the surface refuses the statement, under the package's name. A declared
    door reads the same way (``from app.modules.warehouse import
    warehouse_api``), as the lint's frozen list already did for a shipped
    module.
    """

    def allowed(dotted: str) -> bool:
        return on_module_import_surface(dotted, module_name) or is_declared_module_door(
            dotted, required_modules
        )

    if allowed(name):
        return True
    return isinstance(node, ast.ImportFrom) and all(
        allowed(f'{name}.{alias.name}') for alias in node.names
    )


def is_declared_module_door(name: str, required_modules: Collection[str]) -> bool:
    """Whether *name* is the public API of a shipped module the manifest requires.

    The warehouse seams — a pre-post check, a work-item provider, a pick
    order — are registered through ``warehouse_api``, so a module that may
    reach only Core could extend the warehouse in documentation alone. The
    door is the one the cross-module rule names for the modules shipped here:
    ``app.modules.<m>.<m>_api``, exactly that path, of a module this
    repository ships (its code was reviewed here; another installed module's
    was not), and only for a module that lists ``<m>`` under ``requires`` —
    the dependency is a written decision, the way the frozen list is one for
    a shipped module. The rest of that module's tree stays closed; the
    package spelling of the door itself (``from app.modules.warehouse import
    warehouse_api``) is the same door (``_stays_on_the_surface``).
    """
    parts = name.split('.')
    if len(parts) != 4 or parts[:2] != ['app', 'modules']:
        return False
    target, leaf = parts[2], parts[3]
    return (
        leaf == f'{target}_api'
        and target in REPO_SHIPPED_MODULES
        and target in required_modules
    )


def declared_required_modules(module_dir: Path) -> list[str]:
    """The ``requires`` list of the module's manifest, as the scan reads it.

    Read here rather than passed in like the capabilities: the four callers
    load the manifest for its capabilities alone, and the door is the scan's
    rule, not theirs. An unreadable manifest requires nothing — the manifest
    check refuses the module on its own account.
    """
    try:
        manifest = json.loads(
            (module_dir / 'manifest.json').read_text(encoding='utf-8')
        )
    except (OSError, ValueError):
        return []
    requires = manifest.get('requires') if isinstance(manifest, dict) else None
    if not isinstance(requires, list):
        return []
    return sorted(name for name in requires if isinstance(name, str))


def _scan_import(
    node: ast.Import | ast.ImportFrom,
    *,
    module_name: str,
    rel_path: Path,
    declared_capabilities: list[str],
    required_modules: Collection[str] = (),
) -> list[SafetyFinding]:
    findings: list[SafetyFinding] = []
    # A module file lives at app.modules.<rel_path without the file name>.
    package = ('app', 'modules', *rel_path.parts[:-1])
    exemptions = CORE_EXEMPTIONS.get(module_name, [])

    for name in _imported_names(node, package):
        base_import = name.split('.')[0]

        if base_import in exemptions or name in exemptions:
            continue

        if _is_forbidden(name):
            # A trusted shipped module may reach internal 'app.' resources;
            # third-party bans (subprocess, socket, ...) still apply to it.
            # The set is the shipped directories, not every name that ever
            # carried the trust: a trust decision a directory can claim by
            # naming itself is no decision at all.
            if module_name in TRUSTED_SHIPPED_MODULES and name.startswith('app.'):
                continue
            findings.append(
                SafetyFinding(
                    kind='forbidden_import',
                    rel_path=rel_path,
                    subject=name,
                    lineno=node.lineno,
                )
            )
            continue

        # Anything else under ``app.`` is Core's own business. The scan used
        # to allow it, which made every helper a shipped module happened to
        # import a contract nobody had promised to keep. A module installed
        # from outside may reach the three promised prefixes and its own
        # files; a module the repository ships is baselined by the lint.
        if (
            module_name not in REPO_SHIPPED_MODULES
            and (name == 'app' or name.startswith('app.'))
            and not _stays_on_the_surface(node, name, module_name, required_modules)
        ):
            findings.append(
                SafetyFinding(
                    kind='off_surface_import',
                    rel_path=rel_path,
                    subject=name,
                    lineno=node.lineno,
                    hint=(
                        'A module outside this repository may import only '
                        f'{", ".join(MODULE_IMPORT_SURFACE)} — plus its own '
                        'files, and app.modules.<m>.<m>_api of a module this '
                        'repository ships that its manifest lists under '
                        '"requires". Take the name from app.core.module_sdk; '
                        'if it is not exported there, ask for it to be added.'
                    ),
                )
            )
            continue

        for cap, triggers in CAPABILITY_MAP.items():
            if any(_names_module(name, t) for t in triggers):
                if cap not in declared_capabilities:
                    findings.append(
                        SafetyFinding(
                            kind='undeclared_capability',
                            rel_path=rel_path,
                            subject=name,
                            lineno=node.lineno,
                            capability=cap,
                        )
                    )

    return findings


def _scan_call(
    node: ast.Call,
    *,
    rel_path: Path,
    declared_capabilities: list[str],
    aliases: dict[str, set[str]],
) -> list[SafetyFinding]:
    names = _called_names(node, aliases)
    findings: list[SafetyFinding] = [
        SafetyFinding(
            kind='forbidden_call',
            rel_path=rel_path,
            subject=func_name,
            lineno=node.lineno,
        )
        for func_name in sorted(names & set(FORBIDDEN_CALLS))
    ]

    if 'open' in names and 'filesystem' not in declared_capabilities:
        findings.append(
            SafetyFinding(
                kind='undeclared_capability',
                rel_path=rel_path,
                subject='open()',
                lineno=node.lineno,
                capability='filesystem',
            )
        )

    return findings


def _cache_dir() -> Path:
    """Where scan results live between runs.

    Under the system temp dir rather than the source tree: the result depends
    only on file contents, several workers share it, and losing it costs one
    rescan. ``INVENTARI_VALIDATION_CACHE_DIR`` overrides it for tests.
    """
    override = os.environ.get('INVENTARI_VALIDATION_CACHE_DIR')
    base = Path(override) if override else Path(tempfile.gettempdir())
    return base / 'inventari-module-validation'


def _fingerprint(module_dir: Path, declared_capabilities: list[str]) -> str:
    """Identity of one scan: every scanned file's content, plus the policy.

    Content hashing rather than mtime — a checkout, a container rebuild or a
    volume mount all reset mtimes without changing a byte, which would throw
    the cache away exactly when it is most useful. Reading the files is the
    cheap part; parsing them is not.

    The capability list is part of the key because it decides whether an
    import is a violation, and the policy constants are too: bump
    ``_POLICY_VERSION`` when the rules change, or a stale entry would answer
    for a rule that no longer exists.
    """
    digest = hashlib.sha256()
    digest.update(_POLICY_VERSION.encode())
    # The scanner's own code is part of the verdict too: a fix to how a rule
    # is applied must not keep answering from entries the old logic wrote.
    digest.update(Path(__file__).read_bytes())
    # The module's own name changes the verdict — CORE_EXEMPTIONS and
    # TRUSTED_SHIPPED_MODULES are keyed by it, so 'import subprocess' is a
    # violation in one module and allowed in another with identical bytes.
    digest.update(module_dir.name.encode())
    digest.update(repr(sorted(declared_capabilities)).encode())
    # So does what the manifest requires: it opens the door to that module's
    # public API (``is_declared_module_door``).
    digest.update(repr(declared_required_modules(module_dir)).encode())
    for py_file in sorted(module_dir.rglob('*.py')):
        digest.update(str(py_file.relative_to(module_dir)).encode())
        try:
            digest.update(py_file.read_bytes())
        except OSError:
            # Unreadable now means the scan will report it; fold that into the
            # key so the finding is not served from a run where it was fine.
            digest.update(b'<unreadable>')
    return digest.hexdigest()


_Scan = tuple[list[SafetyFinding], list[_AppReference]]


def _load_cached(path: Path) -> _Scan | None:
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    try:
        findings = [
            SafetyFinding(
                kind=entry['kind'],
                rel_path=Path(entry['rel_path']),
                subject=entry['subject'],
                lineno=entry['lineno'],
                capability=entry['capability'],
                hint=entry.get('hint'),
            )
            for entry in raw['findings']
        ]
        references = [
            _AppReference(
                path=entry['path'],
                rel_path=Path(entry['rel_path']),
                lineno=entry['lineno'],
            )
            for entry in raw['references']
        ]
    except (KeyError, TypeError):
        return None  # written by an older shape; rescan and overwrite
    return findings, references


def _store_cached(path: Path, scan: _Scan) -> None:
    findings, references = scan
    payload = {
        'findings': [
            {
                'kind': f.kind,
                'rel_path': str(f.rel_path),
                'subject': f.subject,
                'lineno': f.lineno,
                'capability': f.capability,
                'hint': f.hint,
            }
            for f in findings
        ],
        'references': [
            {'path': r.path, 'rel_path': str(r.rel_path), 'lineno': r.lineno}
            for r in references
        ],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: four workers start at once, and a half-written
        # file read as valid JSON would be a safety verdict nobody computed.
        tmp = path.with_suffix(f'.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(payload), encoding='utf-8')
        tmp.replace(path)
    except OSError as exc:
        logger.debug('Could not cache safety scan for %s: %s', path.stem, exc)


def analyze_module_safety(
    module_dir: Path, declared_capabilities: list[str], *, use_cache: bool = True
) -> list[SafetyFinding]:
    """Walk a module's Python files and report every safety problem found.

    ``models.py`` and ``migrations/`` are scanned like every other file: the
    first executes when the module package is imported, the second when the
    module is installed, so either can carry a forbidden import into the
    running system. Only the module's own ``tests/`` directories are
    skipped — a scope decision, not a safety property. Inside the working
    tree a ``tests/`` file is an ordinary importable part of the module
    package (``import app.modules.<name>.tests.<file>`` executes it), so the
    only thing keeping one out of a running system is the installer, which
    drops ``tests/`` before copying anything. A module installed through the
    CLI carries none; a tree bind-mounted or copied by hand still does.
    Skipping them keeps the report reading like what an operator installs —
    tests never survive that path — and spares the workshop: importing
    foreign modules is the point of a test, so scanning them would turn
    every exercise into a finding.

    Results are cached by content fingerprint. Discovery parses several hundred
    files in each of four workers on every restart, and the answer only changes
    when the files do. Pass ``use_cache=False`` to force a fresh scan.
    What the module's ``app.`` names resolve to depends on code outside it,
    so that part is never served from the cache: the references are cached,
    the identity check against ``FORBIDDEN_OBJECTS`` runs every time.
    """
    if use_cache:
        cache_path = (
            _cache_dir() / f'{_fingerprint(module_dir, declared_capabilities)}.json'
        )
        cached = _load_cached(cache_path)
        if cached is not None:
            logger.debug('Safety scan cache hit for %s', module_dir.name)
            scan = cached
        else:
            scan = _scan(module_dir, declared_capabilities)
            _store_cached(cache_path, scan)
    else:
        scan = _scan(module_dir, declared_capabilities)

    findings, references = scan
    return findings + _banned_object_findings(module_dir.name, references)


def _scan(module_dir: Path, declared_capabilities: list[str]) -> _Scan:
    findings: list[SafetyFinding] = []
    references: list[_AppReference] = []
    module_name = module_dir.name
    required_modules = declared_required_modules(module_dir)

    for py_file in sorted(module_dir.rglob('*.py')):
        if _is_test_file(py_file, module_dir):
            continue

        rel_path = py_file.relative_to(module_dir.parent)

        try:
            source = py_file.read_text(encoding='utf-8')
            tree = ast.parse(source, filename=str(py_file))
        except Exception as exc:  # noqa: BLE001 — a gate that crashes is a gate that gets skipped
            findings.append(
                SafetyFinding(kind='parse_error', rel_path=rel_path, subject=str(exc))
            )
            continue

        # Every statement counts, including bodies under ``if TYPE_CHECKING:``:
        # Python binds names in more ways than any heuristic can enumerate, so
        # a guard honoured on faith is a pocket in every file the scan reads.
        # A genuinely type-only import is a narrow CORE_EXEMPTIONS entry with
        # a justification, not a rule the scanner guesses at.
        aliases = _callable_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                findings += _scan_import(
                    node,
                    module_name=module_name,
                    rel_path=rel_path,
                    declared_capabilities=declared_capabilities,
                    required_modules=required_modules,
                )
            elif isinstance(node, ast.Call):
                findings += _scan_call(
                    node,
                    rel_path=rel_path,
                    declared_capabilities=declared_capabilities,
                    aliases=aliases,
                )
        references += _app_references(tree, rel_path)

    return findings, references
