"""module SDK snapshot: additive-only stability for the module contract.

``contracts_snapshot.json`` freezes the DTO shapes a module exchanges with the
core, ``core_api_snapshot.json`` freezes the facade it calls, and this file
freezes the third half: what ``app.core.module_sdk`` exports and the shape of
the hooks a module implements. Before it existed, ``BaseModule``,
``define_module``, ``ModuleContext``, the interceptor and contribution classes
were contracts in fact — every external module subclasses or raises through
them — and in no gate at all: a renamed hook or a new abstract method passed
every check in the repository and broke every module outside it the day it
shipped.

What is recorded, per exported name:

- the kind (function, class, value);
- a function's parameters, in call order, with their requiredness;
- a class's constructor parameters, its base classes, and the methods and
  properties it defines itself (the hooks it offers), each with its
  parameters and whether it is abstract;
- a value (a registry or pipeline singleton) the same methods of its type,
  when the type is this repository's own.

The policy mirrors the facade, because the failure is the same shape:

- name removed from ``__all__``                        -> ::error
- kind changed                                         -> ::error
- parameter removed, renamed, reordered or made required -> ::error
- new *required* parameter or new required field       -> ::error
- method removed or changed kind on a hook base        -> ::error
- base class changed                                   -> ::error
- concrete method becoming abstract                    -> ::error
- new *abstract* method on a hook base                 -> ::error

Additive changes pass silently: new exported names, new optional parameters,
new optional fields, new concrete methods, and required -> optional
relaxations. A module can ignore an export it does not use, but it cannot
survive an export it uses going away.

There is no deprecation window yet, because none can be honoured before the
first public release: 0.11.0 is the first version a module outside this
repository can be built against, so every removal before it breaks nobody.
After it, a removal is a deliberate change to this snapshot — a reviewed JSON
diff that says what a module author has to change — not a side effect of a
refactor.

Regenerate after an intentional, additive change:

    python manage.py arch lint --update-module-sdk-snapshot
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from ._core_api_snapshot import _diff_params, _signature_of

SNAPSHOT_VERSION = 1

#: Attributes a framework writes onto a class for its own bookkeeping. They
#: are not part of the module contract, and recording them would turn a
#: pydantic or SQLAlchemy upgrade into a breaking-change report. Everything
#: else a class defines is frozen, including the SQLAlchemy ``metadata`` a
#: module's migration environment reads off ``ModuleModelBase``.
_FRAMEWORK_ATTRIBUTES = frozenset(
    {'model_config', 'model_fields', 'model_computed_fields'}
)


def _member_entry(attr: Any) -> dict[str, Any]:
    """What one class-level name means for a module.

    ``property`` is a hook too (``BaseModule.metadata`` and
    ``register_routes`` are abstract properties a module implements), so it is
    recorded by name and abstractness rather than dropped as a non-callable.
    """
    if isinstance(attr, property):
        return {
            'kind': 'property',
            'abstract': bool(getattr(attr.fget, '__isabstractmethod__', False)),
        }
    if isinstance(attr, staticmethod):
        return {
            'kind': 'static_method',
            'abstract': bool(getattr(attr.__func__, '__isabstractmethod__', False)),
            'params': _signature_of(attr.__func__),
        }
    if isinstance(attr, classmethod):
        return {
            'kind': 'class_method',
            'abstract': bool(getattr(attr.__func__, '__isabstractmethod__', False)),
            'params': _signature_of(attr.__func__),
        }
    if inspect.isfunction(attr):
        return {
            'kind': 'method',
            'abstract': bool(getattr(attr, '__isabstractmethod__', False)),
            'params': _signature_of(attr),
        }
    return {'kind': 'attribute'}


def _init_signature(obj: type) -> list[dict[str, Any]]:
    """A class's constructor parameters, or nothing when Python cannot say.

    ``inspect.signature`` raises for a class inheriting a C-level ``__init__``
    it cannot inspect (``ValueError`` subclasses such as ``PeriodClosedError``
    are the ones in this surface). The constructor is still the contract for
    the classes that define one; for the rest there is nothing to record, and
    a snapshot that cannot be built is worse than one that is smaller.
    """
    try:
        return _signature_of(obj)
    except (TypeError, ValueError):
        return []


def _class_entry(obj: type) -> dict[str, Any]:
    """A class's contract: its constructor, its bases and the hooks it offers."""
    members: dict[str, Any] = {}
    for name, attr in vars(obj).items():
        if name.startswith('_') or name in _FRAMEWORK_ATTRIBUTES:
            continue
        members[name] = _member_entry(attr)
    return {
        'kind': 'class',
        'bases': [base.__name__ for base in obj.__bases__],
        'init': _init_signature(obj),
        'members': members,
    }


def _entry(name: str) -> dict[str, Any]:
    from app.core import module_sdk

    obj = getattr(module_sdk, name)
    if inspect.isclass(obj):
        return _class_entry(obj)
    if inspect.isroutine(obj):
        return {'kind': 'function', 'params': _signature_of(obj)}
    # A registry or pipeline singleton: the name carries the object; its type
    # is what a module may rely on, and a rename of the type is the signal.
    entry: dict[str, Any] = {'kind': 'value', 'type': type(obj).__name__}
    # A module calls the singleton's methods (``scan_registry.register``), so
    # those are the contract too -- but only for a type this repository owns;
    # a re-exported typing alias has no methods of ours to freeze.
    if type(obj).__module__.startswith('app.'):
        entry['members'] = _class_entry(type(obj))['members']
    return entry


def build_snapshot() -> dict[str, Any]:
    """Introspect the live ``app.core.module_sdk`` into a canonical dict."""
    from app.core import module_sdk

    return {
        'version': SNAPSHOT_VERSION,
        'names': {name: _entry(name) for name in sorted(module_sdk.__all__)},
    }


def load_snapshot(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def write_snapshot(path: Path) -> int:
    """Write the current SDK snapshot. Returns the exported-name count."""
    snapshot = build_snapshot()
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + '\n')
    return len(snapshot['names'])


def _diff_members(
    label: str, old_members: dict[str, Any], new_members: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    for name in sorted(old_members):
        old = old_members[name]
        new = new_members.get(name)
        if new is None:
            errors.append(
                f'{label}.{name}: member removed — a module that overrides or '
                'calls it stops working'
            )
            continue
        if old['kind'] != new['kind']:
            errors.append(
                f'{label}.{name}: kind changed {old["kind"]} -> {new["kind"]}'
            )
            continue
        if not old.get('abstract', False) and new.get('abstract', False):
            errors.append(
                f'{label}.{name}: concrete member became abstract — every '
                'subclass must now implement it'
            )
        if 'params' in old and 'params' in new:
            errors.extend(_diff_params(f'{label}.{name}', old['params'], new['params']))
    for name in sorted(set(new_members) - set(old_members)):
        if new_members[name].get('abstract', False):
            errors.append(
                f'{label}.{name}: new abstract member — every module '
                'subclass must implement it, so it cannot be added to a hook '
                'base (give it a default body instead)'
            )
    return errors


def _diff_class(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if old.get('bases') != new.get('bases'):
        errors.append(
            f'{name}: base class changed {old.get("bases")} -> {new.get("bases")}'
        )
    errors.extend(_diff_params(name, old.get('init', []), new.get('init', [])))
    errors.extend(_diff_members(name, old.get('members', {}), new.get('members', {})))
    return errors


def diff_snapshot(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Return human-readable breaking changes (empty list = additive-only)."""
    errors: list[str] = []
    old_names = old.get('names', {})
    new_names = new.get('names', {})

    for name in sorted(old_names):
        if name not in new_names:
            errors.append(
                f'{name}: removed from app.core.module_sdk — a module '
                'importing it stops working'
            )
            continue
        before = old_names[name]
        after = new_names[name]
        if before['kind'] != after['kind']:
            errors.append(f'{name}: kind changed {before["kind"]} -> {after["kind"]}')
        elif before['kind'] == 'function':
            errors.extend(_diff_params(name, before['params'], after['params']))
        elif before['kind'] == 'class':
            errors.extend(_diff_class(name, before, after))
        elif before.get('type') != after.get('type'):
            errors.append(
                f'{name}: value type changed '
                f'{before.get("type")} -> {after.get("type")}'
            )
        else:
            errors.extend(
                _diff_members(name, before.get('members', {}), after.get('members', {}))
            )
    return errors


def check_module_sdk_snapshot(path: Path) -> list[str]:
    """Return ``::error`` annotations for breaking changes vs the snapshot."""
    if not path.exists():
        return [
            '::error title=Architecture: module SDK snapshot missing::'
            f'{path} not found. Generate it with '
            '`python manage.py arch lint --update-module-sdk-snapshot` '
            'and commit the result.'
        ]
    return [
        f'::error title=Architecture: module SDK breaking change::{change}. '
        'Additive-only policy: new names, methods and optional parameters '
        'are OK; a removal or a renamed parameter breaks every module that '
        'imports it. Regenerate the snapshot deliberately for an intended '
        'change (`--update-module-sdk-snapshot`) and say why in the commit '
        'message; after v0.11.0 it also gets a **Breaking** entry in '
        'CHANGELOG.md (AGENTS.md, Changelog).'
        for change in diff_snapshot(load_snapshot(path), build_snapshot())
    ]
