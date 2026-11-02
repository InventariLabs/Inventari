"""Every write path reaches the organization journal — or says why it does not.

``log_action_async`` (``app/services/audit_service.py``) is called by hand
from ~80 sites, and nothing notices a write path that never reaches it.
The known instance is document cancel: the status flips, the stock is
released, the transaction commits, and no entry says the document was
cancelled — while the approval-request cascade beside it journals its own
row, so a reachability check that counted any entry anywhere would call
the path covered.

This check takes the two surfaces a write reaches the database through and
requires each to reach ``log_action_async``:

- every mutating route handler (POST/PUT/PATCH/DELETE) in ``app/api/**``
  and ``app/modules/**`` — whether registered by decorator (``@router.post``
  or ``@router.api_route``) or through ``router.add_api_route`` (the
  storages route table uses the latter, and a scan that walks
  ``decorator_list`` alone never sees it), and
- every public method of a ``Core*`` namespace class in
  ``app/core/public_api/**`` (the surface a module calls for Core data).

A source counts as a write when its call graph — resolved through imports,
re-exports and the ``core_api``/``*_api`` singleton assignments — reaches a
write primitive: a session-scoped ``.add``/``.add_all``/``.delete``/
``.merge``/``.flush``/``.execute(insert|update|delete)`` or any
``.commit()``. A read-only source is not a finding: a search endpoint that
posts is not a write that failed to journal.

**The entry must live where the act lives.** A reachable ``log_action_async``
counts when it sits in Core (``app/api``, ``app/services``, ``app/core``)
or in the same vertical module as the source. A cross-module cascade — the
approval request cancelled beside a document — writes its own module's row
about its own record, and counting it is exactly how document cancel stayed
invisible. A module that delegates an act to another module's public API
either journals the act itself or takes a reasoned baseline entry saying
the other module's service owns the entry.

What the gate cannot see, stated so nobody reads it as more than it is:
Python is resolved statically, so a callee reached through a dict of
handlers, a ``getattr`` string or a variable holding a function is an edge
this index does not follow, and a write that touches no session-scoped
method (an ORM attribute set that relies on the caller's commit, with no
``flush`` anywhere) is not recognised as a write at all.

Findings ride a reasoned baseline — ``audit_coverage_baseline.txt``, one
owned entry per key, ``<key> | owner=<who> | expires=<date> | <reason>`` —
whose size the ratchet in ``baseline_sizes.txt`` records. A path that
cannot journal by design (login, read-marking, a working note, an outbox
row) belongs there with the reason; a path that simply lost its entry is
debt, and the reason names its follow-up.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from ._constants import _is_test_file
from ._run_cache import once_per_run

_HTTP_METHODS = frozenset({'post', 'put', 'patch', 'delete'})
_WRITE_ATTRS = frozenset({'add', 'add_all', 'delete', 'merge', 'flush'})
_LOGGING_ATTR = 'log_action_async'
_EXECUTE_ATTR = 'execute'
_WRITE_STATEMENT_MARKERS = ('insert(', 'update(', 'delete(')
_CORE_API_CLASS_PREFIX = 'Core'
_SESSION_PARAM_NAMES = frozenset({'db', 'session', 'sess'})


@dataclass(frozen=True)
class AuditCoverageGap:
    """One write path that reaches no journal entry in its own domain."""

    key: str
    rel_path: str
    lineno: int
    label: str
    kind: str


@dataclass
class _Function:
    key: tuple[str, str]  # (module, qualname)
    rel_path: str
    lineno: int
    class_name: str | None
    calls: list[tuple[str, ...]] = field(default_factory=list)
    direct_log: bool = False
    direct_write: bool = False


@dataclass
class _Module:
    name: str
    rel_path: str
    tree: ast.Module
    package: bool
    imports: dict[str, tuple[str, str, str | None]] = field(default_factory=dict)
    assignments: dict[str, str] = field(default_factory=dict)
    functions: dict[str, _Function] = field(default_factory=dict)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)


#: A partially resolved reference during the import-aware walk.
@dataclass
class _Ref:
    kind: str  # 'fn' | 'class' | 'module' | 'coreapi' | 'coreapi_ns' | 'log'
    fn: _Function | None = None
    module: str = ''
    name: str = ''


def _module_name(rel: Path) -> str:
    parts = list(rel.with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(('app', *parts))


def _dotted(node: ast.AST) -> tuple[str, ...] | None:
    """``a.b.c(…)`` as ``('a', 'b', 'c')``; anything computed returns None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return tuple(reversed(parts))
    return None


def _session_names(node: ast.AST) -> set[str]:
    """Parameter names that hold the session inside this function.

    The receiver decides: ``claimed.add(x)`` is a set, ``db.add(x)`` is a
    write. A session arrives as a parameter annotated ``AsyncSession`` or
    named like one; ``db_session``/``real_async_db_session`` are the test
    fixtures and never reach this scan.
    """
    names: set[str] = set()
    args = getattr(node, 'args', None)
    for arg in getattr(args, 'args', ()):
        annotation = ast.unparse(arg.annotation) if arg.annotation else ''
        name: str = arg.arg
        if (
            'Session' in annotation
            or name in _SESSION_PARAM_NAMES
            or name.endswith(('_db', '_session'))
        ):
            names.add(name)
    return names


def _receiver_is_session(fn_names: set[str], dotted: tuple[str, ...]) -> bool:
    if len(dotted) < 2:
        return False
    receiver = dotted[-2]
    if receiver in fn_names:
        return True
    if '.'.join(dotted[:-1]) in {
        'self.db',
        'self._db',
        'self.session',
        'self._session',
    }:
        return True
    return receiver.endswith(('_db', '_session')) and receiver not in {
        'db_url',
        'db_engine',
    }


def _make_function(
    module_name: str,
    rel_path: str,
    class_name: str | None,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    qualname: str | None = None,
) -> _Function:
    if qualname is None:
        qualname = node.name if class_name is None else f'{class_name}.{node.name}'
    fn = _Function(
        key=(module_name, qualname),
        rel_path=rel_path,
        lineno=node.lineno,
        class_name=class_name,
    )
    session_names = _session_names(node)
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        dotted = _dotted(sub.func)
        if dotted is None:
            continue
        fn.calls.append(dotted)
        last = dotted[-1]
        if last == _LOGGING_ATTR:
            fn.direct_log = True
        elif last == 'commit':
            fn.direct_write = True
        elif last in _WRITE_ATTRS and _receiver_is_session(session_names, dotted):
            fn.direct_write = True
        elif last == _EXECUTE_ATTR and _receiver_is_session(session_names, dotted):
            text = ast.unparse(sub)
            if any(marker in text for marker in _WRITE_STATEMENT_MARKERS):
                fn.direct_write = True
    return fn


def _resolve_import_base(module: _Module, level: int, base: str) -> str:
    if not level:
        return base
    package = module.name if module.package else module.name.rsplit('.', 1)[0]
    parts = package.split('.')
    parts = parts[: len(parts) - level + 1]
    return '.'.join((*parts, base)) if base else '.'.join(parts)


class _AppIndex:
    """Functions of ``app/`` keyed by module, with imports resolved.

    Resolution is name-based but import-aware, and deliberately partial:
    the gate follows what a reader can follow (imports, re-exports, the
    facade singletons) and treats anything else as unreachable.
    """

    def __init__(self, app_root: Path) -> None:
        self.app_root = app_root
        self.modules: dict[str, _Module] = {}
        for py_file in sorted(app_root.rglob('*.py')):
            if _is_test_file(py_file, app_root) or '__pycache__' in py_file.parts:
                continue
            rel = py_file.relative_to(app_root)
            module = _parse_module(py_file, rel)
            if module is not None:
                self.modules[module.name] = module
        self._reach_cache: dict[tuple[str, str], tuple[bool, bool]] = {}

    # -- resolution ------------------------------------------------------

    def resolve(
        self,
        module: _Module,
        path: tuple[str, ...],
        class_name: str | None,
    ) -> _Function | None:
        state = self._root_binding(module, path[0], class_name)
        resolved = self._walk(state, path[1:], frozenset())
        if resolved is not None and resolved.kind == 'fn':
            return resolved.fn
        return None

    def _root_binding(
        self, module: _Module, name: str, class_name: str | None
    ) -> _Ref | None:
        if name == 'self' and class_name:
            return _Ref('class', module=module.name, name=class_name)
        if class_name and f'{class_name}.{name}' in module.functions:
            return _Ref('fn', fn=module.functions[f'{class_name}.{name}'])
        if name in module.imports:
            return self._binding_state(module, module.imports[name], frozenset())
        if name in module.functions:
            return _Ref('fn', fn=module.functions[name])
        if name in module.classes:
            return _Ref('class', module=module.name, name=name)
        if name in module.assignments:
            return self._class_state(module.name, module.assignments[name], frozenset())
        return None

    def _binding_state(
        self,
        module: _Module,
        binding: tuple[str, str, str | None],
        seen: frozenset[tuple[str, str]],
    ) -> _Ref | None:
        kind, target, attr = binding
        if kind == 'module':
            return _Ref('module', module=target)
        assert attr is not None
        return self._symbol_state(target, attr, seen)

    def _symbol_state(
        self, module_name: str, attr: str, seen: frozenset[tuple[str, str]]
    ) -> _Ref | None:
        if (module_name, attr) in seen:
            return None
        seen = seen | {(module_name, attr)}
        module = self.modules.get(module_name)
        if module is None:
            # A package without ``__init__.py`` is not in the index, yet
            # ``from <package> import <submodule>`` still names a module.
            return self._submodule_state(module_name, attr)
        if attr in module.functions:
            return _Ref('fn', fn=module.functions[attr])
        if attr in module.classes:
            return _Ref('class', module=module_name, name=attr)
        if attr in module.assignments:
            return self._class_state(module_name, module.assignments[attr], seen)
        if attr in module.imports:
            return self._binding_state(module, module.imports[attr], seen)
        return self._submodule_state(module_name, attr)

    def _submodule_state(self, module_name: str, attr: str) -> _Ref | None:
        submodule = self.modules.get(f'{module_name}.{attr}')
        if submodule is not None:
            return _Ref('module', module=submodule.name)
        return None

    def _class_state(
        self, module_name: str, class_name: str, seen: frozenset[tuple[str, str]]
    ) -> _Ref | None:
        module = self.modules.get(module_name)
        if module is None:
            return None
        if class_name == 'CoreAPI':
            return _Ref('coreapi')
        if class_name in module.classes:
            return _Ref('class', module=module_name, name=class_name)
        if class_name in module.imports:
            return self._binding_state(module, module.imports[class_name], seen)
        return None

    def _walk(
        self, state: _Ref | None, rest: tuple[str, ...], seen: frozenset[str]
    ) -> _Ref | None:
        if state is None:
            return None
        if not rest:
            return state
        attr = rest[0]
        if attr == _LOGGING_ATTR:
            return _Ref('log')
        if state.kind == 'module':
            next_state = self._symbol_state(state.module, attr, frozenset())
            return self._walk(next_state, rest[1:], seen)
        if state.kind == 'class':
            return self._walk_class_attr(state, attr, rest, seen)
        if state.kind == 'coreapi':
            return self._walk(_Ref('coreapi_ns', name=attr), rest[1:], seen)
        if state.kind == 'coreapi_ns':
            return self._walk(self._namespace_method(state.name, attr), rest[1:], seen)
        return None

    def _walk_class_attr(
        self,
        state: _Ref,
        attr: str,
        rest: tuple[str, ...],
        seen: frozenset[str],
    ) -> _Ref | None:
        module = self.modules.get(state.module)
        if module is None:
            return None
        method = module.functions.get(f'{state.name}.{attr}')
        if method is not None:
            return self._walk(_Ref('fn', fn=method), rest[1:], seen)
        class_node = module.classes.get(state.name)
        if class_node is None or state.name in seen:
            return None
        for base in class_node.bases:
            base_path = _dotted(base)
            if base_path is None:
                continue
            base_state = self._root_binding(module, base_path[0], None)
            inherited = self._walk(
                base_state, (*base_path[1:], attr), seen | {state.name}
            )
            if inherited is not None:
                return self._walk(inherited, rest[1:], seen)
        return None

    def _namespace_method(self, namespace: str, attr: str) -> _Ref | None:
        module = self.modules.get(f'app.core.public_api.{namespace}')
        if module is None:
            return None
        for class_name in module.classes:
            if not class_name.startswith(_CORE_API_CLASS_PREFIX):
                continue
            # The namespace class composes mixins (``CoreItemsAPI`` extends
            # the read/write mixins), so the walk has to follow bases.
            resolved = self._walk_class_attr(
                _Ref('class', module=module.name, name=class_name),
                attr,
                (attr,),
                frozenset(),
            )
            if resolved is not None:
                return resolved
        return None

    # -- reachability ----------------------------------------------------

    def reaches(self, source: _Function) -> tuple[bool, bool]:
        """``(writes, logs)`` reachable from *source* in its own domain."""
        if source.key in self._reach_cache:
            return self._reach_cache[source.key]
        seen = {source.key}
        stack = [source]
        writes = False
        logs = False
        while stack:
            fn = stack.pop()
            if fn.direct_write:
                writes = True
            if fn.direct_log and self._log_counts(source, fn):
                logs = True
            module = self.modules[fn.key[0]]
            for path in fn.calls:
                if path[-1] == _LOGGING_ATTR and self._log_counts(source, fn):
                    logs = True
                target = self.resolve(module, path, fn.class_name)
                if target is None or target.key in seen:
                    continue
                seen.add(target.key)
                stack.append(target)
        self._reach_cache[source.key] = (writes, logs)
        return writes, logs

    @staticmethod
    def _log_counts(source: _Function, entry: _Function) -> bool:
        return _domain(entry.key[0]) == 'core' or _domain(entry.key[0]) == _domain(
            source.key[0]
        )


def _domain(module_name: str) -> str:
    parts = module_name.split('.')
    if len(parts) > 2 and parts[:2] == ['app', 'modules']:
        return parts[2]
    return 'core'


def _parse_module(py_file: Path, rel: Path) -> _Module | None:
    try:
        tree = ast.parse(py_file.read_text(encoding='utf-8'))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return None
    module = _Module(
        name=_module_name(rel),
        rel_path='/'.join(rel.parts),
        tree=tree,
        package=py_file.name == '__init__.py',
    )
    _collect_imports(module, tree)
    _collect_definitions(module, tree)
    return module


def _collect_imports(module: _Module, tree: ast.Module) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split('.')[0]
                module.imports[local] = ('module', alias.name, None)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_base(module, node.level, node.module or '')
            for alias in node.names:
                module.imports[alias.asname or alias.name] = (
                    'symbol',
                    base,
                    alias.name,
                )


def _function_defs(
    tree: ast.Module,
) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Module-level functions and the functions declared in their bodies.

    ``register_po_routes(router)`` declares each handler inside its own
    body (``@router.post(...)`` on a nested ``async def``); indexing only
    ``tree.body`` left every such route out of the scan. A nested def is
    keyed ``<outer>.<inner>``.
    """
    defs: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f'{prefix}{child.name}'
                defs.append((qualname, child))
                visit(child, f'{qualname}.')
            elif prefix and not isinstance(child, ast.ClassDef):
                visit(child, prefix)

    visit(tree, '')
    return defs


def _collect_definitions(module: _Module, tree: ast.Module) -> None:
    for qualname, fn_node in _function_defs(tree):
        module.functions[qualname] = _make_function(
            module.name, module.rel_path, None, fn_node, qualname
        )
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            module.classes[node.name] = node
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    module.functions[f'{node.name}.{sub.name}'] = _make_function(
                        module.name, module.rel_path, node.name, sub
                    )
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ):
            module.assignments[node.targets[0].id] = node.value.func.id


def _method_label(method: str, path: str | None) -> str:
    return f'{method.upper()} {path}' if path else method.upper()


def _route_label(node: ast.AST, method: str) -> str:
    for decorator in getattr(node, 'decorator_list', ()):
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute) or func.attr != method:
            continue
        if decorator.args and isinstance(decorator.args[0], ast.Constant):
            path = decorator.args[0].value
            if isinstance(path, str):
                return _method_label(method, path)
    return _method_label(method, None)


def _keyword_argument(node: ast.Call, name: str) -> ast.AST | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _route_table_path(node: ast.Call) -> str | None:
    path = node.args[0] if node.args else _keyword_argument(node, 'path')
    if isinstance(path, ast.Constant) and isinstance(path.value, str):
        return path.value
    return None


def _route_table_methods(node: ast.Call) -> list[str]:
    """The ``methods=`` of ``add_api_route``/``api_route``, lower-cased.

    FastAPI wraps a bare string (``methods='POST'``) into a one-element set,
    so a scan that reads only a list or tuple would see no method at all.
    """
    methods = _keyword_argument(node, 'methods')
    if isinstance(methods, ast.Constant) and isinstance(methods.value, str):
        return [methods.value.lower()]
    if not isinstance(methods, (ast.List, ast.Tuple)):
        return []
    return [
        element.value.lower()
        for element in methods.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]


def _route_table_endpoint(node: ast.Call) -> tuple[str, ...] | None:
    endpoint = (
        node.args[1] if len(node.args) > 1 else _keyword_argument(node, 'endpoint')
    )
    return _dotted(endpoint) if endpoint is not None else None


def _iter_route_table_sources(
    index: _AppIndex, module: _Module
) -> list[tuple[_Function, str]]:
    """``router.add_api_route(…)`` registrations — the other route form.

    ``app/api/storages/__init__.py`` declares its endpoints in one route
    table instead of on each handler, and a write added there would pass a
    decorator-only scan unseen. The endpoint reference resolves through the
    same import-aware index as a decorator's function name.
    """
    sources: list[tuple[_Function, str]] = []
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != 'add_api_route':
            continue
        mutating = [m for m in _route_table_methods(node) if m in _HTTP_METHODS]
        if not mutating:
            continue
        endpoint = _route_table_endpoint(node)
        if endpoint is None:
            continue
        fn = index.resolve(module, endpoint, None)
        if fn is not None:
            sources.append((fn, _method_label(mutating[0], _route_table_path(node))))
    return sources


def _iter_route_sources(index: _AppIndex) -> list[tuple[_Function, str]]:
    sources: list[tuple[_Function, str]] = []
    for module in index.modules.values():
        parts = module.rel_path.split('/')
        if parts[0] not in ('api', 'modules'):
            continue
        for qualname, node in _function_defs(module.tree):
            for decorator in node.decorator_list:
                func = decorator.func if isinstance(decorator, ast.Call) else decorator
                if not isinstance(func, ast.Attribute):
                    continue
                if func.attr in _HTTP_METHODS:
                    label = _route_label(node, func.attr)
                elif func.attr == 'api_route' and isinstance(decorator, ast.Call):
                    # ``@router.api_route(path, methods=[...])`` — the decorator
                    # twin of ``add_api_route``.
                    mutating = [
                        m for m in _route_table_methods(decorator) if m in _HTTP_METHODS
                    ]
                    if not mutating:
                        continue
                    label = _method_label(mutating[0], _route_table_path(decorator))
                else:
                    continue
                sources.append((module.functions[qualname], label))
        sources.extend(_iter_route_table_sources(index, module))
    return sources


def _iter_core_api_sources(index: _AppIndex) -> list[tuple[_Function, str]]:
    sources: list[tuple[_Function, str]] = []
    for module in index.modules.values():
        if not module.rel_path.startswith('core/public_api/'):
            continue
        for qualname, fn in module.functions.items():
            class_name, _, method = qualname.partition('.')
            if (
                not class_name.startswith(_CORE_API_CLASS_PREFIX)
                or class_name == 'CoreAPI'
                or method.startswith('_')
            ):
                continue
            sources.append((fn, f'core_api.{class_name}.{method}'))
    return sources


@once_per_run
def collect_audit_gaps(app_root: Path) -> dict[str, AuditCoverageGap]:
    """``{key: gap}`` for every write source that reaches no entry."""
    index = _AppIndex(app_root)
    gaps: dict[str, AuditCoverageGap] = {}
    for fn, label in (*_iter_route_sources(index), *_iter_core_api_sources(index)):
        writes, logs = index.reaches(fn)
        if not writes or logs:
            continue
        key = f'{fn.rel_path}::{fn.key[1]}'
        gaps[key] = AuditCoverageGap(
            key=key,
            rel_path=fn.rel_path,
            lineno=fn.lineno,
            label=label,
            kind='core_api' if fn.rel_path.startswith('core/public_api/') else 'route',
        )
    return gaps


def _check_audit_coverage(
    app_root: Path, baseline: set[str] | None = None
) -> list[str]:
    """Emit ``::error`` per un-journaled write, ``::notice`` per baselined one."""
    accepted = baseline or set()
    findings: list[str] = []
    for key, gap in sorted(collect_audit_gaps(app_root).items()):
        severity = 'notice' if key in accepted else 'error'
        findings.append(
            f'::{severity} file=app/{gap.rel_path},line={gap.lineno},'
            f'title=Architecture: write without a journal entry::'
            f'{gap.label} writes and no log_action_async is reachable in its '
            f'module or Core. Call it where the act is written — the entry '
            f'rides the same transaction — or add a reasoned entry to '
            f'app/core/audit_coverage_baseline.txt.'
        )
    return findings
