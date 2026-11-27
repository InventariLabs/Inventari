"""Every public method of ``equipment_api`` carries a stability class.

The rentals module reaches the equipment register through this door, and a
module installed from outside whose manifest requires ``equipment`` may do
the same. ``docs/subsystems/CONTRACTS_STABILITY.md`` says which methods that
is and how safe they are; a method added without a row there is a promise
nobody made, so the list is read against the class itself.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.modules.equipment.equipment_api import EquipmentAPI

_BACKEND_DIR = Path(__file__).resolve().parents[5]
_PROJECT_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT') or _BACKEND_DIR.parent)
_DOC = _PROJECT_ROOT / 'docs' / 'subsystems' / 'CONTRACTS_STABILITY.md'

_ROW = re.compile(r'^\| `(\w+)` \| (stable|experimental) \|', re.MULTILINE)
_HEADING = '### Module APIs: `equipment_api`'


def _equipment_section(text: str) -> str:
    start = text.index(_HEADING)
    rest = text[start + len(_HEADING) :]
    end = re.search(r'^### ', rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


@pytest.mark.integration
def test_every_equipment_api_method_is_listed_with_its_class() -> None:
    assert _DOC.exists(), f'{_DOC} is not reachable from here'
    listed = dict(_ROW.findall(_equipment_section(_DOC.read_text(encoding='utf-8'))))
    public = {
        name
        for name in vars(EquipmentAPI)
        if not name.startswith('_') and callable(getattr(EquipmentAPI, name))
    }

    assert public - listed.keys() == set(), 'add these to CONTRACTS_STABILITY.md'
    assert listed.keys() - public == set(), 'these are listed but no longer exist'
    assert listed['is_enabled_async'] == 'stable'
