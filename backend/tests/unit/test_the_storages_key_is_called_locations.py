"""The core key answers to ``locations``, and the old one does not come back.

It was called ``storages`` until the key was changed before the first
release. After a release a key is a promise — module authors write it in
``requires``, administrators' roles store its permission keys, webhook
receivers filter on its event names — so a stray ``storages:read``,
``requires: ["storages"]`` or ``storage.created`` added later would bring
back a feature no new module can depend on and no subscription can fire.
The key was plural and the event names it published were singular
(``storages``, but ``storage.created``), so both spellings are retired and
this gate looks for both.

What keeps its name is what already says location or is internal: the
``storage_locations`` table, every ``storage_location_id`` column, the
``StorageLocation`` model and the ``CoreStoragesAPI`` / ``StorageDTO``
classes. The REST paths and fields moved after the key, with a gate of
their own (``test_the_api_says_location.py``). The frontend's own half of
this gate lives beside the screens it reads
(``frontend/src/lib/__tests__/theStoragesKeyIsCalledLocations.test.ts``),
because the backend test run does not see the frontend tree.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from app.core.architecture_lint._constants import APP_ROOT, MODULES_ROOT

pytestmark = pytest.mark.unit

FORMER_KEY = 'storages'
# The key was plural and the event names it published were singular:
# ``storage.created`` survived a sweep that only knew ``storages.``, and it
# is the name a webhook receiver saved a subscription for. Both spellings
# are retired, so the gate knows both.
_FORMER_EVENT = re.compile(r'^storages?\.')
_FORMER_NAMESPACE = re.compile(rf'^{FORMER_KEY}:')


def _manifests() -> list[tuple[Path, dict]]:
    return [
        (path, json.loads(path.read_text(encoding='utf-8')))
        for path in sorted(MODULES_ROOT.glob('*/manifest.json'))
    ]


def _sources(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob('*.py'))
        if 'migrations' not in path.relative_to(root).parts
        and '__pycache__' not in path.parts
    ]


def test_no_manifest_names_the_former_key():
    found = []
    for path, manifest in _manifests():
        where = path.relative_to(APP_ROOT)
        if manifest.get('name') == FORMER_KEY:
            found.append(f'{where}: name')
        for field in ('requires', 'optional_requires'):
            if FORMER_KEY in manifest.get(field, []):
                found.append(f'{where}: {field}')
        for permission in manifest.get('permissions', []):
            if isinstance(permission, str):
                permission = {'key': permission}
            for field in ('key', 'label_key', 'description_key'):
                if _FORMER_NAMESPACE.match(permission.get(field, '')):
                    found.append(f'{where}: {permission[field]}')

    assert found == [], f'the feature is locations now: {found}'


def test_no_core_source_says_a_former_name():
    found = []
    for path in _sources(APP_ROOT):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        where = path.relative_to(APP_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == FORMER_KEY:
                found.append(f'{where}:{node.lineno}: {node.value!r}')
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and (
                    _FORMER_NAMESPACE.match(node.value)
                    or _FORMER_EVENT.match(node.value)
                )
            ):
                found.append(f'{where}:{node.lineno}: {node.value!r}')
            if isinstance(node, ast.keyword) and node.arg in {
                'requires',
                'optional_requires',
                'enabled_modules',
                'default_modules',
            }:
                names = [
                    element.value
                    for element in ast.walk(node.value)
                    if isinstance(element, ast.Constant)
                ]
                if FORMER_KEY in names:
                    found.append(f'{where}:{node.value.lineno}: {node.arg}')

    assert found == [], f'the feature is locations now: {found}'


def test_the_facade_exposes_locations_and_not_the_former_namespace():
    from app.core.public_api import core_api

    names = set(vars(core_api))
    assert {'locations', 'location_types'} <= names
    assert not ({FORMER_KEY, 'storage_types'} & names)


def test_the_core_event_namespace_says_location_and_collides_with_nothing():
    from app.core._event_types import SystemEvent
    from app.core.contracts.events._registry import EVENT_PAYLOAD_TYPES

    values = [event.value for event in SystemEvent]
    retired = [name for name in values if _FORMER_EVENT.match(name)]
    # The webhook catalogue is the other place a receiver reads names from;
    # a retired entry here would offer a subscription to an event that never
    # fires.
    retired += [name for name in EVENT_PAYLOAD_TYPES if _FORMER_EVENT.match(name)]
    assert retired == [], f'the event names are location.*: {retired}'
    assert {'location.created', 'location.updated', 'location.deleted'} <= set(values)
    # The new namespace did not land on a name another module already owned:
    # every ``location.*`` payload is one of the three carried across.
    core_location_events = {
        name for name in EVENT_PAYLOAD_TYPES if name.startswith('location.')
    }
    assert core_location_events == {
        'location.created',
        'location.updated',
        'location.deleted',
    }


def test_the_analytics_scope_is_locations():
    from app.core.contracts._analytics_dtos import OverviewDTO

    assert OverviewDTO.model_fields['value_scope'].default == 'locations'
