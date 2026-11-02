"""The paper pick list says what the pick screen says, in the same order.

A dispatch and a session over several dispatches each print their lines by
the walk: the shelf code first, then quantity, unit and product, and the
Code128 of every document. The order is the one the session's screen gives,
and a dispatch nobody has started picking is walked through the same
function.
"""

import io
import re
import uuid
from decimal import Decimal
from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.document_pdf_service import build_pick_list_context
from app.modules.warehouse.models import Document
from app.modules.warehouse.tests.integration._records import sow

_API = '/api/v1/warehouse'


def _shelf(
    db: Session,
    org: Organization,
    user: User,
    code: str,
    sequence: int,
    parent: StorageLocation | None = None,
) -> StorageLocation:
    shelf = StorageLocation(
        name=f'Shelf {code}',
        short_code=code,
        sequence=sequence,
        parent_id=parent.id if parent else None,
        storage_type_id=parent.storage_type_id if parent else None,
        organization_id=org.id,
        created_by=user.id,
    )
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    return shelf


def _dispatch(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    source: StorageLocation,
    lines: list[dict[str, str | int]],
) -> str:
    resp = client.post(
        f'{_API}/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(source.id),
            'lines': lines,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


def _confirmed(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    source: StorageLocation,
    lines: list[dict[str, str | int]],
) -> uuid.UUID:
    doc_id = _dispatch(client, headers, partner, source, lines)
    resp = client.patch(f'{_API}/documents/{doc_id}/confirm', headers=headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return uuid.UUID(doc_id)


def _printed(client: TestClient, headers: dict[str, str], url: str) -> str:
    resp = client.get(url, headers=headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text[:300]
    assert resp.headers['content-type'] == 'application/pdf'
    return '\n'.join(
        page.extract_text() for page in PdfReader(io.BytesIO(resp.content)).pages
    )


def _walk_of(text: str) -> list[str]:
    """The shelf codes in the order the sheet first prints them.

    A row says its shelf twice — the code, and the name beside it.
    """
    return list(dict.fromkeys(re.findall(r'\b[A-C]-0[1-9]\b', text)))


def _screen_of(session: dict[str, list[dict[str, str | int]]]) -> list[str]:
    """The shelf codes in the order the session's screen lists its lines."""
    return [
        str(line['location_code'])
        for line in sorted(session['lines'], key=lambda ln: int(ln['pick_order']))
    ]


@pytest.fixture
def zone_dispatch(
    client: TestClient,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
    doc_user: User,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_template: ProductTemplate,
    doc_source_location: StorageLocation,
) -> str:
    """A draft dispatch of 7 from a zone whose older stock is on the far shelf.

    Drawn in FIFO order the far shelf (A-07) comes first; the walk reaches
    the near one (C-01) first, and neither order is the alphabetical one.
    """
    doc_template.removal_strategy = 'FIFO'
    db_session.commit()
    far = _shelf(db_session, doc_org, doc_user, 'A-07', 2, doc_source_location)
    near = _shelf(db_session, doc_org, doc_user, 'C-01', 1, doc_source_location)
    oldest = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        doc_template,
        far.id,
        '6',
        backdate_days=30,
    )
    sow(db_session, async_engine_fixture, doc_org, doc_template, near.id, '5')
    return _dispatch(
        client,
        doc_auth_headers,
        doc_partner,
        doc_source_location,
        [
            {
                'item_id': str(oldest.id),
                'product_template_id': str(doc_template.id),
                'expected_quantity': 7,
            }
        ],
    )


@pytest.mark.integration
class TestAPickListPrintsInWalkOrder:
    def test_a_dispatch_prints_its_lines_in_the_order_its_session_walks(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        zone_dispatch: str,
    ) -> None:
        client.patch(
            f'{_API}/documents/{zone_dispatch}/confirm', headers=doc_auth_headers
        )

        paper = _printed(
            client, doc_auth_headers, f'{_API}/documents/{zone_dispatch}/pick-list'
        )

        started = client.post(
            f'{_API}/documents/{zone_dispatch}/picking/start',
            headers=doc_auth_headers,
        )
        assert started.status_code == status.HTTP_201_CREATED, started.text
        assert _screen_of(started.json()) == ['C-01', 'A-07']
        assert _walk_of(paper) == ['C-01', 'A-07']
        assert 'Pick List' in paper

    def test_a_session_over_several_dispatches_prints_the_screens_order(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
    ) -> None:
        # Alphabetically A, B, C — numbered so the walk is C, A, B.
        ids = []
        for code, seq in (('B-01', 30), ('C-01', 10), ('A-01', 20)):
            shelf = _shelf(db_session, doc_org, doc_user, code, seq)
            item = Item(
                name=f'Product on {code}',
                organization_id=doc_org.id,
                storage_location_id=shelf.id,
                quantity=Decimal('10'),
            )
            db_session.add(item)
            db_session.commit()
            ids.append(
                _confirmed(
                    client,
                    doc_auth_headers,
                    doc_partner,
                    shelf,
                    [{'item_id': str(item.id), 'expected_quantity': 1}],
                )
            )
        started = client.post(
            f'{_API}/picking/start',
            headers=doc_auth_headers,
            json={'document_ids': [str(i) for i in ids]},
        )
        assert started.status_code == status.HTTP_201_CREATED, started.text
        session = started.json()
        assert _screen_of(session) == ['C-01', 'A-01', 'B-01']

        paper = _printed(
            client,
            doc_auth_headers,
            f'{_API}/documents/{ids[2]}/picking/{session["id"]}/pick-list',
        )

        assert _walk_of(paper) == ['C-01', 'A-01', 'B-01']
        # Every document of the session is on the sheet, with its number.
        for line in session['lines']:
            assert line['document_number'] in paper

    def test_a_dispatch_not_confirmed_has_no_pick_list(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        zone_dispatch: str,
    ) -> None:
        listed = client.get(
            f'{_API}/documents/{zone_dispatch}/pick-list', headers=doc_auth_headers
        )

        assert listed.status_code == status.HTTP_400_BAD_REQUEST, listed.text
        assert 'not confirmed' in listed.json()['detail']['message']

    def test_the_organizations_own_pick_list_template_wins(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        zone_dispatch: str,
    ) -> None:
        created = client.post(
            f'{_API}/templates',
            headers=doc_auth_headers,
            json={
                'module': 'warehouse',
                'name': 'Our pick list',
                'document_type': 'PICK_LIST',
                'is_default': True,
                'body_html': (
                    '<p>{% for line in pick_lines %}SHELF {{ line.shelf_code }} '
                    '{% endfor %}</p>'
                ),
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        client.patch(
            f'{_API}/documents/{zone_dispatch}/confirm', headers=doc_auth_headers
        )

        paper = _printed(
            client, doc_auth_headers, f'{_API}/documents/{zone_dispatch}/pick-list'
        )

        assert 'SHELF C-01 SHELF A-07' in paper


def test_every_document_of_the_sheet_carries_its_scannable_code() -> None:
    documents = [Document(number='OUT/2026/001'), Document(number='OUT/2026/002')]

    context = build_pick_list_context(documents, [], 'en', None)

    assert [d['number'] for d in context['documents']] == [
        'OUT/2026/001',
        'OUT/2026/002',
    ]
    assert all(d['code128_img'].startswith('data:image') for d in context['documents'])
    assert all(d['code128_width_mm'] > 0 for d in context['documents'])
