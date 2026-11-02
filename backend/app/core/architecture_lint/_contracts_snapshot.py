"""Contracts snapshot: additive-only stability enforcement for public DTOs.

A committed JSON snapshot of every public contract in
``app.core.contracts`` (Pydantic DTOs and enums). The lint compares the live
contracts against the snapshot and rejects breaking changes:

- removed contract / field / enum member          -> ::error
- field type change                                -> ::error
- optional field becoming required                 -> ::error
- new *required* field                             -> ::error

Additive changes pass silently: new contracts, new *optional* fields, new enum
members, and required -> optional relaxations.

See ``docs/subsystems/CONTRACTS_STABILITY.md`` for the full policy.
"""

from __future__ import annotations

import json
import re
from dataclasses import MISSING, is_dataclass
from dataclasses import fields as fields_of
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

SNAPSHOT_VERSION = 1

_FORWARD_REF_RE = re.compile(r"ForwardRef\('(.+)'(?:,\s*[a-z_]+=(?:True|False))?\)")
_MODULE_PATH_RE = re.compile(r'\b(?:[a-z_][\w]*\.)+(?=[A-Z])')


def _normalize_type_repr(text: str) -> str:
    """Make a snapshot type repr import-order independent.

    A field annotated through a forward reference snapshots as either
    ``ForwardRef('UomDTO | None')`` or the resolved
    ``app.core.contracts._core_dtos.UomDTO | None`` depending on when
    ``model_rebuild()`` ran in the current process. Both spellings denote
    the same contract type, so the diff compares normalized forms:
    ForwardRef unwrapped, dotted module paths stripped (``a.b.C`` -> ``C``).
    On Python 3.14 the repr of a reference pydantic marks as a class carries
    ``is_class=True``, which is the same type again — the keyword argument is
    dropped with the wrapper.
    """
    match = _FORWARD_REF_RE.fullmatch(text)
    if match:
        text = match.group(1)
    return _MODULE_PATH_RE.sub('', text)


def build_snapshot() -> dict[str, Any]:
    """Introspect ``app.core.contracts`` into a canonical, serialisable dict."""
    from app.core import contracts
    from app.core._event_types import SystemEvent
    from app.core.llm.enums import LlmCapability

    # Enums a module outside the repo names but that live outside
    # ``contracts.__all__``: the event names it subscribes to and the
    # capability it declares for an LLM purpose.
    named_from_outside: dict[str, type] = {
        'SystemEvent': SystemEvent,
        'LlmCapability': LlmCapability,
    }
    candidates: dict[str, Any] = {
        name: getattr(contracts, name, None) for name in contracts.__all__
    }
    candidates.update(named_from_outside)

    entries: dict[str, Any] = {}
    for name in sorted(candidates):
        obj = candidates[name]
        if not isinstance(obj, type):
            continue
        if issubclass(obj, BaseModel):
            fields = {
                fname: {
                    'type': repr(field.annotation),
                    'required': field.is_required(),
                }
                for fname, field in sorted(obj.model_fields.items())
            }
            entries[name] = {'kind': 'model', 'fields': fields}
        elif is_dataclass(obj):
            # Frozen dataclass DTOs (e.g. UserProfileDTO) — same policy.
            fields = {
                field.name: {
                    'type': repr(field.type),
                    'required': (
                        field.default is MISSING and field.default_factory is MISSING
                    ),
                }
                for field in sorted(fields_of(obj), key=lambda f: f.name)
            }
            entries[name] = {'kind': 'model', 'fields': fields}
        elif issubclass(obj, Enum):
            entries[name] = {'kind': 'enum', 'members': sorted(m.name for m in obj)}
    return {'version': SNAPSHOT_VERSION, 'contracts': entries}


def load_snapshot(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def check_contracts_snapshot(path: Path) -> list[str]:
    """Return ``::error`` annotations for breaking changes vs the snapshot."""
    if not path.exists():
        return [
            '::error title=Architecture: Contracts snapshot missing::'
            f'{path} not found. Generate it with '
            '`python manage.py arch lint --update-contracts-snapshot` '
            'and commit the result.'
        ]
    breaking_changes = diff_snapshot(load_snapshot(path), build_snapshot())
    return [
        f'::error title=Architecture: Contracts breaking change::{change}. '
        'Additive-only policy: new optional fields are OK; renames, removals '
        'and type changes need a deprecation window. '
        'See docs/subsystems/CONTRACTS_STABILITY.md.'
        for change in breaking_changes
    ]


def write_snapshot(path: Path) -> int:
    """Write the current contracts snapshot. Returns the contract count."""
    snapshot = build_snapshot()
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + '\n')
    return len(snapshot['contracts'])


def diff_snapshot(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Return human-readable breaking changes (empty list = additive-only OK)."""
    errors: list[str] = []
    old_contracts = old.get('contracts', {})
    new_contracts = new.get('contracts', {})

    for name in sorted(old_contracts):
        if name not in new_contracts:
            errors.append(f'{name}: contract removed')
            continue
        old_entry = old_contracts[name]
        new_entry = new_contracts[name]
        if old_entry.get('kind') != new_entry.get('kind'):
            errors.append(
                f'{name}: kind changed {old_entry.get("kind")} -> {new_entry.get("kind")}'
            )
            continue
        if old_entry['kind'] == 'enum':
            removed = set(old_entry['members']) - set(new_entry['members'])
            errors.extend(
                f'{name}.{member}: enum member removed' for member in sorted(removed)
            )
            continue
        errors.extend(
            _diff_model_fields(name, old_entry['fields'], new_entry['fields'])
        )
    return errors


def _diff_model_fields(
    name: str, old_fields: dict[str, Any], new_fields: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    for fname in sorted(old_fields):
        if fname not in new_fields:
            errors.append(f'{name}.{fname}: field removed')
            continue
        old_field = old_fields[fname]
        new_field = new_fields[fname]
        if _normalize_type_repr(old_field['type']) != _normalize_type_repr(
            new_field['type']
        ):
            errors.append(
                f'{name}.{fname}: type changed {old_field["type"]} -> {new_field["type"]}'
            )
        elif not old_field['required'] and new_field['required']:
            errors.append(f'{name}.{fname}: optional field became required')
        # required -> optional is a relaxation and is allowed.
    for fname in sorted(new_fields):
        if fname not in old_fields and new_fields[fname]['required']:
            errors.append(
                f'{name}.{fname}: new required field '
                '(only optional fields may be added — additive-only policy)'
            )
    return errors
