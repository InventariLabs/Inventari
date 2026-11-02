"""Module-boundary checks: cross-module imports + Depends(get_db) in async def.

These two checks live together because they both guard the *module boundary*
contract — cross-module imports must use the public API, and async endpoints
must use ``get_async_db``. Splitting them would scatter closely-related
checks across two files.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Callable
from pathlib import Path

from app.core.module_safety_analysis import on_module_import_surface

from ._baselines import _load_get_db_baseline
from ._constants import (
    CROSS_MODULE_WHITELIST_MODULES,
    CROSS_MODULE_WHITELIST_SUFFIXES,
    _is_test_file,
    _rel,
    _rel_parts,
)


def _is_cross_module_import_whitelisted(module_path: str) -> bool:
    """Check if a cross-module import targets an approved public API symbol.

    Approved public API patterns (per AGENTS.md Cross-Module API Contracts):
    - `<other_module>_api` — the single public API entry point
    - `<other_module>.exceptions` — exception types for error handling
    - `<other_module>.schemas` — DTOs and request/response schemas

    Each of those is one module deep, and the API one is named after the
    module it belongs to. Both conditions are checked. Matching the `_api`
    suffix alone honoured any file that ended in it, wherever it sat and
    whatever it was named: `app.modules.maker.secret_internal_api` passed,
    and so did a file inside maker named after somebody else's module. The
    contract names one door per module, not a naming convention that opens
    every file adopting it.

    Only applies to paths under `app.modules.*` — Core paths (e.g.
    `app.core.public_api`) are out of scope for cross-module checks.
    """
    parts = module_path.split('.')
    if len(parts) != 4:
        return False
    if parts[0] != 'app' or parts[1] != 'modules':
        return False
    target, leaf = parts[2], parts[3]
    return (
        leaf in {f'{target}{suffix}' for suffix in CROSS_MODULE_WHITELIST_SUFFIXES}
        or leaf in CROSS_MODULE_WHITELIST_MODULES
    )


def _imported_modules(
    node: ast.Import | ast.ImportFrom,
    package_parts: tuple[str, ...],
    modules_prefix: tuple[str, ...] = ('app', 'modules'),
    *,
    bound_submodule: Callable[[str, str], bool] | None = None,
) -> list[str]:
    """Every absolute module path an import statement names, resolved.

    Both node types, because Python has two ways to write the same reach:
    ``from app.modules.maker.bom_tree import X`` and
    ``import app.modules.maker.bom_tree``. This check read only the first
    for as long as it existed, which made the second a way through a gate
    that was otherwise thorough.

    One rule for both writings, absolute and relative: the dots and the
    module the statement names are joined into a single address first
    (relative imports climb against *package_parts* — the absolute package
    of the file the import sits in — one dot is the file's own package,
    each further dot one level up, the way ``importlib.util.resolve_name``
    would), and only the joined address is judged. Resolving first is what
    keeps the two spellings of the same statement from taking two code
    paths: ``from ...modules import warehouse`` and ``from app.modules
    import documents`` join to the same address, land exactly on the
    modules package (*modules_prefix*), and there the bound names are the
    reach — each names a child module nothing vouches for, so each stands
    on its own. Any other address is the reach itself, bound names
    included. What no import statement can show — ``importlib``,
    ``__import__``, ``getattr`` over ``sys.modules`` — is out of an AST
    gate's reach by definition and stays with runtime supervision, the
    same place a bare ``import app.modules`` was left.

    *bound_submodule* answers, for a resolved package and a bound name,
    whether that name is a module or package inside it. When given,
    ``from app import config`` and ``from app.core import db_facade``
    resolve to the child module they bind rather than stopping at the
    parent package: otherwise a baseline entry for ``app.core`` covers every
    helper the package will ever hold. A name that is not a child module is
    a symbol from the package's ``__init__``, and the package itself stays
    the address.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]

    prefix = '.'.join(modules_prefix)

    def address(join_to: list[str]) -> list[str]:
        joined = '.'.join(join_to)
        if joined == prefix:
            # The statement binds the modules package itself: each bound
            # name is another module, known only by the name it binds.
            return [f'{prefix}.{alias.name}' for alias in node.names]
        if (
            isinstance(node, ast.ImportFrom)
            and len(join_to) == len(modules_prefix) + 1
            and '.'.join(join_to[: len(modules_prefix)]) == prefix
        ):
            # The statement binds another module's package: each bound
            # name is a file inside it — a sanctioned door or a private
            # file — and each is its own address, judged on its own. A
            # door and a private file bound by one statement are judged
            # separately, never covered by the door's name.
            return [f'{joined}.{alias.name}' for alias in node.names]
        if bound_submodule is not None:
            children = [
                f'{joined}.{alias.name}'
                for alias in node.names
                if bound_submodule(joined, alias.name)
            ]
            if len(children) == len(node.names):
                return children
            return [joined, *children] if children else [joined]
        return [joined]

    level = node.level or 0
    if level == 0:
        if node.module:
            return address(node.module.split('.'))
        return [f'{prefix}.{alias.name}' for alias in node.names]

    up = level - 1
    if up >= len(package_parts):
        return []
    base = list(package_parts[: len(package_parts) - up])
    if node.module:
        return address([*base, *node.module.split('.')])
    # ``from . import x`` / ``from .. import x`` — the base package plus
    # each bound name.
    return ['.'.join([*base, alias.name]) for alias in node.names]


def _check_cross_module_imports(modules_root: Path) -> list[str]:
    """Flag imports from modules/other_module/ (must use public API).

    A statement is judged by everything it can name, name by name. Most
    statements name one address, but the package form — ``from
    app.modules.other import other_api, services`` — resolves to another
    module's package while binding its files: each bound name becomes its
    own address, so a sanctioned door passes and a private file bound by
    the same statement is still reported. What an AST gate cannot see at
    all — ``importlib.import_module``, ``__import__``, ``getattr`` over
    ``sys.modules`` — is out of scope here by nature and rests on runtime
    supervision.

    What the walk cannot reach is a different matter and is named rather
    than skipped: ``Path.rglob`` stops at a symlinked directory and
    ``ast.parse`` gives up on a file that is not valid Python, so both
    used to end in a silent ``continue`` — and "Architecture lint passed"
    over a tree nobody read is the report a certification review is run
    on. The gaps come back as ``::warning`` entries, the recipe ``module
    validate`` already uses: the tool says what it did not read, the exit
    code stays with the findings, and whether what sits behind the link
    belongs to this module is the reviewer's call.
    """
    errors: list[str] = []
    unread: list[str] = []
    modules_prefix: tuple[str, ...] = ('app', modules_root.name)
    for module_dir in sorted(modules_root.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith('_'):
            continue
        for linked in sorted(module_dir.rglob('*')):
            # Not `is_dir()`: a link whose target this process cannot see
            # (a host path inside a container, a package installed
            # elsewhere) resolves to nothing and would drop out of the
            # report exactly where the report matters most.
            if linked.is_symlink() and not linked.is_file():
                target = os.readlink(linked)
                kind = 'symlinked directory' if linked.is_dir() else 'broken symlink'
                unread.append(
                    f'::warning file={_rel(linked)},title=Architecture: tree not read::'
                    f'{linked.relative_to(modules_root)} was not read ({kind} -> '
                    f'{target}). The scan does not follow it; whether what sits behind '
                    f'it belongs to this module is a review call.'
                )
        for py_file in sorted(module_dir.rglob('*.py')):
            if _is_test_file(py_file, modules_root) or '__pycache__' in _rel_parts(
                py_file, modules_root
            ):
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError) as exc:
                unread.append(
                    f'::warning file={_rel(py_file)},title=Architecture: file not read::'
                    f'{py_file.relative_to(modules_root)} was not read '
                    f'({type(exc).__name__}). A file the parser cannot read is a file '
                    f'this gate did not judge.'
                )
                continue
            rel = py_file.relative_to(modules_root)
            package_parts = (*modules_prefix, *rel.parts[:-1])
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                paths = _imported_modules(node, package_parts, modules_prefix)
                for module_path in paths:
                    if not _is_cross_module_reach(
                        module_path, module_dir.name, modules_prefix
                    ):
                        continue
                    if _is_cross_module_import_whitelisted(module_path):
                        continue
                    parts = module_path.split('.')
                    found = _rel(py_file)
                    errors.append(
                        f'::error file={found},line={node.lineno},title=Architecture: cross-module import::'
                        f"Import of '{module_path}' from {module_dir.name} module. "
                        f"Use the target module's public API instead "
                        f'(app.modules.{parts[2]}.{parts[2]}_api).'
                    )
    return errors + unread


def _is_cross_module_reach(
    module_path: str,
    importer: str,
    modules_prefix: tuple[str, ...] = ('app', 'modules'),
) -> bool:
    """True when *module_path* names a package or file of another module.

    The package name is the one the checked root actually has, not an
    assumed one: a root mounted as ``plugins`` resolves and reports as
    ``app.plugins.*``.
    """
    parts = module_path.split('.')
    depth = len(modules_prefix)
    return (
        len(parts) > depth
        and parts[:depth] == list(modules_prefix)
        and parts[depth] != importer
    )


def _is_child_module(app_root: Path, package: str, name: str) -> bool:
    """Whether *name* is a module or package inside *package* on disk.

    ``from app import config`` and ``import app.config`` are one reach written
    two ways, and ``from app.core import db_facade`` reaches
    ``app.core.db_facade`` rather than the whole ``app.core`` package. The tree
    decides, because only the tree knows the difference between a bound
    submodule and a symbol a package exports from its ``__init__``.
    """
    if package != 'app' and not package.startswith('app.'):
        return False
    directory = app_root.joinpath(*package.split('.')[1:])
    return (directory / f'{name}.py').is_file() or (
        directory / name / '__init__.py'
    ).is_file()


def collect_module_surface_imports(
    modules_root: Path,
) -> dict[str, dict[str, tuple[Path, int]]]:
    """Every import a shipped module makes outside the declared module surface.

    Returns ``{module: {import path: (first file, line)}}``. The surface is
    the one the install-time scan enforces on an installed module
    (``app.core.contracts``, ``app.core.public_api``, ``app.core.module_sdk``,
    plus the module's own package), so the two gates cannot drift: the same
    ``on_module_import_surface`` answers both.

    Everything under ``app.`` outside that surface is counted, including the
    top package itself and *another* module's permitted public-API door: a
    sibling API is an exception to the same surface, so it is frozen here with
    the same reason and growth gate. A sibling path that is not one of those
    doors is left to ``_check_cross_module_imports``, which already refuses it
    — counting it here too would put one refusal on two lists. Imports outside
    ``app.`` (``fastapi``, ``sqlalchemy``, …) are the capability map's
    business.

    Relative imports are resolved before they are judged (``from ...core.deps
    import x`` in a module file is ``app.core.deps``), because the two
    spellings of one reach must not take two code paths. A file that cannot be
    parsed is skipped here — the cross-module walk names it as "not read", and
    a second silent answer to the same question is how one of the two gates
    ends up lying.
    """
    modules_prefix: tuple[str, ...] = ('app', modules_root.name)
    modules_package = '.'.join(modules_prefix)
    app_root = modules_root.parent
    found: dict[str, dict[str, tuple[Path, int]]] = {}

    for module_dir in sorted(modules_root.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith('_'):
            continue
        # Every module gets an entry, even a clean one: the caller uses
        # "module absent" for "the directory is gone", and a module that paid
        # its whole list should read as an empty block, not a missing one.
        module_entries = found.setdefault(module_dir.name, {})
        for py_file in sorted(module_dir.rglob('*.py')):
            if _is_test_file(py_file, modules_root) or '__pycache__' in _rel_parts(
                py_file, modules_root
            ):
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = py_file.relative_to(modules_root)
            package_parts = (*modules_prefix, *rel.parts[:-1])
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for module_path in _imported_modules(
                    node,
                    package_parts,
                    modules_prefix,
                    bound_submodule=lambda base, name: _is_child_module(
                        app_root, base, name
                    ),
                ):
                    if module_path != 'app' and not module_path.startswith('app.'):
                        continue
                    if on_module_import_surface(module_path, module_dir.name):
                        continue
                    if module_path.startswith(
                        modules_package + '.'
                    ) and not _is_cross_module_import_whitelisted(module_path):
                        # Another module's file that is not one of its public
                        # doors: the cross-module check already refuses it.
                        continue
                    module_entries.setdefault(module_path, (py_file, node.lineno))
    return found


def _check_module_import_surface(
    modules_root: Path, baseline: dict[str, set[str]]
) -> list[str]:
    """App imports a shipped module makes outside the SDK, frozen by module.

    The install-time scan lets a module installed from outside reach only
    ``app.core.contracts``, ``app.core.public_api`` and
    ``app.core.module_sdk``; the modules this repository ships predate that
    door, so their current reaches are recorded in
    ``module_import_surface_baseline.txt`` and this check holds them to it.
    A new path, a module that grew a line, or an entry whose import was fixed
    all fail: the list only ever shrinks, and the way to shrink it is to move
    the import to the SDK — an additive change the SDK snapshot covers. A
    sibling module's public API is an exception of the same kind: it is legal
    to call, but a new dependency still needs a written decision.
    """
    live = collect_module_surface_imports(modules_root)
    errors: list[str] = []

    for module in sorted(live):
        allowed = baseline.get(module, set())
        for path in sorted(set(live[module]) - allowed):
            py_file, lineno = live[module][path]
            if path.startswith('app.modules.'):
                remedy = (
                    f'{module} imports {path} from another module. A module '
                    f'takes another module through its public API '
                    f'(app.modules.<other>.<other>_api, .exceptions or '
                    f'.schemas), and a new dependency still needs a written '
                    f'decision: add it to module_import_surface_baseline.txt '
                    f'with the reason it belongs there.'
                )
            else:
                remedy = (
                    f'{module} imports {path}. A module reaches Core through '
                    f'app.core.module_sdk (DTOs and the model base through '
                    f'app.core.contracts, data through app.core.public_api). If the '
                    f'SDK does not export the name, add it there — an additive change '
                    f'the SDK snapshot covers — and import it from the module. Do not '
                    f'add the path to module_import_surface_baseline.txt.'
                )
            errors.append(
                f'::error file={_rel(py_file)},line={lineno},'
                f'title=Architecture: import outside the module SDK::{remedy}'
            )

    for module in sorted(baseline):
        if module not in live:
            errors.append(
                f'::error file=app/core/module_import_surface_baseline.txt,'
                f'title=Architecture: stale module surface entry::'
                f"'{module}' matches no module in app/modules any more. Remove "
                f'its block, then run `--write-baseline-sizes`.'
            )
            continue
        for path in sorted(baseline[module] - set(live[module])):
            errors.append(
                f'::error file=app/core/module_import_surface_baseline.txt,'
                f'title=Architecture: stale module surface entry::'
                f"'{module} -> {path}' matches no import any more. The code it "
                f'described moved to the SDK or was deleted — remove the line, '
                f'then run `--write-baseline-sizes`.'
            )
    return errors


def _check_get_db_in_async_def(api_root: Path) -> list[str]:
    """Detect Depends(get_db) inside async def — must use get_async_db."""
    baseline = _load_get_db_baseline()
    errors = []
    for py_file in api_root.rglob('*.py'):
        if _is_test_file(py_file, api_root):
            continue

        source = py_file.read_text(encoding='utf-8')
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and getattr(sub.func, 'id', '') == 'Depends'
                ):
                    for arg in sub.args:
                        if getattr(arg, 'id', '') == 'get_db':
                            rel = py_file.relative_to(Path.cwd())
                            key = f'{rel}::{node.name}'
                            if key in baseline:
                                errors.append(
                                    f'::notice file={rel},line={sub.lineno},title=Architecture: get_db in async def (baseline)::'
                                    f"'Depends(get_db)' used in async def '{node.name}'. "
                                    f'Baselined — needs deeper service-layer refactoring. '
                                    f'See the Sync/Async Rule in backend/AGENTS.md.'
                                )
                            else:
                                errors.append(
                                    f'::error file={rel},line={sub.lineno},title=Architecture: get_db in async def::'
                                    f"'Depends(get_db)' used in async def '{node.name}'. "
                                    f"Use Depends(get_async_db, scope='function') with AsyncSession instead."
                                )
                            break
    return errors
