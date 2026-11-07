from __future__ import annotations

import ast
import sys
from pathlib import Path

from ._baselines import _load_baseline
from ._constants import (
    API_FORBIDDEN_IMPORT_PREFIXES,
    API_IMPORTS_BASELINE_FILE,
    API_LAYER_FORBIDDEN_WRITES,
    API_ROOT,
    DEFAULT_BASELINE_FILE,
    ESCAPE_HATCH_MARKER,
    FORBIDDEN_PREFIXES,
    FORBIDDEN_WRITES,
    MODULES_ROOT,
    REASON_MIN_WORDS,
    REASON_PATTERN,
    Violation,
    _is_alembic_env,
    _is_model_file,
    _is_test_file,
    _rel,
)


def _collect_type_checking_line_ranges(tree: ast.AST) -> set[int]:
    """Return line numbers that are inside a `if TYPE_CHECKING:` block."""
    ranges: set[int] = set()

    def _is_type_checking_test(test: ast.AST) -> bool:
        return (isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING') or (
            isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING'
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            for child in ast.walk(node):
                if hasattr(child, 'lineno'):
                    ranges.add(child.lineno)
    return ranges


#: The ORM modules the contracts, public-API and API layers may never import.
_ORM_IMPORT_PREFIXES = ('app.models', 'app.database')


def _iter_forbidden_imports(
    tree: ast.AST, prefixes: tuple[str, ...]
) -> list[tuple[int, str]]:
    """Every forbidden import in *tree*, as ``(line, import path)``.

    One walk serves the four scans in this module. ``ImportFrom`` names one
    module; ``Import`` binds a list, and every alias is checked — the layer
    scans used to read only the first one, so ``import os, app.models.item``
    slipped past them. An import under ``if TYPE_CHECKING:`` is a hint, not
    a dependency, and stays out.
    """
    type_checking_lines = _collect_type_checking_line_ranges(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.lineno in type_checking_lines:
                continue
            module = node.module or ''
            if module.startswith(prefixes):
                found.append((node.lineno, module))
        elif isinstance(node, ast.Import):
            if node.lineno in type_checking_lines:
                continue
            found.extend(
                (node.lineno, alias.name)
                for alias in node.names
                if alias.name.startswith(prefixes)
            )
    return found


def _check_escape_hatch(file_path: Path, source: str) -> str | None:
    """
    If the file declares the escape hatch (L2), validate it and return the reason.
    Returns None if no escape hatch is present.
    Exits with code 1 on invalid declarations or CQRS violations.
    """
    if ESCAPE_HATCH_MARKER not in source:
        return None

    match = REASON_PATTERN.search(source)
    if not match:
        print(
            f'::error file={_rel(file_path)},title=Architecture: missing reason::'
            f"Used '{ESCAPE_HATCH_MARKER}' without a '# reason: ...' comment "
            f'({REASON_MIN_WORDS}+ words required).'
        )
        sys.exit(1)

    reason = match.group(1).strip()
    if len(reason.split()) < REASON_MIN_WORDS:
        print(
            f'::error file={_rel(file_path)},title=Architecture: reason too short::'
            f"Reason '{reason}' has fewer than {REASON_MIN_WORDS} words. "
            f'Write a real justification for bypassing CoreAPI.'
        )
        sys.exit(1)

    for lineno, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        for call in FORBIDDEN_WRITES:
            if call in stripped:
                # module_writes marker allows writes to module-local tables
                if '# module_writes:' in source:
                    continue
                print(
                    f'::error file={_rel(file_path)},line={lineno},title=Architecture: write in read-only file::'
                    f"'{call}' found in a file with {ESCAPE_HATCH_MARKER}. "
                    f'Direct DB writes to Core tables are forbidden — use CoreAPI instead.'
                )
                sys.exit(1)

    return reason


def _check_api_layer_violations(api_root: Path) -> list[str]:
    errors = []
    for py_file in api_root.rglob('*.py'):
        if _is_test_file(py_file, api_root):
            continue

        source = py_file.read_text(encoding='utf-8')
        for lineno, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            for call in API_LAYER_FORBIDDEN_WRITES:
                if call in stripped:
                    rel = py_file.relative_to(Path.cwd())
                    errors.append(
                        f'::error file={rel},line={lineno},title=Architecture: Direct DB write in API::'
                        f"Direct DB write '{call}' found in API layer. "
                        f'Must use a Service to ensure Interceptors and EventBus are triggered.'
                    )
    return errors


def _collect_api_import_violations(api_root: Path) -> list[Violation]:
    """Detect `from app.models` and `from app.database` imports in app/api/**."""
    violations: list[Violation] = []
    for py_file in api_root.rglob('*.py'):
        if _is_test_file(py_file, api_root):
            continue
        try:
            source = py_file.read_text(encoding='utf-8')
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        violations.extend(
            Violation(file_path=py_file, line=line, import_path=path)
            for line, path in _iter_forbidden_imports(
                tree, API_FORBIDDEN_IMPORT_PREFIXES
            )
        )
    return violations


def find_api_layer_import_violations(
    api_root: Path | None = None,
    baseline_file: Path | None = API_IMPORTS_BASELINE_FILE,
) -> tuple[list[Violation], list[Violation]]:
    """
    Returns (new_violations, baseline_violations):
    - new_violations: forbidden imports not in baseline (will become ::error)
    - baseline_violations: forbidden imports present in baseline (will become ::notice)
    """
    root = api_root or API_ROOT
    baseline = _load_baseline(baseline_file)
    all_violations = _collect_api_import_violations(root)
    new: list[Violation] = []
    in_baseline: list[Violation] = []
    for v in all_violations:
        if v.baseline_key(root.parent) in baseline:
            in_baseline.append(v)
        else:
            new.append(v)
    return (
        sorted(new, key=lambda v: (str(v.file_path), v.line, v.import_path)),
        sorted(in_baseline, key=lambda v: (str(v.file_path), v.line, v.import_path)),
    )


def _check_layer_imports(
    root: Path,
    *,
    title: str,
    where: str,
    advice: str,
) -> list[str]:
    """Flag ORM imports in one layer whose purity the gate certifies.

    Contracts, the public API and the API layer answer the same question —
    does this file couple the layer to the ORM — and differed only in the
    sentence a finding speaks. One scan, one policy: a file that cannot be
    read or parsed is skipped here, and the module scan is the one that
    names the gaps it walked past.
    """
    errors: list[str] = []
    for py_file in root.rglob('*.py'):
        if py_file.name == '__init__.py' or _is_test_file(py_file, root):
            continue
        try:
            source = py_file.read_text(encoding='utf-8')
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rel = py_file.relative_to(Path.cwd())
        errors.extend(
            f'::error file={rel},line={line},title=Architecture: {title}::'
            f"Direct import of '{path}' found in {where}. {advice}"
            for line, path in _iter_forbidden_imports(tree, _ORM_IMPORT_PREFIXES)
        )
    return errors


def _check_public_api_violations(public_api_root: Path) -> list[str]:
    return _check_layer_imports(
        public_api_root,
        title='Model import in Public API',
        where='Public API',
        advice='Must use a Service to ensure abstraction and proper logic execution.',
    )


def _check_contracts_violations(contracts_root: Path) -> list[str]:
    """Scan contracts/ layer for ORM imports (app.models, app.database).

    The contracts layer must stay free of the core's ORM: its DTOs are pure
    Pydantic models, and the one SQLAlchemy name the layer carries is the
    module model base (``module_models.ModuleModelBase``) — a declarative base
    of the module's own, never the core's, so module tables stay out of the
    core metadata. Mirrors _check_public_api_violations.
    """
    return _check_layer_imports(
        contracts_root,
        title='Model import in Contracts',
        where='contracts layer',
        advice='Define DTOs/enums here and re-export from app.models instead.',
    )


def _collect_import_violations(file_path: Path, tree: ast.AST) -> list[Violation]:
    """Forbidden imports in one already-parsed module."""
    return [
        Violation(file_path=file_path, line=line, import_path=import_path)
        for line, import_path in _iter_forbidden_imports(tree, FORBIDDEN_PREFIXES)
    ]


def collect_module_import_violations(modules_root: Path) -> list[Violation]:
    """Forbidden imports across a module tree, unreadable files skipped.

    The ``--write-baseline`` walk. ``find_module_boundary_violations``
    needs each file's source for the escape-hatch check, so it reads and
    parses its own loop; both answer the same "cannot be read or parsed"
    the same way — skip, and let the module scan name the gap.
    """
    violations: list[Violation] = []
    for py_file in modules_root.rglob('*.py'):
        if (
            _is_test_file(py_file, modules_root)
            or _is_model_file(py_file)
            or _is_alembic_env(py_file, modules_root)
        ):
            continue
        try:
            source = py_file.read_text(encoding='utf-8')
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        violations.extend(_collect_import_violations(py_file, tree))
    return violations


def find_module_boundary_violations(
    modules_root: Path | None = None,
    baseline_file: Path | None = DEFAULT_BASELINE_FILE,
) -> tuple[list[Violation], list[tuple[Path, str]]]:
    """
    Returns (violations, escape_hatch_files) where:
    - violations: new forbidden imports not in baseline
    - escape_hatch_files: list of (file_path, reason) for L2 approved bypasses
    """
    root = modules_root or MODULES_ROOT
    baseline = _load_baseline(baseline_file)
    violations: list[Violation] = []
    escape_hatch_files: list[tuple[Path, str]] = []

    for py_file in root.rglob('*.py'):
        if _is_test_file(py_file, root):
            continue

        if _is_model_file(py_file) or _is_alembic_env(py_file, root):
            continue

        # A file that is not valid Python used to take the whole gate down
        # with a traceback: every other check after it went unrun, and the
        # operator read a stack trace instead of a finding. Reading and
        # parsing happen once here; a file that fails is skipped and named
        # where the skip belongs — ``_check_cross_module_imports`` walks the
        # same module tree and reports it as "not read".
        try:
            source = py_file.read_text(encoding='utf-8')
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        reason = _check_escape_hatch(py_file, source)
        if reason is not None:
            escape_hatch_files.append((py_file, reason))
            continue

        violations.extend(_collect_import_violations(py_file, tree))

    filtered = [
        violation
        for violation in violations
        if violation.baseline_key(root.parent) not in baseline
    ]

    return (
        sorted(filtered, key=lambda v: (str(v.file_path), v.line, v.import_path)),
        escape_hatch_files,
    )
