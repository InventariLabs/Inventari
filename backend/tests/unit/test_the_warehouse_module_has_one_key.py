"""The warehouse module answers to one key, and the old one does not come back.

It was called ``documents`` until the key was changed before the first
release. After a release a key is a promise — module authors write it in
``requires``, administrators' roles store its permission keys — so a stray
``documents:read`` or ``requires: ["documents"]`` added later would bring
back a module that no installation can enable, or a permission no role can
hold. Nothing here reads the document entity, whose tables and models still
say documents.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from app.core.architecture_lint._constants import APP_ROOT, MODULES_ROOT

pytestmark = pytest.mark.unit

FORMER_KEY = 'documents'
_FORMER_NAMESPACE = re.compile(rf'^{FORMER_KEY}:[A-Za-z_]')


def _manifests() -> list[tuple[Path, dict]]:
    return [
        (path, json.loads(path.read_text(encoding='utf-8')))
        for path in sorted(MODULES_ROOT.glob('*/manifest.json'))
    ]


def _sources() -> list[Path]:
    return [
        path
        for path in sorted(APP_ROOT.rglob('*.py'))
        if 'migrations' not in path.relative_to(APP_ROOT).parts
        and '__pycache__' not in path.parts
    ]


def test_no_manifest_names_requires_or_declares_the_former_key():
    found = []
    for path, manifest in _manifests():
        where = path.relative_to(APP_ROOT)
        if manifest.get('name') == FORMER_KEY:
            found.append(f'{where}: name')
        for field in ('requires', 'optional_requires'):
            if FORMER_KEY in manifest.get(field, []):
                found.append(f'{where}: {field}')
        for permission in manifest.get('permissions', []):
            # A permission is declared as an object, or named by its key alone.
            if isinstance(permission, str):
                permission = {'key': permission}
            for field in ('key', 'label_key', 'description_key'):
                if _FORMER_NAMESPACE.match(permission.get(field, '')):
                    found.append(f'{where}: {permission[field]}')

    assert found == [], f'the module is warehouse now: {found}'


def test_no_source_writes_a_permission_or_requires_under_the_former_key():
    found = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        where = path.relative_to(APP_ROOT)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _FORMER_NAMESPACE.match(node.value)
            ):
                found.append(f'{where}:{node.lineno}: {node.value!r}')
            if isinstance(node, ast.keyword) and node.arg in {
                'requires',
                'optional_requires',
            }:
                names = [
                    element.value
                    for element in ast.walk(node.value)
                    if isinstance(element, ast.Constant)
                ]
                if FORMER_KEY in names:
                    found.append(f'{where}:{node.value.lineno}: {node.arg}')

    assert found == [], f'the module is warehouse now: {found}'
