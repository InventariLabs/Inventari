"""A skipped pick line is answered as skipped, and its summary opens for anyone.

Scanning the product of a line the picker put off used to answer "already
picked: 0 of 2", straight above a card that says Skipped and offers Undo skip.
Nothing was picked of it. The scan now says the line was skipped.

The summary a skip of the last line leaves behind is handed to whoever opens
it again, so a colleague who finds the dispatch finished can take the skip
back or answer it, instead of meeting "now held by" on those buttons.
"""

import uuid
from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import WmsPickSession
from app.modules.warehouse.tests.integration._records import sow as _sow

pytestmark = pytest.mark.integration

_DOCS = '/api/v1/warehouse/documents'


@pytest.fixture
def dispatch(
    h: ModuleTestHelper,
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_template: ProductTemplate,
    doc_org: Organization,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
) -> dict[str, object]:
    """A confirmed dispatch of two products, a session open over it."""
    other = h.create_template(doc_org, name='Second Product', barcode='5901234123464')
    lines = []
    for template in (doc_template, other):
        record = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            template,
            doc_source_location.id,
            '20',
        )
        lines.append(
            {
                'item_id': str(record.id),
                'product_template_id': str(template.id),
                'expected_quantity': 2,
            }
        )
    created = client.post(
        _DOCS,
        headers=doc_auth_headers,
        json={
            'type': 'OUT',
            'partner_id': str(doc_partner.id),
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
            'lines': lines,
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = cast(str, created.json()['id'])
    confirmed = client.patch(f'{_DOCS}/{doc_id}/confirm', headers=doc_auth_headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    session = client.post(f'{_DOCS}/{doc_id}/picking/start', headers=doc_auth_headers)
    assert session.status_code == status.HTTP_201_CREATED, session.text
    by_barcode = {line['product_name']: line['id'] for line in session.json()['lines']}
    return {
        'doc_id': doc_id,
        'session_id': session.json()['id'],
        'first': by_barcode[doc_template.name],
        'second': by_barcode[other.name],
    }


def _skip(
    client: TestClient, headers: dict[str, str], d: dict[str, object], key: str
) -> None:
    resp = client.post(
        f'{_DOCS}/{d["doc_id"]}/picking/{d["session_id"]}/skip',
        headers=headers,
        params={'line_id': d[key]},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


def test_scanning_a_skipped_product_says_it_was_skipped(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_template: ProductTemplate,
    dispatch: dict[str, object],
) -> None:
    _skip(client, doc_auth_headers, dispatch, 'first')

    scan = client.post(
        f'{_DOCS}/{dispatch["doc_id"]}/picking/{dispatch["session_id"]}/scan',
        headers=doc_auth_headers,
        json={'barcode': doc_template.barcode},
    )

    assert scan.status_code == status.HTTP_200_OK, scan.text
    assert scan.json()['status'] == 'line_skipped'
    assert scan.json()['line_id'] == dispatch['first']
    assert scan.json()['picked_quantity'] == 0


def test_scanning_a_picked_product_still_says_already_picked(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_template: ProductTemplate,
    dispatch: dict[str, object],
) -> None:
    base = f'{_DOCS}/{dispatch["doc_id"]}/picking/{dispatch["session_id"]}'
    picked = client.post(
        f'{base}/scan',
        headers=doc_auth_headers,
        json={'barcode': doc_template.barcode, 'quantity': 2},
    )
    assert picked.json()['status'] == 'picked', picked.text

    again = client.post(
        f'{base}/scan',
        headers=doc_auth_headers,
        json={'barcode': doc_template.barcode},
    )

    assert again.json()['status'] == 'already_picked'


def test_a_colleague_opening_the_finished_summary_can_take_the_skip_back(
    h: ModuleTestHelper,
    client: TestClient,
    db_session: Session,
    doc_org: Organization,
    doc_auth_headers: dict[str, str],
    doc_template: ProductTemplate,
    dispatch: dict[str, object],
) -> None:
    base = f'{_DOCS}/{dispatch["doc_id"]}/picking/{dispatch["session_id"]}'
    picked = client.post(
        f'{base}/scan',
        headers=doc_auth_headers,
        json={'barcode': doc_template.barcode, 'quantity': 2},
    )
    assert picked.json()['status'] == 'picked', picked.text
    _skip(client, doc_auth_headers, dispatch, 'second')
    colleague = h.create_user(doc_org, email='colleague@example.com')
    colleague_headers = h.get_auth_headers(colleague)

    # The summary a skip of the last line left behind, opened by someone else.
    start = client.post(
        f'{_DOCS}/{dispatch["doc_id"]}/picking/start', headers=colleague_headers
    )
    assert start.status_code == status.HTTP_201_CREATED, start.text
    assert start.json()['id'] == dispatch['session_id']
    undo = client.post(
        f'{base}/undo',
        headers=colleague_headers,
        params={'line_id': dispatch['second']},
    )

    assert undo.status_code == status.HTTP_200_OK, undo.text
    db_session.expire_all()
    session = db_session.get(
        WmsPickSession, uuid.UUID(cast(str, dispatch['session_id']))
    )
    assert session is not None
    assert session.status == 'active'
    assert session.assigned_to == colleague.id


def test_a_colleague_can_answer_the_skipped_line_on_the_summary(
    h: ModuleTestHelper,
    client: TestClient,
    doc_org: Organization,
    doc_auth_headers: dict[str, str],
    doc_template: ProductTemplate,
    dispatch: dict[str, object],
) -> None:
    base = f'{_DOCS}/{dispatch["doc_id"]}/picking/{dispatch["session_id"]}'
    client.post(
        f'{base}/scan',
        headers=doc_auth_headers,
        json={'barcode': doc_template.barcode, 'quantity': 2},
    )
    _skip(client, doc_auth_headers, dispatch, 'second')
    colleague_headers = h.get_auth_headers(
        h.create_user(doc_org, email='colleague@example.com')
    )
    client.post(
        f'{_DOCS}/{dispatch["doc_id"]}/picking/start', headers=colleague_headers
    )

    answer = client.post(
        f'{base}/short-pick',
        headers=colleague_headers,
        json={
            'line_id': dispatch['second'],
            'picked_quantity': 0,
            'discrepancy_code': 'OTHER',
        },
    )

    assert answer.status_code == status.HTTP_200_OK, answer.text
    assert answer.json()['status'] == 'short_pick_confirmed'


def test_completing_with_a_skipped_line_unanswered_is_refused_even_as_planned(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_template: ProductTemplate,
    dispatch: dict[str, object],
) -> None:
    base = f'{_DOCS}/{dispatch["doc_id"]}/picking/{dispatch["session_id"]}'
    client.post(
        f'{base}/scan',
        headers=doc_auth_headers,
        json={'barcode': doc_template.barcode, 'quantity': 2},
    )
    _skip(client, doc_auth_headers, dispatch, 'second')

    completed = client.patch(
        f'{_DOCS}/{dispatch["doc_id"]}/complete',
        headers=doc_auth_headers,
        json={'complete_as_planned': True},
    )

    assert completed.status_code == status.HTTP_400_BAD_REQUEST, completed.text
    assert '2' in completed.json()['detail']['message']
    doc = client.get(f'{_DOCS}/{dispatch["doc_id"]}', headers=doc_auth_headers).json()
    assert doc['status'] == 'CONFIRMED'
