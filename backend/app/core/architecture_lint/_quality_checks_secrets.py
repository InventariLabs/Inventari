"""A module's secret has to be bound to that module.

Binding exists and works — the module name is authenticated data inside
the cipher, so a stored value cannot be read as another module's and
cannot be edited into one. What was missing is that nothing used it: the
module-facing write helper encrypted with the app-wide key, and a secret
saved through it read back as any module's. This check is the part that
keeps the fix from quietly coming undone.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ._constants import _is_test_file, _rel, _rel_parts

# ---------------------------------------------------------------------------
# Module secrets: a module may not write a secret nobody owns
# ---------------------------------------------------------------------------

#: The app-wide crypto surface. These bind nothing — a value written
#: through them reads back as any module's secret — so they belong to core
#: code handling the installation's own credentials (SMTP, a provider API
#: key), never to a module holding one organization's.
_APP_WIDE_SECRET_CALLS = (
    ('secrets', 'encrypt'),
    ('secrets', 'decrypt'),
)

#: The installation-wide helpers themselves, wherever a module reaches them
#: from — ``core_api.settings.encrypt_app_secret``, ``crypto_service.
#: encrypt_app_secret``, or the name imported bare — and whether they are
#: called or handed on: the name is the whole question.
_APP_WIDE_SECRET_NAMES = frozenset({'encrypt_app_secret', 'decrypt_app_secret'})


def _app_wide_secret_call(node: ast.AST) -> str | None:
    """``core_api.secrets.encrypt(...)``, and any reach for the app-wide helpers."""
    if isinstance(node, ast.ImportFrom):
        for alias in node.names:
            if alias.name in _APP_WIDE_SECRET_NAMES:
                return alias.name
        return None
    if isinstance(node, ast.Attribute) and node.attr in _APP_WIDE_SECRET_NAMES:
        return node.attr
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    owner = node.func.value
    if not isinstance(owner, ast.Attribute):
        return None
    for namespace, method in _APP_WIDE_SECRET_CALLS:
        if owner.attr == namespace and node.func.attr == method:
            return f'{namespace}.{method}'
    return None


def _check_module_secret_binding(modules_root: Path) -> list[str]:
    """Emit ``::error`` for a module reaching for the unbound crypto surface.

    A module's secret belongs to that module: the name is authenticated
    data inside the cipher, so the stored text cannot be read as another
    module's and cannot be edited into one. The app-wide calls produce a
    value with no owner, which is how a key saved by one module read back
    as any module's — measured, not theorised.

    No baseline: the tree has no such call site, and the point of writing
    the check on the same day as the fix is that it never acquires one.
    """
    errors: list[str] = []
    for py_file in sorted(modules_root.rglob('*.py')):
        parts = _rel_parts(py_file, modules_root)
        if _is_test_file(py_file, modules_root) or '__pycache__' in parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, OSError, UnicodeDecodeError, ValueError):
            continue
        for node in ast.walk(tree):
            called = _app_wide_secret_call(node)
            if called is None:
                continue
            assert isinstance(node, (ast.Call, ast.Attribute, ast.ImportFrom))
            errors.append(
                f'::error file={_rel(py_file)},line={node.lineno},'
                f'title=Architecture: module secret is not bound to its module::'
                f'{called}() encrypts with no owner, so the value '
                f"reads back as any module's secret. Use "
                f'core_api.secrets.encrypt_for_module(<module>, value) / '
                f'decrypt_for_module, or core_api.settings.encrypt_secret('
                f'<module>, value) for a settings field.'
            )
    return errors
