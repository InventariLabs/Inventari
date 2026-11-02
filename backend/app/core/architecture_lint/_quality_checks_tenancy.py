"""Two shape checks on tenancy, and a note on what they cannot see.

The name says "tenancy", which a reader will take to mean "tenant isolation
is checked". It is not, and the gap is worth stating where somebody reading a
green build will see it: **neither guard can see a foreign key written from a
request payload**. Both work on shapes -- a signature, the presence of a word
in a file -- and a handler that takes an id from the caller and stores it
without asking whose row it is has the right shape and the wrong behaviour.
That class is caught by tests, one per reference, not by this file. It has
already been the cause of one real defect (a storage type, an assignee and a
service partner, all accepted from any organisation).

Two guards:

1. ``_check_public_api_optional_org`` — forbids
   ``organization_id: UUID | None = None`` in ``app/core/public_api/``
   signatures. An optional org that defaults to None silently disables the
   tenant filter (cross-org reads). The org must be required; legitimate
   global/system-row access goes through an explicit
   ``include_global: bool = False`` parameter instead -- one the body
   actually reads, since a parameter nobody consults is a switch, not a
   decision.

2. ``_check_escape_hatch_org_filter`` — every file declaring the
   ``allow_direct_db_access`` escape hatch must reference
   ``organization_id`` somewhere (proxy for "queries are org-scoped").
   Alembic ``migrations/env.py`` files are exempt by construction: they
   import models for metadata/autogenerate but never query tenant data
   (carve-out S-2026-08-01). Remaining justified exceptions live in
   ``app/core/escape_hatch_org_filter_baseline.txt`` and emit ``::notice``;
   new violations emit ``::error``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from ._constants import ESCAPE_HATCH_MARKER, _is_test_file, _rel, _rel_parts

_ORG_PARAM_NAMES = frozenset({'organization_id', 'org_id'})
_OPT_OUT_PARAM_NAMES = frozenset({'include_global'})


def _iter_args_with_defaults(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[tuple[ast.arg, ast.expr | None]]:
    """Every parameter of *node* paired with its default, if it has one.

    ``posonlyargs`` belongs here: ``ast.arguments.defaults`` covers
    positional-only and ordinary positional parameters as one run, so a
    function declaring ``def f(db, organization_id, /)`` was invisible to
    both guards below — its org parameter simply did not exist for them.
    """
    positional = [*node.args.posonlyargs, *node.args.args]
    defaults = node.args.defaults
    offset = len(positional) - len(defaults)
    for index, arg in enumerate(positional):
        default = defaults[index - offset] if index >= offset else None
        yield arg, default
    yield from zip(node.args.kwonlyargs, node.args.kw_defaults, strict=False)


def _reads_parameter(node: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """True when the body of *node* actually reads the parameter *name*.

    An opt-out that nothing consults is not a decision about global rows, it
    is a way to turn the guard off in one line. Passing the value on
    (``inner(include_global=include_global)``) counts as a read: the value
    leaves this function, and what the callee does with it is not visible
    from here.

    That is also where the chain stops, and it is worth saying instead of
    promising: a *public* callee that drops the parameter is caught when its
    own signature is read by the same rule, but the rule skips every
    ``_``-prefixed function, so handing the flag to a private
    ``_load_rows(db, item_id, include_global)`` that ignores it reads as a
    live opt-out here and nothing downstream ever looks.
    """
    for statement in node.body:
        for sub in ast.walk(statement):
            if (
                isinstance(sub, ast.Name)
                and sub.id == name
                and isinstance(sub.ctx, ast.Load)
            ):
                return True
    return False


def _has_live_opt_out(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the function declares an opt-out parameter *and* uses it."""
    return any(
        arg.arg in _OPT_OUT_PARAM_NAMES and _reads_parameter(node, arg.arg)
        for arg, _default in _iter_args_with_defaults(node)
    )


def _check_public_api_optional_org(public_api_dir: Path) -> list[str]:
    """Emit ``::error`` for optional ``organization_id=None`` in public_api."""
    errors: list[str] = []
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
            for arg, default in _iter_args_with_defaults(node):
                if arg.arg != 'organization_id' or arg.annotation is None:
                    continue
                if 'None' not in ast.unparse(arg.annotation):
                    continue
                if not (isinstance(default, ast.Constant) and default.value is None):
                    continue
                rel = _rel(py_file)
                errors.append(
                    f'::error file={rel},line={arg.lineno},'
                    f'title=Architecture: optional organization_id in public_api::'
                    f'{node.name}() declares `organization_id: ... | None = None` — '
                    f'an omitted org disables the tenant filter (cross-org reads). '
                    f'Make the org required; use an explicit '
                    f'`include_global: bool = False` parameter for global/system rows.'
                )
    return errors


#: ``_for_user`` marks a method scoped to the caller's own user id. It sits
#: before the ``_async`` suffix in practice (``list_for_user_async``), so match
#: the segment rather than the tail of the name.
_OPT_OUT_NAME_MARKER = '_for_user'


def _takes_identifier(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the function is addressed by some row identifier.

    ``*_id`` / ``*_ids`` covers the shapes that matter: a method reachable by
    an id alone is exactly the one whose isolation depends on the caller
    passing an id from its own organization (confused deputy). ``email``
    counts too — it addresses a single user row and is far easier to guess
    than a UUID, which is what makes cross-org lookup by email worse, not
    milder.
    """
    for arg, _default in _iter_args_with_defaults(node):
        name = arg.arg
        if name in _ORG_PARAM_NAMES:
            continue
        if name == 'email' or name.endswith(('_id', '_ids')):
            return True
    return False


def _iter_cross_module_api_files(
    public_api_dir: Path, modules_dir: Path | None
) -> Iterator[Path]:
    """Every file whose functions one module calls on another's behalf.

    Core's ``public_api`` was the whole list until it turned out not to be:
    a module publishes its own cross-module surface as ``<name>_api.py``, and
    those are read by sibling modules under exactly the same conditions —
    an id arrives from the caller, and whether it belongs to the caller's
    organization is the caller's word. The rule that Core's facade lives by
    now covers them too.
    """
    for py_file in sorted(public_api_dir.rglob('*.py')):
        if py_file.name == '__init__.py':
            continue
        yield py_file

    if modules_dir is None:
        return

    for py_file in sorted(modules_dir.rglob('*_api.py')):
        if _is_test_file(py_file, modules_dir):
            continue
        yield py_file


def _check_public_api_missing_org(
    public_api_dir: Path, baseline: set[str], modules_dir: Path | None = None
) -> list[str]:
    """Flag cross-module API methods that take an id but no organization.

    The sibling rule ``_check_public_api_optional_org`` catches an *optional*
    org; a signature with no org parameter at all slipped through, which is
    how a whole batch of them passed CI unnoticed. Isolation then rests on
    the calling module passing an id from its own organization.

    ``modules_dir`` extends the scan to each module's own cross-module facade
    (``app/modules/**/*_api.py``). Leaving those out was not a decision, and
    it showed: a method fetching a Core row by bare id, with the org check
    living in whichever caller happened to remember, reads as clean.

    Opt-outs, mirroring the convention the optional-org rule already names:
    an explicit ``include_global`` parameter or a ``_for_user`` suffix.
    """
    entries: list[str] = []
    for py_file in _iter_cross_module_api_files(public_api_dir, modules_dir):
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith('_'):
                continue
            if _OPT_OUT_NAME_MARKER in node.name:
                continue
            params = {arg.arg for arg, _ in _iter_args_with_defaults(node)}
            if 'db' not in params:
                continue
            if params & _ORG_PARAM_NAMES or _has_live_opt_out(node):
                continue
            if not _takes_identifier(node):
                continue
            rel = _rel(py_file)
            key = f'{rel}::{node.name}'
            severity = 'notice' if key in baseline else 'error'
            entries.append(
                f'::{severity} file={rel},line={node.lineno},'
                f'title=Architecture: public_api method without organization::'
                f'{node.name}() takes a row identifier and `db` but no '
                f'`organization_id` — isolation then depends on the calling '
                f'module passing an id from its own organization (confused '
                f'deputy). Add the org parameter, or opt out explicitly with '
                f'`include_global: bool = False` or a `_for_user` suffix.'
            )
    return entries


def _collect_public_api_missing_org_keys(
    public_api_dir: Path, modules_dir: Path | None = None
) -> set[str]:
    """Baseline keys for every current hit of :func:`_check_public_api_missing_org`."""
    keys: set[str] = set()
    for entry in _check_public_api_missing_org(public_api_dir, set(), modules_dir):
        file_part = entry.split('file=', 1)[1].split(',', 1)[0]
        name = entry.split('::', 2)[2].split('(', 1)[0]
        keys.add(f'{file_part}::{name}')
    return keys


def _is_alembic_env(py_file: Path, root: Path) -> bool:
    """True for Alembic ``migrations/env.py`` files.

    Migration tooling imports models for metadata/autogenerate but never
    queries tenant data, so the org-filter requirement does not apply
    (carve-out S-2026-08-01).

    Read below ``root``: a checkout under a directory named ``migrations``
    would otherwise hand this carve-out to every ``env.py`` in the tree.
    """
    return py_file.name == 'env.py' and 'migrations' in _rel_parts(py_file, root)


def _check_escape_hatch_org_filter(app_root: Path, baseline: set[str]) -> list[str]:
    """Emit entries for escape-hatch files that never reference organization_id."""
    entries: list[str] = []
    for py_file in sorted(app_root.rglob('*.py')):
        if _is_test_file(py_file, app_root):
            continue
        # The linter itself only holds the marker as a string constant.
        if 'architecture_lint' in _rel_parts(py_file, app_root):
            continue
        if _is_alembic_env(py_file, app_root):
            continue
        try:
            source = py_file.read_text(encoding='utf-8')
        except OSError:
            continue
        if ESCAPE_HATCH_MARKER not in source:
            continue
        if 'organization_id' in source:
            continue
        rel = str(_rel(py_file))
        severity = 'notice' if rel in baseline else 'error'
        entries.append(
            f'::{severity} file={rel},'
            f'title=Architecture: escape hatch without org filter::'
            f'This file declares {ESCAPE_HATCH_MARKER} but never references '
            f'organization_id. Direct DB queries must be org-scoped '
            f'(multi-tenancy guard) — or baseline the file with a justification.'
        )
    return entries


#: SQLAlchemy constructs that start a statement. ``text`` is here because raw
#: SQL is exactly where a tenant filter is easiest to forget and hardest to
#: read back.
#:
#: Recognised by bare name, which is also the limit of this check: the same
#: constructs behind a module attribute (``sa.select(...)``), the unit-of-work
#: get (``db.get(Model, id)``) and the legacy ORM (``.query(...)``) are not
#: read at all. Matching those means matching an attribute name, which turns
#: every ``.get(`` on a dict and every ``.query(`` on any other receiver into
#: a statement. The escape-hatch corpus uses none of the three forms today, so
#: the class they leave open is empty rather than silent -- the check's
#: docstring says the same where a reader of the gate will find it.
_QUERY_STARTERS = frozenset({'select', 'update', 'delete', 'insert', 'text'})

#: Builder methods whose arguments carry the filters. "Is this query
#: org-scoped" is a question about those arguments and nothing else: an
#: organization in the result columns or in the ordering picks no subset of
#: rows, so ``select(Item.organization_id).where(Item.id == item_id)`` reads
#: as a search hit for the word, not as a scope. ``filter_by`` is here for
#: its keywords — ``filter_by(organization_id=...)`` scopes the query as
#: much as the ``where`` spelling does.
#:
#: A join condition is left out on purpose, and not because it narrows
#: nothing: an inner join's ``ON`` clause narrows the paired rows as a
#: ``WHERE`` clause would. It narrows the pairing, though, not the rows of
#: the entity the statement selects — in ``select(Item).join(
#: S, S.organization_id == organization_id)`` every Item still comes back,
#: paired with S's rows of the org. Whether the condition reaches the
#: selected entity is an ownership invariant between the two tables that no
#: shape here can read, and an outer join narrows nothing at all. The
#: statement's own filter clauses are where this codebase writes the tenant,
#: so they are what this check reads; the same condition moved there is
#: accepted with no change of meaning.
_FILTER_METHODS = frozenset({'where', 'filter', 'filter_by'})

#: Calls that take a collection of values. A local fetched for one
#: organization and then passed as that collection is a column comparison in
#: the only clause it can be one -- ``Item.storage_id.in_(storage_ids)``.
_ORG_SET_METHODS = frozenset({'in_', 'notin_', 'any', 'has'})


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _statement_root(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> ast.AST:
    """The outermost node of the builder chain *call* starts.

    ``select(X).join(Y).where(...)`` parses inside-out, so the ``select``
    call alone says nothing about the filters hung off it. Walking up while
    the parent is still receiving this node -- ``.where`` on it, or the call
    of that attribute -- gives the whole statement as one subtree, which is
    what "is this query org-scoped" is a question about.
    """
    node: ast.AST = call
    while True:
        parent = parents.get(node)
        if isinstance(parent, ast.Attribute) and parent.value is node:
            node = parent
            continue
        if isinstance(parent, ast.Call) and parent.func is node:
            node = parent
            continue
        return node


def _names_read(node: ast.AST) -> set[str]:
    return {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}


def _without_conditionals(node: ast.AST) -> Iterator[ast.AST]:
    """Every node under *node*, with conditional expressions skipped whole.

    ``X if flag else Y`` is one expression, and a comparison written in a
    branch is not a filter: neither half of
    ``.where(Item.id == item_id if True else Item.organization_id == org)``
    restricts the rows, and reading the branch as a scope turned the check
    into a search for a word with one extra step.
    """
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        if not isinstance(current, ast.IfExp):
            stack.extend(ast.iter_child_nodes(current))


def _names_read_without_conditionals(node: ast.AST) -> set[str]:
    return {sub.id for sub in _without_conditionals(node) if isinstance(sub, ast.Name)}


def _is_org_reference(node: ast.AST) -> bool:
    """True for a name, attribute or keyword carrying an organization."""
    if isinstance(node, ast.Attribute):
        return node.attr in _ORG_PARAM_NAMES
    if isinstance(node, ast.Name):
        return node.id in _ORG_PARAM_NAMES
    if isinstance(node, ast.keyword):
        return node.arg in _ORG_PARAM_NAMES
    return False


def _mentions_org(node: ast.AST) -> bool:
    """True when *node* names an organization anywhere inside it."""
    return any(_is_org_reference(sub) for sub in ast.walk(node))


def _mentions_org_without_conditionals(node: ast.AST) -> bool:
    """True when *node* names an organization outside every conditional."""
    return any(_is_org_reference(sub) for sub in _without_conditionals(node))


def _enclosing_scope(
    node: ast.AST, parents: dict[ast.AST, ast.AST], tree: ast.AST
) -> ast.AST:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return tree


def _org_derived_names(scope: ast.AST) -> set[str]:
    """Local names carrying something derived from the organization.

    A filter list is routinely built next door and splatted in
    (``conditions = _window_conditions(org_id, ...)`` then
    ``.where(*conditions)``), and a query restricted to ids that were
    themselves fetched for one organization is scoped too. Both are followed
    here, transitively, to a fixed point.

    Deliberately not followed: names bound by ``for`` targets or tuple
    unpacking. A value that reached a loop variable from an org-scoped query
    is an argument about the code around it, not about the query -- and it
    is the argument that stops holding the first time somebody moves the
    loop. Those stay visible.
    """
    derived: set[str] = set(_ORG_PARAM_NAMES)
    assignments: list[tuple[str, ast.expr]] = []
    for sub in ast.walk(scope):
        if (
            isinstance(sub, ast.Assign)
            and len(sub.targets) == 1
            and isinstance(sub.targets[0], ast.Name)
        ):
            assignments.append((sub.targets[0].id, sub.value))
        elif (
            isinstance(sub, ast.AnnAssign)
            and isinstance(sub.target, ast.Name)
            and sub.value is not None
        ):
            assignments.append((sub.target.id, sub.value))

    changed = True
    while changed:
        changed = False
        for name, value in assignments:
            if name in derived:
                continue
            if _mentions_org(value) or (_names_read(value) & derived):
                derived.add(name)
                changed = True
    return derived


def _filter_arguments(root: ast.AST) -> Iterator[ast.AST]:
    """Every argument of the filter calls in *root*.

    ``.where(...)`` and ``.filter(...)`` carry theirs positionally,
    ``.filter_by(...)`` in keywords — all three restrict the rows, so all
    three are read. The keyword node is yielded whole rather than its value:
    the name on the left of the equality is half of the filter
    (``filter_by(organization_id=...)``), and it is what
    :func:`_is_org_reference` reads.
    """
    for node in ast.walk(root):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute) and node.func.attr in _FILTER_METHODS
        ):
            continue
        yield from node.args
        yield from node.keywords


def _derived_value_restricts(node: ast.AST, derived: set[str]) -> bool:
    """True when *node* is an org-derived local in a position that filters rows.

    Two positions qualify, and both are how this codebase writes a scoped
    query: a clause list built next door and splatted in
    (``conditions = _window_conditions(org_id, ...)``, then
    ``.where(*conditions)``), and ids fetched for one organization and used as
    the collection of a set comparison
    (``Item.storage_id.in_(storage_ids)``). A derived local anywhere else does
    not, and it is the difference between a filter and a coincidence:
    ``label = str(organization_id)`` followed by ``Item.name == label``
    compares names. The comparison that does name the organization on one side
    (``Item.organization_id == label``) needs no branch here -- that mention
    is what :func:`_mentions_org_without_conditionals` reads.
    """
    if isinstance(node, ast.Starred):
        return bool(_names_read_without_conditionals(node) & derived)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr in _ORG_SET_METHODS and bool(
            _names_read_without_conditionals(node) & derived
        )
    return False


def _filter_argument_restricts(node: ast.AST, derived: set[str]) -> bool:
    """True when one ``where`` / ``filter`` / ``filter_by`` argument narrows
    rows to an org."""
    if _mentions_org_without_conditionals(node):
        return True
    return any(
        _derived_value_restricts(sub, derived) for sub in _without_conditionals(node)
    )


def _query_restricts_to_org(root: ast.AST, derived: set[str]) -> bool:
    """True when a filter clause of the statement *root* names the organization."""
    return any(
        _filter_argument_restricts(argument, derived)
        for argument in _filter_arguments(root)
    )


def _unscoped_queries(tree: ast.AST) -> Iterator[tuple[str, int, str]]:
    """Yield ``(function name, line, starter)`` per query with no org filter."""
    parents = _parent_map(tree)
    derived_by_scope: dict[ast.AST, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id in _QUERY_STARTERS):
            continue
        root = _statement_root(node, parents)
        scope = _enclosing_scope(node, parents, tree)
        if scope not in derived_by_scope:
            derived_by_scope[scope] = _org_derived_names(scope)
        if _query_restricts_to_org(root, derived_by_scope[scope]):
            continue
        yield getattr(scope, 'name', '<module>'), node.lineno, node.func.id


def _check_escape_hatch_query_scoping(app_root: Path, baseline: set[str]) -> list[str]:
    """Emit entries for individual escape-hatch queries with no org filter.

    The sibling file-level check asks whether ``organization_id`` appears
    anywhere in the file, which a docstring satisfies. This one reads the
    statement and asks the narrower question: does a clause handed to
    ``where()`` / ``filter()`` / ``filter_by()`` name an organization,
    directly or through a local built from one? An organization anywhere
    else in the statement -- the result columns, the ordering, a conditional
    expression -- selects no subset of rows, so ``select(Item).where(Item.id
    == item_id).order_by(Item.organization_id)`` is reported even when the
    word occurs ten lines above in a different function. A join condition is
    the one other place an organization can narrow rows; why it is not read
    as the scope is stated at ``_FILTER_METHODS``.

    Deliberately out of scope, named here so it is read as a decision rather
    than found as a gap: ``sa.select(...)`` (the same construct behind a
    module attribute), ``db.get(Model, id)`` and the legacy ORM
    ``.query(...)``. Those are matched by attribute name, which would turn
    every ``.get(`` on a dict and every ``.query(`` on any other receiver into
    a statement; the escape-hatch corpus uses none of the three forms today,
    so the class they leave open is empty. ``_QUERY_STARTERS`` says the same.
    """
    entries: list[str] = []
    for py_file in sorted(app_root.rglob('*.py')):
        if _is_test_file(py_file, app_root):
            continue
        if 'architecture_lint' in _rel_parts(py_file, app_root):
            continue
        if _is_alembic_env(py_file, app_root):
            continue
        try:
            source = py_file.read_text(encoding='utf-8')
        except OSError:
            continue
        if ESCAPE_HATCH_MARKER not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        rel = str(_rel(py_file))
        for func_name, lineno, starter in _unscoped_queries(tree):
            key = f'{rel}::{func_name}'
            severity = 'notice' if key in baseline else 'error'
            entries.append(
                f'::{severity} file={rel},line={lineno},'
                f'title=Architecture: escape-hatch query without org filter::'
                f'{func_name}() builds a {starter}() whose filter clauses '
                f'never name an organization — neither directly nor through a '
                f'local derived from one. Direct DB access must be org-scoped '
                f'(multi-tenancy guard). Scope the filter, or baseline '
                f'`{key}` with an owner, an expiry and a reason.'
            )
    return entries


def _declares_only(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True for a body that only states a signature: ``...``, ``pass``, a
    docstring, ``raise NotImplementedError``.

    Protocols, abstract methods and stubs promise the parameter to an
    implementation; whether it is read is the implementation's question.
    """
    for statement in node.body:
        if isinstance(statement, ast.Pass):
            continue
        if isinstance(statement, ast.Expr) and isinstance(
            statement.value, ast.Constant
        ):
            continue
        if isinstance(statement, ast.Raise):
            exc = statement.exc
            target = exc.func if isinstance(exc, ast.Call) else exc
            if isinstance(target, ast.Name) and target.id == 'NotImplementedError':
                continue
        return False
    return True


def _functions_with_qualname(
    tree: ast.AST,
) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Every function in *tree*, named ``Class.method`` inside a class."""

    def walk(
        node: ast.AST, prefix: str
    ) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from walk(child, f'{prefix}{child.name}.')
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                yield f'{prefix}{child.name}', child
                yield from walk(child, f'{prefix}{child.name}.')
            else:
                yield from walk(child, prefix)

    yield from walk(tree, '')


def _check_unread_org_parameter(app_root: Path, baseline: set[str]) -> list[str]:
    """Functions that take ``organization_id``/``org_id`` and never read it.

    A parameter naming the tenant that the body then ignores is the shape a
    forgotten filter leaves: of four omissions planted on purpose, two had
    it, and every other gate stayed green over both. Handing the value on
    counts as reading it (see ``_reads_parameter``), which is also this
    check's edge: a helper that receives the organization and drops it is
    caught at the helper's own signature, and one that receives it inside
    another object is not caught at all.

    Keys are ``app/<path>.py::Qualname``; a baselined key is a notice.
    """
    entries: list[str] = []
    for py_file in sorted(app_root.rglob('*.py')):
        if _is_test_file(py_file, app_root):
            continue
        parts = _rel_parts(py_file, app_root)
        if 'migrations' in parts or 'architecture_lint' in parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (OSError, SyntaxError):
            continue
        rel = '/'.join((app_root.name, *parts))
        for qualname, node in _functions_with_qualname(tree):
            if _declares_only(node):
                continue
            for arg, _default in _iter_args_with_defaults(node):
                if arg.arg not in _ORG_PARAM_NAMES:
                    continue
                if _reads_parameter(node, arg.arg):
                    continue
                key = f'{rel}::{qualname}'
                severity = 'notice' if key in baseline else 'error'
                entries.append(
                    f'::{severity} file={rel},line={node.lineno},'
                    f'title=Architecture: organization taken and not read::'
                    f'{key} takes `{arg.arg}` and never reads it — the shape a '
                    f'forgotten tenant filter leaves. Filter by it, hand it on, '
                    f'or drop the parameter; a deliberate exception goes in '
                    f'app/core/unread_org_parameter_baseline.txt with a reason.'
                )
    return entries
