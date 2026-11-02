"""core_api snapshot: additive-only stability enforcement for the facade.

``contracts_snapshot.json`` freezes the *shapes* modules exchange with the
core; this freezes the *surface* they call. The two were never the same
guarantee, and only one of them existed: a rename, a dropped namespace or a
parameter that quietly became required passed every gate in the repository,
because no file recorded what the facade looked like yesterday. In-tree
modules were repaired in the same commit and never noticed. A module living
outside this repository finds out at runtime, in front of a user.

The policy mirrors the DTO snapshot, because the failure is the same shape:

- removed namespace / method                       -> ::error
- parameter removed, renamed or reordered          -> ::error
- optional parameter becoming required             -> ::error
- new *required* parameter                         -> ::error

Additive changes pass silently: new namespaces, new methods, new optional
parameters, and required -> optional relaxations.

**The deprecation window is the way through.** A method registered in
``app.core._core_api_deprecations`` may be removed without an error — that
registry is a dated, reviewed promise that the surface is going away, and
honouring it is the point of writing one. Removing a method that was never
registered is what this gate refuses, and the message says so.

Regenerate after an intentional, additive change:

    python manage.py arch lint --update-core-api-snapshot
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

SNAPSHOT_VERSION = 1

#: Parameter kinds that a caller can pass positionally or by name. ``self``
#: is dropped; ``*args``/``**kwargs`` are recorded but carry no default.
_SKIPPED = {'self'}


def _signature_of(func: Any) -> list[dict[str, Any]]:
    """Record a method's parameters in call order, with requiredness."""
    params = []
    for name, param in inspect.signature(func).parameters.items():
        if name in _SKIPPED:
            continue
        params.append(
            {
                'name': name,
                'kind': param.kind.name,
                'required': param.default is inspect.Parameter.empty
                and param.kind
                not in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                ),
            }
        )
    return params


def build_snapshot() -> dict[str, Any]:
    """Introspect the live ``core_api`` facade into a canonical dict."""
    from app.core.public_api import core_api

    namespaces: dict[str, Any] = {}
    for ns_name in sorted(vars(core_api)):
        if ns_name.startswith('_'):
            continue
        namespace = getattr(core_api, ns_name)
        methods: dict[str, Any] = {}
        for attr in sorted(dir(type(namespace))):
            if attr.startswith('_'):
                continue
            member = getattr(type(namespace), attr, None)
            if not callable(member):
                continue
            methods[attr] = {'params': _signature_of(member)}
        namespaces[ns_name] = {
            'class': type(namespace).__name__,
            'methods': methods,
        }
    return {'version': SNAPSHOT_VERSION, 'namespaces': namespaces}


def load_snapshot(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def write_snapshot(path: Path) -> int:
    """Write the current facade snapshot. Returns the method count."""
    snapshot = build_snapshot()
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + '\n')
    return sum(len(ns['methods']) for ns in snapshot['namespaces'].values())


def _deprecated_qualifiers() -> set[str]:
    from app.core._core_api_deprecations import DEPRECATED_CORE_API

    return set(DEPRECATED_CORE_API)


def diff_snapshot(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Return human-readable breaking changes (empty list = additive-only)."""
    errors: list[str] = []
    deprecated = _deprecated_qualifiers()
    old_ns = old.get('namespaces', {})
    new_ns = new.get('namespaces', {})

    for ns_name in sorted(old_ns):
        if ns_name not in new_ns:
            errors.append(f'core_api.{ns_name}: namespace removed')
            continue
        old_entry = old_ns[ns_name]
        new_entry = new_ns[ns_name]
        if old_entry.get('class') != new_entry.get('class'):
            errors.append(
                f'core_api.{ns_name}: class changed '
                f'{old_entry.get("class")} -> {new_entry.get("class")}'
            )
        errors.extend(
            _diff_methods(
                ns_name,
                old_entry.get('class', ''),
                old_entry['methods'],
                new_entry['methods'],
                deprecated,
            )
        )
    return errors


def _diff_methods(
    ns_name: str,
    class_name: str,
    old_methods: dict[str, Any],
    new_methods: dict[str, Any],
    deprecated: set[str],
) -> list[str]:
    errors: list[str] = []
    for name in sorted(old_methods):
        if name not in new_methods:
            # A removal that went through the deprecation window is the
            # window working, not a breaking change.
            if f'{class_name}.{name}' in deprecated:
                continue
            errors.append(
                f'core_api.{ns_name}.{name}: method removed without a '
                f'deprecation entry ({class_name}.{name} is not in '
                f'app.core._core_api_deprecations)'
            )
            continue
        errors.extend(
            _diff_params(
                f'core_api.{ns_name}.{name}',
                old_methods[name]['params'],
                new_methods[name]['params'],
            )
        )
    return errors


def _diff_params(
    label: str, old_params: list[dict[str, Any]], new_params: list[dict[str, Any]]
) -> list[str]:
    """Compare parameters in call order — position is part of the contract."""
    errors: list[str] = []
    new_by_name = {p['name']: p for p in new_params}

    for index, old_param in enumerate(old_params):
        name = old_param['name']
        new_param = new_by_name.get(name)
        if new_param is None:
            errors.append(f'{label}({name}): parameter removed or renamed')
            continue
        if new_params.index(new_param) != index and old_param['kind'] in (
            'POSITIONAL_ONLY',
            'POSITIONAL_OR_KEYWORD',
        ):
            errors.append(
                f'{label}({name}): positional parameter moved '
                f'{index} -> {new_params.index(new_param)}'
            )
        if old_param['kind'] != new_param['kind']:
            errors.append(
                f'{label}({name}): parameter kind changed '
                f'{old_param["kind"]} -> {new_param["kind"]}'
            )
        elif not old_param['required'] and new_param['required']:
            errors.append(f'{label}({name}): optional parameter became required')

    old_names = {p['name'] for p in old_params}
    for new_param in new_params:
        if new_param['name'] not in old_names and new_param['required']:
            errors.append(
                f'{label}({new_param["name"]}): new required parameter '
                '(only optional parameters may be added — additive-only policy)'
            )
    return errors


def check_core_api_snapshot(path: Path) -> list[str]:
    """Return ``::error`` annotations for breaking changes vs the snapshot."""
    if not path.exists():
        return [
            '::error title=Architecture: core_api snapshot missing::'
            f'{path} not found. Generate it with '
            '`python manage.py arch lint --update-core-api-snapshot` '
            'and commit the result.'
        ]
    return [
        f'::error title=Architecture: core_api breaking change::{change}. '
        'Additive-only policy: new namespaces, methods and optional '
        'parameters are OK; a removal needs an entry in '
        'app.core._core_api_deprecations with a removal_release.'
        for change in diff_snapshot(load_snapshot(path), build_snapshot())
    ]
