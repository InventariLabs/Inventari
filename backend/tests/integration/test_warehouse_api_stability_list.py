"""Every public method of ``warehouse_api`` carries a stability class.

``docs/subsystems/CONTRACTS_STABILITY.md`` tells a module author which of the
warehouse's methods they may build on. A method added without a row there is
a promise nobody made, so the list is read against the class itself.
``docker-compose.yml`` mounts the checkout into the backend container and
names it in ``INVENTARI_REPO_ROOT``, as for the other documentation checks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.modules.warehouse.warehouse_api import WarehouseAPI

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT') or _BACKEND_DIR.parent)
_DOC = _PROJECT_ROOT / 'docs' / 'subsystems' / 'CONTRACTS_STABILITY.md'

_ROW = re.compile(r'^\| `(\w+)` \| (stable|experimental) \|', re.MULTILINE)


@pytest.mark.integration
def test_every_warehouse_api_method_is_listed_with_its_class() -> None:
    assert _DOC.exists(), f'{_DOC} is not reachable from here'
    listed = dict(_ROW.findall(_DOC.read_text(encoding='utf-8')))
    public = {
        name
        for name in vars(WarehouseAPI)
        if not name.startswith('_') and callable(getattr(WarehouseAPI, name))
    }

    assert public - listed.keys() == set(), 'add these to CONTRACTS_STABILITY.md'
    assert listed.keys() - public == set(), 'these are listed but no longer exist'
    assert listed['register_pre_post_check'] == 'stable'
