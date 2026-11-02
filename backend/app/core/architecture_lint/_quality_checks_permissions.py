"""Manifest permission keys must have a place where they are enforced.

A key declared in ``app/modules/<m>/manifest.json`` travels to the permission
catalog and shows up as a switch in the roles matrix. If no code ever asks for
it, that switch promises a restriction it does not apply — worse than dead
code, because dead code promises nothing. This check makes the promise
verifiable.

Enforcement means a string literal handed to a call that decides access:
``require_permission('<key>')``, either half of
``require_read_write('<read>', '<write>')``, ``has_permission('<key>')``, or a
module's own wrapper around them — approvals guards its router through
``_require_module_permission``, and a check that only knew the three canonical
names would call that module unguarded. Mounting the pair on a module's
top-level router counts for every endpoint of that module: see
``require_read_write`` in ``app/core/deps.py`` for why that is the default
rather than a per-endpoint declaration.

Core permission keys are out of scope. A module manifest may legitimately name
``items:read`` to say what it needs; Core owns that key, enforces it through the
``SystemPermission`` enum, and the module is not the place to look for it.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from app.core.module_manifest_schema import CORE_PERMISSION_KEYS

from ._constants import _is_test_file, _rel, _rel_parts

_ENFORCING_CALLS = frozenset(
    {'require_permission', 'require_read_write', 'has_permission'}
)


def _is_enforcing_call(name: str) -> bool:
    """Whether a call by this name decides access on a permission key.

    The name test catches module-local wrappers (``_require_module_permission``)
    without naming each one here — a list of approved wrapper names would go
    stale the first time a module wrote its own.
    """
    return name in _ENFORCING_CALLS or 'permission' in name.lower()


def _manifest_permission_keys(modules_root: Path) -> dict[str, str]:
    """Every permission key declared in a manifest, mapped to its module.

    Two shapes are in use: a bare list of strings, and a list of objects
    carrying ``key`` plus the labels the roles matrix renders.
    """
    keys: dict[str, str] = {}
    for manifest in sorted(modules_root.glob('*/manifest.json')):
        try:
            data = json.loads(manifest.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for entry in data.get('permissions') or []:
            key = entry if isinstance(entry, str) else entry.get('key')
            if key:
                keys.setdefault(str(key), manifest.parent.name)
    return keys


def _called_func_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ''


def _enforced_permission_keys(app_root: Path) -> set[str]:
    """Keys named as a string literal in one of the enforcing call shapes."""
    enforced: set[str] = set()
    for py_file in sorted(app_root.rglob('*.py')):
        if _is_test_file(py_file, app_root) or '__pycache__' in _rel_parts(
            py_file, app_root
        ):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_enforcing_call(_called_func_name(node)):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    enforced.add(arg.value)
    return enforced


def _check_manifest_permissions_enforced(
    modules_root: Path, app_root: Path, deferred: set[str]
) -> list[str]:
    """Flag manifest permission keys with no enforcement point anywhere."""
    declared = _manifest_permission_keys(modules_root)
    enforced = _enforced_permission_keys(app_root)
    errors: list[str] = []
    for key, module in sorted(declared.items()):
        if key in enforced or key in deferred or key in CORE_PERMISSION_KEYS:
            continue
        rel = _rel(modules_root / module / 'manifest.json')
        errors.append(
            f'::error file={rel},title=Architecture: permission declared but never enforced::'
            f"Permission '{key}' is declared by the {module} manifest and reaches the roles "
            f'matrix, but no code asks for it. Mount '
            f"require_read_write('{module}:read', '{module}:write') on the module router, "
            f'guard the endpoints that need it, or drop the key from the manifest.'
        )
    return errors
