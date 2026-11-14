"""The tool/resource catalogue is a contract; this freezes it.

A client may cache `tools/list`; a rename, a reordering or a changed input
schema is a visible change for an agent that already learned the catalogue, so
it is reviewed here and carries a module semver bump. Regenerate the snapshot
with `MCP_SNAPSHOT_UPDATE=1` when the change is intended and the version moved.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.modules.mcp_server._http import build_server

pytestmark = pytest.mark.integration

_SNAPSHOT = Path(__file__).resolve().parents[1] / 'snapshots' / 'tools.json'
_MANIFEST = Path(__file__).resolve().parents[2] / 'manifest.json'


async def _payload(server) -> dict:
    manifest = json.loads(_MANIFEST.read_text('utf-8'))
    return {
        'module_version': manifest['version'],
        'tools': [
            tool.model_dump(by_alias=True, mode='json')
            for tool in await server.list_tools()
        ],
        'resources': [
            resource.model_dump(by_alias=True, mode='json')
            for resource in await server.list_resources()
        ],
    }


async def test_the_catalogue_matches_the_snapshot() -> None:
    payload = await _payload(build_server())

    if os.environ.get('MCP_SNAPSHOT_UPDATE') == '1':
        _SNAPSHOT.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8'
        )

    assert payload == json.loads(_SNAPSHOT.read_text('utf-8'))


async def test_the_catalogue_is_deterministic() -> None:
    first = await _payload(build_server())
    second = await _payload(build_server())

    assert first == second
    assert [tool['name'] for tool in first['tools']] == [
        'search_items',
        'get_item',
        'list_locations',
        'get_location_tree',
        'get_stock_levels',
        'list_lots',
        'get_expiring_soon',
        'create_item',
        'correct_stock',
    ]
