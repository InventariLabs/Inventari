"""A module narrows the documents list by its own fields, on the server.

A module that keeps a certificate number on each receipt line knows what
"the receipts whose certificates lapse this month" means; the warehouse does
not. It registers a filter whose provider answers which of its own fields a
line must carry, and the list narrows to the documents that have such a line
— with the count and the paging the server keeps, which a filter run over the
page in the reader's hands would get wrong.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.contracts import DocumentFilterDTO
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.modules.warehouse.warehouse_api import warehouse_api

_MODULE = 'customs_codes'
_URL = '/api/v1/warehouse/documents'


class _Answer:
    """The provider: what it was asked, and what it answers this time."""

    def __init__(self) -> None:
        self.answer = DocumentFilterDTO(line_meta_data=[{}])
        self.asked: list[UUID] = []

    async def __call__(self, db: Any, org_id: UUID) -> DocumentFilterDTO:
        self.asked.append(org_id)
        return self.answer


@pytest.fixture
def provider(db_session: Session, doc_org: Organization) -> Iterator[_Answer]:
    doc_org.enabled_modules = [*doc_org.enabled_modules, _MODULE]
    db_session.commit()
    answer = _Answer()
    warehouse_api.register_document_filter(_MODULE, 'entered', answer)
    yield answer
    # The registry is process-wide; leave the name answering nothing.
    nothing = _Answer()
    nothing.answer = DocumentFilterDTO(line_meta_data=[])
    warehouse_api.register_document_filter(_MODULE, 'entered', nothing)


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    shelf: StorageLocation,
    item: Item,
    line_meta: dict[str, Any] | None,
    batch: str | None = None,
) -> str:
    line: dict[str, Any] = {'item_id': str(item.id), 'expected_quantity': 1}
    if line_meta is not None:
        line['meta_data'] = line_meta
    if batch is not None:
        line['batch_number'] = batch
    created = client.post(
        _URL,
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(shelf.id),
            'lines': [line],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return str(created.json()['id'])


@pytest.fixture
def receipts(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_target_location: StorageLocation,
    doc_item: Item,
) -> dict[str, str]:
    """Four drafts: two with the module's field, one with another module's, one bare."""

    def make(meta: dict[str, Any] | None) -> str:
        return _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_item,
            meta,
        )

    return {
        'pl': make({_MODULE: {'entry': 'PL-1'}}),
        'de': make({_MODULE: {'entry': 'DE-7'}}),
        # The same field under another module's name is not this module's.
        'other': make({'lot_certificates': {'entry': 'PL-1'}}),
        'none': make(None),
    }


def _listed(
    client: TestClient, headers: dict[str, str], *filters: str
) -> tuple[set[str], int]:
    response = client.get(
        _URL, headers=headers, params={'module_filter': list(filters), 'limit': 50}
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    body = response.json()
    return {row['id'] for row in body['items']}, body['total']


@pytest.mark.integration
class TestAModuleFiltersTheDocumentsList:
    def test_any_line_the_module_wrote_to_keeps_its_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        provider: _Answer,
        receipts: dict[str, str],
        doc_org: Organization,
    ) -> None:
        ids, total = _listed(client, doc_auth_headers, f'{_MODULE}:entered')

        assert ids == {receipts['pl'], receipts['de']}
        assert total == 2
        assert provider.asked == [doc_org.id]

    def test_the_fields_it_answers_narrow_to_the_lines_that_carry_them(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        provider: _Answer,
        receipts: dict[str, str],
    ) -> None:
        provider.answer = DocumentFilterDTO(line_meta_data=[{'entry': 'PL-1'}])

        ids, total = _listed(client, doc_auth_headers, f'{_MODULE}:entered')

        # 'other' carries the same value under another module's name.
        assert ids == {receipts['pl']}
        assert total == 1

    def test_a_filter_for_lots_counts_only_the_lines_that_carry_one(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        provider: _Answer,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """A certificate rule checks the lines with a batch, and the filter
        that lists "certified" documents kept any line carrying a filed number
        — a non-lot line with one listed its document as certified."""

        def make(batch: str | None) -> str:
            return _receipt(
                client,
                doc_auth_headers,
                doc_partner,
                doc_target_location,
                doc_item,
                {_MODULE: {'entry': 'PL-1'}},
                batch,
            )

        lot, loose, blank = make('LOT-1'), make(None), make('')
        provider.answer = DocumentFilterDTO(
            line_meta_data=[{'entry': 'PL-1'}], lots_only=True
        )

        ids, total = _listed(client, doc_auth_headers, f'{_MODULE}:entered')

        assert ids == {lot}, {'loose': loose in ids, 'blank': blank in ids}
        assert total == 1

    def test_an_empty_answer_lists_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        provider: _Answer,
        receipts: dict[str, str],
    ) -> None:
        provider.answer = DocumentFilterDTO(line_meta_data=[])

        assert _listed(client, doc_auth_headers, f'{_MODULE}:entered') == (set(), 0)

    def test_a_filter_of_a_disabled_module_is_refused_not_dropped(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        provider: _Answer,
        receipts: dict[str, str],
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        doc_org.enabled_modules = [m for m in doc_org.enabled_modules if m != _MODULE]
        db_session.commit()

        response = client.get(
            _URL,
            headers=doc_auth_headers,
            params={'module_filter': f'{_MODULE}:entered'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        assert response.json()['detail']['field'] == 'module_filter'
        assert response.json()['detail']['code'] == 'DOCUMENT_FILTER_UNKNOWN'
        assert provider.asked == []

    def test_a_name_nothing_registered_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        provider: _Answer,
    ) -> None:
        response = client.get(
            _URL,
            headers=doc_auth_headers,
            params={'module_filter': f'{_MODULE}:nothing'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
