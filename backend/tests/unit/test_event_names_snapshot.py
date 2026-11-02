"""Event names are frozen the way event payload shapes are.

``SystemEvent`` and the payload DTOs sit in ``contracts_snapshot.json``, but
the names that modules contribute (``recipe.created`` and its kin) are plain
strings: renaming or dropping one silences every webhook endpoint and
subscriber that named it, with no exception anywhere.

``event_names_snapshot.json`` lists every name the core table and the in-tree
modules declare. The rule is the additive one: a name may be added, never
removed or renamed without a deliberate, reviewed change to the snapshot.
Regenerate it with ``UPDATE_EVENT_NAMES_SNAPSHOT=1`` on this test.
"""

import json
import os
import re
from pathlib import Path

from app.core.contracts.events import EVENT_PAYLOAD_TYPES

_APP = Path(__file__).resolve().parents[2] / 'app'
_SNAPSHOT = _APP / 'core' / 'event_names_snapshot.json'
_REGISTRATION = re.compile(r"register_payload\(\s*'([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)'")


def _declared_names() -> list[str]:
    """Core table names plus every name an in-tree module registers."""
    names = set(EVENT_PAYLOAD_TYPES)
    for source in (_APP / 'modules').glob('*/module.py'):
        names.update(_REGISTRATION.findall(source.read_text(encoding='utf-8')))
    return sorted(names)


def test_no_event_name_leaves_without_a_reviewed_snapshot_change() -> None:
    declared = _declared_names()
    if os.environ.get('UPDATE_EVENT_NAMES_SNAPSHOT'):
        _SNAPSHOT.write_text(
            json.dumps({'version': 1, 'events': declared}, indent=2) + '\n',
            encoding='utf-8',
        )
    frozen = json.loads(_SNAPSHOT.read_text(encoding='utf-8'))['events']

    removed = sorted(set(frozen) - set(declared))
    assert not removed, (
        f'event names removed or renamed: {removed}. Receivers subscribed to '
        'them go silent; if the change is deliberate, regenerate the snapshot '
        'with UPDATE_EVENT_NAMES_SNAPSHOT=1 and review the diff.'
    )


def test_the_snapshot_lists_the_module_events() -> None:
    frozen = set(json.loads(_SNAPSHOT.read_text(encoding='utf-8'))['events'])
    assert {
        'recipe.created',
        'purchase_order.confirmed',
        'equipment.checkout',
    } <= frozen
