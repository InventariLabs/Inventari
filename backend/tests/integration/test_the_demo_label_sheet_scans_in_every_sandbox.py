"""The demo's label sheet is worth printing: its codes answer in any sandbox.

A visitor prints one sheet — the demo's shelves and a handful of its
products — and scans the printed codes with a phone. The sheet only earns
its paper if a code resolves wherever the visitor was sent, so this claims
two sandboxes off the pool the way two visitors would, prints the sheet in
both and scans every code printed on it in both: the same sheet, the same
codes, every one of them answered.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import pytest

from app.config import settings
from app.modules.printing.services.demo_label_sheet_service import (
    demo_label_sheet_async,
)
from tests.integration._demo_world import ids, pooled_sandboxes
from tests.integration._shelf import run_in_async_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

SHEET = '/api/v1/printing/demo-label-sheet'
SANDBOX = '/api/v1/demo/sandbox'

#: A shelf's code in the business format warehouses name their racks with:
#: a zone letter and two-digit numbers under it, ``A-01``, ``A-01-01``.
SHELF_CODE = re.compile(r'[A-Z]+(?:-\d{2}){1,2}')


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)


@pytest.fixture
def two_claims(demo_world, async_engine_fixture) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Two sandboxes built the way ``demo fill-pool`` builds one, offered on
    the pool: an organization and its administrator each.
    """
    payload = demo_world('pooled-sandboxes', pooled_sandboxes(async_engine_fixture))
    return [ids(pair) for pair in payload]


def _auth(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


async def _sheet_codes(db: AsyncSession, org_id: uuid.UUID) -> list[str]:
    """The codes the sheet prints for *org_id*, read as the route reads it."""
    labels, png = await demo_label_sheet_async(db, org_id)
    assert png
    return [label.code for label in labels]


def test_the_sheet_prints_the_same_codes_and_they_scan_in_both_sandboxes(
    demo, client, async_engine_fixture, two_claims: list[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    # Two visitors take the two offered sandboxes. The first claim sets
    # this client's demo cookie, and the route answers a returning visitor
    # with the same account again — so the second claim must ask for a
    # fresh one, or the sheet below is compared with itself.
    first = client.post(SANDBOX, json={})
    assert first.status_code == 200, first.text
    second = client.post(SANDBOX, json={'fresh': True})
    assert second.status_code == 200, second.text
    tokens = [first.json()['access_token'], second.json()['access_token']]

    # Both offered sandboxes were taken, one administrator each — two
    # organizations, before any sheet is compared or any code scanned.
    claimed_admins = set()
    for token in tokens:
        me = client.get('/api/v1/auth/me', headers=_auth(token))
        assert me.status_code == 200, me.text
        claimed_admins.add(me.json()['id'])
    assert claimed_admins == {str(admin_id) for _org_id, admin_id in two_claims}, (
        'the two claims did not take the two offered sandboxes'
    )

    # Each prints the sheet its own sandbox offers.
    sheets = []
    for token in tokens:
        sheet = client.get(SHEET, headers=_auth(token))
        assert sheet.status_code == 200, sheet.text
        assert sheet.headers['content-type'].startswith('image/png')
        sheets.append(sheet.content)
    assert sheets[0] == sheets[1], 'two sandboxes hand out the same sheet'

    # The sheet's contents: identical in both sandboxes, shelf and product.
    codes_by_org = [
        run_in_async_session(
            async_engine_fixture,
            lambda adb, org=org_id: _sheet_codes(adb, org),
        )
        for org_id, _admin_id in two_claims
    ]
    assert codes_by_org[0] == codes_by_org[1]

    codes = codes_by_org[0]
    shelves = [code for code in codes if not code.isdigit()]
    products = [code for code in codes if code.isdigit()]
    assert shelves, 'the sheet carries the demo shelves'
    assert products, 'the sheet carries a handful of the demo products'
    for code in shelves:
        assert SHELF_CODE.fullmatch(code), f'{code} is not a shelf code'
    for code in products:
        assert len(code) == 13 and code.isdigit(), f'{code} is not a barcode'

    # Every printed code answers, in each of the two sandboxes.
    for token in tokens:
        for code in shelves:
            scanned = client.get(f'/api/v1/labels/scan/{code}', headers=_auth(token))
            assert scanned.status_code == 200, f'{code}: {scanned.text}'
            body = scanned.json()
            assert body['status'] == 'storage_context'
            assert body['location'], f'{code} names no shelf'
        for code in products:
            scanned = client.get(f'/api/v1/labels/scan/{code}', headers=_auth(token))
            assert scanned.status_code == 200, f'{code}: {scanned.text}'
            body = scanned.json()
            # The product answers — its stock, or the catalogue's card when
            # no record of it stands on a shelf — never SCAN_UNRECOGNIZED.
            assert body['label_code'] == code
            assert body['status'] in ('product_stock', 'unassigned'), code
            assert body['stock_summary']['template'], code


def test_outside_a_demo_the_sheet_is_not_there(
    client, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The route's own gate, not the stack's ambient mode: set the flag the
    # way the demo fixture sets it, so this answers the same on a demo
    # stack as anywhere else.
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', False)
    response = client.get(SHEET, headers=auth_headers)
    assert response.status_code == 404, response.text
