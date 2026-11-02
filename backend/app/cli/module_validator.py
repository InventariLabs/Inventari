"""Module validation (manifest + AST safety checks).

Moved from the deprecated top-level validate_module.py script.
Used by ``manage.py module validate`` and the module packaging pipeline.

The safety scan itself lives in :mod:`app.core.module_safety_analysis`, shared
with the runtime registry so this gate cannot again end up laxer than the
loader it is supposed to run ahead of.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from app.core.logging import get_logger
from app.core.manifest_icons import is_drawable_icon
from app.core.module_manifest_schema import PERMISSION_ACTIONS, ModuleManifest
from app.core.module_safety_analysis import (
    SafetyFinding,
    _is_test_file,
    analyze_module_safety,
)
from app.i18n import MAINTAINED_LANGUAGES

logger = get_logger(__name__)


def validate_manifest(module_dir: Path) -> list[str]:
    """Validate manifest.json using the shared Pydantic schema."""
    try:
        ModuleManifest.load(module_dir)
        return []
    except FileNotFoundError:
        return [f'{module_dir.name}: missing manifest.json']
    except (OSError, TypeError, ValueError) as exc:
        return [f'{module_dir.name}: invalid manifest.json ({exc})']


def validate_manifest_icon(module_dir: Path) -> list[str]:
    """Warn about a manifest ``icon`` the catalogue cannot draw.

    The frontend knows a closed list of icons and draws a generic package for
    any other name, so the author would otherwise find out only by looking at
    the catalogue. A warning rather than an error: the module works, and an
    unreadable manifest is ``validate_manifest``'s finding.
    """
    try:
        icon = ModuleManifest.load(module_dir).icon
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
        return []
    if icon is None or is_drawable_icon(icon):
        return []
    return [
        f'{module_dir.name}: manifest icon "{icon}" is not one the catalogue can '
        f'draw, so it shows a generic package icon instead '
        f'(accepted names: MODULES_GUIDE.md, "Icons")'
    ]


def validate_permission_actions(module_dir: Path) -> list[str]:
    """Warn about a permission whose action is outside the vocabulary.

    The key is stored by name in every organization's roles, so the word is
    cheap to change before release and a data migration after it. A warning
    rather than an error: the key works, and a module that means it says why
    in ``permission_action_exceptions``. An entry there that explains no such
    key is reported too, so the list cannot drift away from the keys.
    """
    try:
        manifest = ModuleManifest.load(module_dir)
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
        return []
    vocabulary = ', '.join(sorted(PERMISSION_ACTIONS))
    unexplained = [
        f'{module_dir.name}: permission "{key}" uses an action outside the '
        f'vocabulary ({vocabulary}); '
        f'rename it or give the reason in permission_action_exceptions '
        f'(MODULES_GUIDE.md, "Permissions")'
        for key in manifest.unexplained_actions
    ]
    idle = [
        f'{module_dir.name}: permission_action_exceptions names "{key}", which '
        f'is not a permission of this module outside the vocabulary; remove the entry'
        for key in manifest.idle_action_exceptions
    ]
    return unexplained + idle


def _format_error(module_name: str, finding: SafetyFinding) -> str:
    """CLI wording: one run reports on many modules, so every line names its own."""
    if finding.kind == 'parse_error':
        return (
            f'{module_name}: cannot parse {finding.rel_path.name} ({finding.subject})'
        )
    if finding.kind == 'forbidden_import':
        return (
            f'{module_name}: FORBIDDEN import {finding.subject} '
            f'at {finding.rel_path}:{finding.lineno}'
        )
    if finding.kind == 'off_surface_import':
        hint = f' {finding.hint}' if finding.hint else ''
        return (
            f'{module_name}: import outside the module SDK {finding.subject} '
            f'at {finding.rel_path}:{finding.lineno}.{hint}'
        )
    if finding.kind == 'forbidden_call':
        return (
            f'{module_name}: forbidden call {finding.subject}() '
            f'at {finding.rel_path}:{finding.lineno}'
        )
    noun = 'call' if finding.subject.endswith('()') else 'import'
    return (
        f'{module_name}: UNDECLARED capability "{finding.capability}" required for '
        f'{noun} "{finding.subject}" at {finding.rel_path}:{finding.lineno}'
    )


def validate_safety(module_dir: Path, declared_capabilities: list[str]) -> list[str]:
    """Report safety violations, one message per finding, prefixed by module name."""
    return [
        _format_error(module_dir.name, finding)
        for finding in analyze_module_safety(module_dir, declared_capabilities)
    ]


#: Imports each package the way discovery does — as ``app.modules.<name>`` —
#: from wherever its directory is, and prints ``{name: reason}`` for the ones
#: that fail as the last line of its output.
_IMPORT_PROBE = """
import importlib.util
import json
import sys
from pathlib import Path

failures = {}
for path in map(Path, sys.argv[1:]):
    name = f'app.modules.{path.name}'
    if name in sys.modules:  # imported already, as another package's dependency
        continue
    spec = importlib.util.spec_from_file_location(
        name, path / '__init__.py', submodule_search_locations=[str(path)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    try:
        spec.loader.exec_module(package)
    except BaseException as exc:
        sys.modules.pop(name, None)
        failures[path.name] = f'{type(exc).__name__}: {exc}'
print()
print(json.dumps(failures))
"""

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def validate_importable(module_dirs: list[Path]) -> list[str]:
    """Report each backend package that cannot be imported, and why.

    The safety scan reads import paths, not the names they import, so a typo
    in ``from app.core.module_sdk import ...`` passed every check here and
    surfaced only at the next start, when discovery rejected the module.
    Asking the interpreter is the only check that sees what discovery will.

    The probe runs in a fresh interpreter: the process asking may hold an
    older copy of the same package (an upgrade replaces one discovery has
    already imported), and a package that imports cleanly still declares
    models on the shared metadata, which must not leak into the caller.
    """
    packages = [d.resolve() for d in module_dirs if (d / '__init__.py').is_file()]
    if not packages:
        return []
    try:
        # -B: the probe writes no bytecode into the tree it was asked about.
        result = subprocess.run(
            [sys.executable, '-B', '-c', _IMPORT_PROBE, *map(str, packages)],
            cwd=_BACKEND_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [f'{d.name}: the import check could not run — {exc}' for d in packages]
    try:
        failures = json.loads(result.stdout.rstrip().rsplit('\n', 1)[-1])
    except ValueError:
        # The probe did not finish (a package that exits the interpreter on
        # import): no package in it can be called importable.
        why = result.stderr.strip()[-400:] or f'exit code {result.returncode}'
        return [
            f'{d.name}: the backend package cannot be imported — {why}'
            for d in packages
        ]
    return [
        f'{name}: the backend package cannot be imported — {reason}'
        for name, reason in sorted(failures.items())
    ]


def validate_deprecated_core_api(module_dir: Path) -> list[str]:
    """Report module code that uses a deprecated core_api method.

    Warning, not error, on purpose: the window exists so a module keeps
    working while it migrates — the runtime warns on every call (see
    ``install_runtime_warnings``) and the removal release deletes the
    method. This scan is how the author learns about the deadline months
    earlier, at validate and install time, with the method name and the
    release in hand.

    Static scanning sees direct ``core_api.<namespace>.<method>`` chains,
    called or merely referenced; a usage reached through an alias hides
    from this scan the same way it hides from the safety scan.
    """
    from app.core._core_api_deprecations import deprecated_facade_chains

    chains = deprecated_facade_chains()
    if not chains:
        return []

    findings: list[str] = []
    for py_file in sorted(module_dir.rglob('*.py')):
        if _is_test_file(py_file, module_dir):
            continue
        rel_path = py_file.relative_to(module_dir.parent)
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except SyntaxError:
            # An unparseable file is the safety scan's parse_error finding;
            # this scan stays quiet rather than reporting the file twice.
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            parts: list[str] = []
            cursor: ast.expr = node
            while isinstance(cursor, ast.Attribute):
                parts.append(cursor.attr)
                cursor = cursor.value
            if not isinstance(cursor, ast.Name) or cursor.id != 'core_api':
                continue
            deprecation = chains.get('.'.join(reversed(parts)))
            if deprecation:
                findings.append(
                    f'{module_dir.name}: deprecated core_api.'
                    f'{".".join(reversed(parts))} (removal in release '
                    f'{deprecation.removal_release}) at {rel_path}:'
                    f'{node.lineno} — use {deprecation.replacement}'
                )
    return findings


def skipped_paths(module_dir: Path) -> list[str]:
    """What the safety scan cannot read, named as ``rel -> target``.

    ``Path.rglob`` does not descend into symlinked directories, so a module
    carrying one that points outside the tree holds files the scan never
    read — and a clean report over a tree nobody read is exactly what this
    gate must not produce. Three shapes, named for what they are:

    - a link resolved **inside** the tree is not reported: the walk reads
      that content at its real path, and calling it "skipped" would name a
      hole where there is none;
    - a link resolved **outside** the tree is unread content and is named —
      deciding whether the target belongs to the module is the reviewer's
      call, not the tool's;
    - a **dangling** link (target does not exist) is named as dangling:
      ``is_dir`` is false for it, so the old check let it pass the report
      in silence — unreadable is not unread.
    """
    skipped: list[str] = []
    if not module_dir.is_dir():
        return skipped
    real_root = module_dir.resolve()
    for path in sorted(module_dir.rglob('*')):
        if not path.is_symlink():
            continue
        rel = path.relative_to(module_dir)
        target = os.readlink(path)
        if not path.exists():
            skipped.append(f'{rel} -> {target} (dangling: target does not exist)')
            continue
        if not path.is_dir():
            # A symlinked file is opened (and read) at the link's path, so
            # there is nothing unread to name here.
            continue
        if path.resolve().is_relative_to(real_root):
            continue
        skipped.append(f'{rel} -> {target}')
    return skipped


#: The maintained languages other than `en`. A community language is never
#: required of a module, official or not: it falls back to English per key.
REQUIRED_LANGUAGES = [lang for lang in MAINTAINED_LANGUAGES if lang != 'en']


def is_strict_i18n(module_dir: Path) -> bool:
    """True when this module owes all five languages, not just ``en``.

    Core and official modules ship with the product, so an untranslated string
    there is a product defect. A community module is written by someone who may
    speak one language, and demanding four placeholder catalogs only ever
    produced empty files.
    """
    try:
        module_type = ModuleManifest.load(module_dir).module_type
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError) as exc:
        # An unreadable manifest must not hide i18n findings — fall back to the
        # lenient default and let manifest validation report the real problem.
        logger.warning(
            'manifest.json unreadable for %s; falling back to community defaults',
            module_dir,
            exc_info=exc,
        )
        return False
    return module_type in ('core', 'official')


def validate_i18n(module_dir: Path) -> list[tuple[str, str]]:
    """Check that a module has the required i18n language files.

    Severity rules:
    - ``en.json`` is always required (error).
    - Other maintained languages (pl, de, fr, es) are required for *core* and *official*
      modules (error) and not reported at all for *community* modules: English
      is the only language a package owes, and a warning per language it
      chose not to ship reads as four problems above "validation passed".
    - A missing ``i18n/`` directory is reported at the appropriate severity.
    """
    results: list[tuple[str, str]] = []
    label = module_dir.name

    strict = is_strict_i18n(module_dir)
    severity = 'error' if strict else 'warning'

    i18n_dir = module_dir / 'i18n'
    if not i18n_dir.exists():
        results.append((severity, f'{label}: missing i18n/ directory'))
        return results

    en_path = i18n_dir / 'en.json'
    if not en_path.exists():
        results.append(('error', f'{label}: missing required i18n/en.json'))

    if not strict:
        return results

    for lang in REQUIRED_LANGUAGES:
        lang_path = i18n_dir / f'{lang}.json'
        if not lang_path.exists():
            results.append(('error', f'{label}: missing i18n/{lang}.json'))

    return results


def get_module_dirs(base_path: Path, module_name: str | None) -> list[Path]:
    if module_name:
        module_dir = base_path / module_name
        return [module_dir] if module_dir.exists() else []

    return [
        module_dir
        for module_dir in base_path.iterdir()
        if module_dir.is_dir()
        and not module_dir.name.startswith('_')
        and any(module_dir.iterdir())
        and (module_dir / 'manifest.json').exists()
    ]
