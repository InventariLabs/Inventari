"""The advanced module guide's hook tables are the base classes, not a memory of them.

A module author learns which hooks exist, and what each one is handed, from
the tables in ``docs/MODULE_ADVANCED_GUIDE.md``. They had drifted: the item
interceptor's table left out ``before_purge``, so an author guarding a delete
never learned that a purge skips ``before_delete``; four rows named the update
payload ``data`` where the hooks receive ``changes``; and the lifecycle section
left out ``on_install_async``, ``on_startup_async`` and ``on_modules_ready``.
Each table is read here and compared with the class it describes — every
public hook named, none invented, each with the parameters its signature has.
"""

from __future__ import annotations

import inspect
import os
import re
from pathlib import Path

from app.core._base_module import BaseModule
from app.core._interceptor_base import (
    CategoryInterceptor,
    ItemInterceptor,
    StorageInterceptor,
)

_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))
_GUIDE = _ROOT / 'docs' / 'MODULE_ADVANCED_GUIDE.md'

#: `name(param, param)` as the guide writes a hook, with or without `-> None`.
_HOOK = re.compile(r'`(\w+)\(([^)]*)\)(?: -> \w+)?`')


def _section(heading: str) -> str:
    guide = _GUIDE.read_text(encoding='utf-8')
    start = guide.index(heading)
    end = guide.find('\n#', start + len(heading))
    return guide[start : end if end != -1 else None]


def _table_rows(section: str) -> dict[str, list[str]]:
    """Each table row's hook in the first column, with its parameter names."""
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        match = re.match(r'^\| ' + _HOOK.pattern + r' \|', line)
        if match:
            name, params = match.groups()
            rows[name] = [p.strip() for p in params.split(',') if p.strip()]
    return rows


def _documented_anywhere(section: str) -> dict[str, list[str]]:
    """Every hook named in the section, in a table or in prose."""
    return {
        name: [p.strip() for p in params.split(',') if p.strip()]
        for name, params in _HOOK.findall(section)
    }


def _hooks(cls: type, prefix: str = '') -> dict[str, list[str]]:
    """The hooks a class defines itself, with their parameters after ``self``."""
    return {
        name: list(inspect.signature(member).parameters)[1:]
        for name, member in vars(cls).items()
        if inspect.isfunction(member)
        and not name.startswith('_')
        and name.startswith(prefix)
    }


def _base_module_hooks() -> dict[str, list[str]]:
    hooks: dict[str, list[str]] = {}
    for cls in reversed(BaseModule.__mro__):
        hooks.update(_hooks(cls, prefix='on_'))
    return hooks


def test_the_lifecycle_section_names_every_hook_with_its_parameters() -> None:
    documented = _documented_anywhere(_section('## Lifecycle Hooks'))
    expected = _base_module_hooks()
    assert {name: documented.get(name) for name in expected} == expected


def test_the_item_interceptor_table_is_the_item_interceptor() -> None:
    assert _table_rows(_section('### `ItemInterceptor` hooks')) == _hooks(
        ItemInterceptor
    )


def test_the_storage_interceptor_table_is_the_storage_interceptor() -> None:
    assert _table_rows(_section('### `StorageInterceptor` hooks')) == _hooks(
        StorageInterceptor
    )


def test_the_category_interceptor_has_the_storage_interceptors_shape() -> None:
    """The guide gives the category interceptor no table of its own: it says
    the shape is the storage interceptor's. That holds while each hook has the
    same name and the same parameters, the identifier renamed."""
    assert '`CategoryInterceptor` hooks — same shape as `StorageInterceptor`' in (
        _GUIDE.read_text(encoding='utf-8')
    )
    as_storage = {
        name: ['storage_id' if p == 'category_id' else p for p in params]
        for name, params in _hooks(CategoryInterceptor).items()
    }
    assert as_storage == _hooks(StorageInterceptor)
