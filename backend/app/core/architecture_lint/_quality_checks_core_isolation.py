"""Core isolation check: Core must not import feature modules.

``app/core/**`` importing ``app.modules.*`` inverts the dependency
direction — feature modules depend on Core, never the other way around.
Cross-cutting capabilities owned by a module are exposed to Core through a
registry (e.g. :mod:`app.core.period_guard`) or a cross-module public API
(``*_api.py``), never by direct import from Core.

Zero baseline: the single historical violation (Core → documents periods)
has since been removed. New violations are ``::error``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ._constants import _is_test_file, _rel

#: Imports of a feature module from Core that are deliberate and gated — the
#: caller checks the module is enabled first and degrades when it is not. They
#: are listed here rather than silently tolerated so that adding a new one is a
#: decision someone makes on purpose, in review.
GATED_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # Onboarding and profile switching apply a documents preset only when
        # the warehouse module is enabled for the organization.
        ('app/services/onboarding_service.py', 'app.modules.warehouse'),
        ('app/services/profile_switch_service.py', 'app.modules.warehouse'),
        # Barcode lookup falls back to Open Food Facts when nutrition is on.
        ('app/api/_items_product_templates.py', 'app.modules.nutrition'),
    }
)


def _is_gated_exception(rel_path: object, module_path: str) -> bool:
    text = str(rel_path)
    return any(
        text.endswith(path) and module_path.startswith(prefix)
        for path, prefix in GATED_EXCEPTIONS
    )


def _check_core_module_imports(core_dir: Path) -> list[str]:
    """Emit ``::error`` for ``app.modules.*`` imports inside a Core directory.

       Applied to ``app/core/``, ``app/services/`` and ``app/api/``: all three are
       Core, and confining the rule to ``app/core/`` left the actual violations
    unguarded — every one found by lived in services or api.
    """
    errors: list[str] = []
    for py_file in sorted(core_dir.rglob('*.py')):
        if _is_test_file(py_file, core_dir):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            module_path: str | None = None
            lineno = 0
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith('app.modules'):
                        module_path = alias.name
                        lineno = node.lineno
                        break
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith('app.modules')
            ):
                module_path = node.module
                lineno = node.lineno
            if module_path is None:
                continue
            rel = _rel(py_file)
            if _is_gated_exception(rel, module_path):
                continue
            errors.append(
                f'::error file={rel},line={lineno},'
                f'title=Architecture: Core imports feature module::'
                f"Import of '{module_path}' in app/core/** inverts the "
                f'dependency direction — modules depend on Core, never the '
                f'reverse. Expose the capability through a Core registry '
                f'(e.g. app.core.period_guard) or a cross-module *_api.py.'
            )
    return errors
