"""A module keeps its own fields on a document and its lines.

A field one customer needs on a line — a certificate number, a customs code —
is not a column of the warehouse's table. It lives in the line's (or the
document's) ``meta_data``, under the name of the module that owns it. The
document endpoints write it, one module's write leaves the others' keys
alone, the pre-post check reads it, and a correction, a return or a backorder
carries it from the document it continues.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.core.contracts import DocumentToPostDTO
from app.core.interceptors import InterceptorError
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models import Document, DocumentStatus
from app.modules.warehouse.warehouse_api import warehouse_api
from tests.integration._shelf import run_in_async_session

_MODULE = 'lot_certificates'


class _RequiresCertificate:
    """A module that will not let a receipt line be confirmed without its field."""

    def __init__(self) -> None:
        self.seen: list[DocumentToPostDTO] = []

    async def __call__(self, db: Any, org_id: UUID, doc: DocumentToPostDTO) -> None:
        self.seen.append(doc)
        if doc.stage != 'confirm':
            return
        missing = [
            line.line_number
            for line in doc.lines
            if not line.meta_data.get(_MODULE, {}).get('certificate')
        ]
        if missing:
            raise InterceptorError(
                f'Certificate number missing on line {missing[0]}',
                error_code='CERTIFICATE_MISSING',
            )


@pytest.fixture
def requires_certificate(
    db_session: Session, doc_org: Organization
) -> Iterator[_RequiresCertificate]:
    doc_org.enabled_modules = [*doc_org.enabled_modules, _MODULE]
    db_session.commit()
    check = _RequiresCertificate()
    warehouse_api.register_pre_post_check(_MODULE, check)
    yield check

    # The registry is process-wide; leave the module with nothing to refuse.
    async def _passes(db: Any, org_id: UUID, doc: DocumentToPostDTO) -> None:
        return None

    warehouse_api.register_pre_post_check(_MODULE, _passes)


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    shelf: StorageLocation,
    item: Item,
    *,
    line_meta: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    quantity: int = 5,
) -> dict[str, Any]:
    line: dict[str, Any] = {'item_id': str(item.id), 'expected_quantity': quantity}
    if line_meta is not None:
        line['meta_data'] = line_meta
    body: dict[str, Any] = {
        'type': 'IN',
        'partner_id': str(partner.id),
        'target_location_id': str(shelf.id),
        'lines': [line],
    }
    if meta is not None:
        body['meta_data'] = meta
    created = client.post('/api/v1/warehouse/documents', headers=headers, json=body)
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return cast(dict[str, Any], created.json())


def _posted_receipt(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    shelf: StorageLocation,
    item: Item,
) -> dict[str, Any]:
    doc = _receipt(
        client,
        headers,
        partner,
        shelf,
        item,
        line_meta={_MODULE: {'certificate': 'C-1'}},
        meta={'customs': {'entry': 'PL-77'}},
    )
    posted = client.post(
        f'/api/v1/warehouse/documents/{doc["id"]}/post', headers=headers
    )
    assert posted.status_code == status.HTTP_200_OK, posted.text
    return cast(dict[str, Any], posted.json())


@pytest.mark.integration
class TestAModuleKeepsItsOwnFieldsOnADocument:
    def test_create_keeps_the_fields_on_the_header_and_the_lines(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_item,
            line_meta={_MODULE: {'certificate': 'C-1'}},
            meta={'customs': {'entry': 'PL-77'}},
        )

        read = client.get(
            f'/api/v1/warehouse/documents/{doc["id"]}', headers=doc_auth_headers
        )

        assert read.status_code == status.HTTP_200_OK
        assert read.json()['meta_data'] == {'customs': {'entry': 'PL-77'}}
        assert read.json()['lines'][0]['meta_data'] == {_MODULE: {'certificate': 'C-1'}}

    def test_a_field_outside_a_modules_key_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                        'meta_data': {'certificate': 'C-1'},
                    }
                ],
            },
        )

        assert created.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_editing_a_draft_keeps_what_the_form_sends_back(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )

        updated = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}',
            headers=doc_auth_headers,
            json={
                'meta_data': {'customs': {'entry': 'PL-78'}},
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 6,
                        'meta_data': {_MODULE: {'certificate': 'C-2'}},
                    }
                ],
            },
        )

        assert updated.status_code == status.HTTP_200_OK, updated.text
        assert updated.json()['meta_data'] == {'customs': {'entry': 'PL-78'}}
        assert updated.json()['lines'][0]['meta_data'] == {
            _MODULE: {'certificate': 'C-2'}
        }

    def test_one_modules_write_leaves_another_modules_key(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_item,
            line_meta={'grading': {'grade': 'A'}},
            meta={'customs': {'entry': 'PL-77'}},
        )
        line_id = doc['lines'][0]['id']

        on_line = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}/lines/{line_id}/meta-data/{_MODULE}',
            headers=doc_auth_headers,
            json={'certificate': 'C-1'},
        )
        on_header = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}/meta-data/{_MODULE}',
            headers=doc_auth_headers,
            json={'checked_by': 'Ann'},
        )

        assert on_line.status_code == status.HTTP_200_OK, on_line.text
        assert on_header.status_code == status.HTTP_200_OK, on_header.text
        assert on_header.json()['lines'][0]['meta_data'] == {
            'grading': {'grade': 'A'},
            _MODULE: {'certificate': 'C-1'},
        }
        assert on_header.json()['meta_data'] == {
            'customs': {'entry': 'PL-77'},
            _MODULE: {'checked_by': 'Ann'},
        }

        cleared = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}/lines/{line_id}/meta-data/{_MODULE}',
            headers=doc_auth_headers,
            json={},
        )

        assert cleared.json()['lines'][0]['meta_data'] == {'grading': {'grade': 'A'}}

    def test_a_line_of_another_document_is_not_found(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        first = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        second = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )

        written = client.put(
            f'/api/v1/warehouse/documents/{first["id"]}/lines/'
            f'{second["lines"][0]["id"]}/meta-data/{_MODULE}',
            headers=doc_auth_headers,
            json={'certificate': 'C-1'},
        )

        assert written.status_code == status.HTTP_404_NOT_FOUND

    def test_the_check_refuses_a_confirm_until_the_field_is_filled(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        requires_certificate: _RequiresCertificate,
    ) -> None:
        doc = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        line_id = doc['lines'][0]['id']

        refused = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )

        assert refused.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert refused.json()['detail']['code'] == 'CERTIFICATE_MISSING'

        filled = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}/lines/{line_id}/meta-data/{_MODULE}',
            headers=doc_auth_headers,
            json={'certificate': 'C-1'},
        )
        assert filled.status_code == status.HTTP_200_OK, filled.text
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )

        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        asked = requires_certificate.seen[-1]
        assert asked.lines[0].meta_data == {_MODULE: {'certificate': 'C-1'}}

    def test_the_check_reads_the_documents_own_fields(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        requires_certificate: _RequiresCertificate,
    ) -> None:
        _posted_receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )

        assert [seen.stage for seen in requires_certificate.seen] == [
            'confirm',
            'post',
        ]
        assert requires_certificate.seen[-1].meta_data == {
            'customs': {'entry': 'PL-77'}
        }

    def test_the_fields_close_with_the_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc = _posted_receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )

        written = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}/meta-data/{_MODULE}',
            headers=doc_auth_headers,
            json={'certificate': 'C-9'},
        )

        assert written.status_code == status.HTTP_400_BAD_REQUEST
        assert 'can no longer change' in written.json()['detail']['message']

    def test_an_undo_carries_the_fields_of_what_it_takes_back(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc = _posted_receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )

        undone = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/undo', headers=doc_auth_headers
        )

        assert undone.status_code == status.HTTP_200_OK, undone.text
        assert undone.json()['meta_data'] == {'customs': {'entry': 'PL-77'}}
        assert undone.json()['lines'][0]['meta_data'] == {
            _MODULE: {'certificate': 'C-1'}
        }

    def test_a_correction_and_a_return_carry_the_fields(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc = _posted_receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )

        corrected = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': doc['id'],
                'reason_code': 'WRONG_QUANTITY',
                'lines': [{'original_line_number': 1, 'quantity_delta': -1}],
            },
        )
        returned = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 1}],
            },
        )

        for made in (corrected, returned):
            assert made.status_code == status.HTTP_201_CREATED, made.text
            assert made.json()['meta_data'] == {'customs': {'entry': 'PL-77'}}
            assert made.json()['lines'][0]['meta_data'] == {
                _MODULE: {'certificate': 'C-1'}
            }

    def test_a_duplicate_carries_the_fields(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_item,
            line_meta={_MODULE: {'certificate': 'C-1'}},
            meta={'customs': {'entry': 'PL-77'}},
        )

        copied = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/duplicate',
            headers=doc_auth_headers,
        )

        assert copied.status_code == status.HTTP_201_CREATED, copied.text
        assert copied.json()['id'] != doc['id']
        assert copied.json()['meta_data'] == {'customs': {'entry': 'PL-77'}}
        assert copied.json()['lines'][0]['meta_data'] == {
            _MODULE: {'certificate': 'C-1'}
        }

    def test_a_backorder_carries_the_fields_of_the_rest(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_item,
            line_meta={_MODULE: {'certificate': 'C-1'}},
            meta={'customs': {'entry': 'PL-77'}},
            quantity=10,
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )

        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': doc['lines'][0]['id'],
                        'done_quantity': 7,
                        'discrepancy_code': 'SHORTAGE',
                        'discrepancy_reason': 'Only 7 delivered',
                    }
                ]
            },
        )

        assert completed.status_code == status.HTTP_200_OK, completed.text
        backorder_id = completed.json()['generated_backorder_id']
        backorder = client.get(
            f'/api/v1/warehouse/documents/{backorder_id}', headers=doc_auth_headers
        ).json()
        assert backorder['meta_data'] == {'customs': {'entry': 'PL-77'}}
        assert backorder['lines'][0]['meta_data'] == {_MODULE: {'certificate': 'C-1'}}

    def test_a_module_writes_its_fields_through_the_warehouse_api(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        doc_id = UUID(doc['id'])
        line_id = UUID(doc['lines'][0]['id'])

        async def _write(session: AsyncSession) -> None:
            await warehouse_api.set_module_meta_data_async(
                session, doc_org.id, doc_id, _MODULE, {'checked': True}, doc_user.id
            )
            await warehouse_api.set_module_meta_data_async(
                session,
                doc_org.id,
                doc_id,
                _MODULE,
                {'certificate': 'C-1'},
                doc_user.id,
                line_id=line_id,
            )

        run_in_async_session(async_engine_fixture, _write)

        stored = db_session.get(Document, doc_id)
        assert stored is not None
        assert stored.status == DocumentStatus.DRAFT.value
        assert stored.meta_data == {_MODULE: {'checked': True}}
        assert stored.lines[0].meta_data == {_MODULE: {'certificate': 'C-1'}}
