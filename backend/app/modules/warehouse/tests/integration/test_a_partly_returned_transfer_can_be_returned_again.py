"""What is left of a transfer that was partly returned can be returned or undone.

A transfer moves the record its line names to the target shelf. Returning
part of it moves that same record back and leaves the rest on the target
shelf under a record of its own, so the line's record no longer stands where
the goods are. A later return, or an undo of the transfer, has to take the
rest from the record that does.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.stock_ledger_total import StockLedgerTotal
from app.models.storage_location import StorageLocation

API = '/api/v1/warehouse'


def _complete(
    client: TestClient, headers: dict[str, str], document_id: str
) -> dict[str, Any]:
    confirmed = client.patch(f'{API}/documents/{document_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    completed = client.patch(
        f'{API}/documents/{document_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text
    body: dict[str, Any] = completed.json()
    return body


def _transfer(
    client: TestClient,
    headers: dict[str, str],
    source: StorageLocation,
    target: StorageLocation,
    item: Item,
    quantity: str,
) -> str:
    created = client.post(
        f'{API}/documents',
        headers=headers,
        json={
            'type': 'INT',
            'source_location_id': str(source.id),
            'target_location_id': str(target.id),
            'lines': [{'item_id': str(item.id), 'expected_quantity': quantity}],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    document_id: str = created.json()['id']
    _complete(client, headers, document_id)
    return document_id


def _return_and_complete(
    client: TestClient, headers: dict[str, str], document_id: str, quantity: str
) -> None:
    created = client.post(
        f'{API}/documents/{document_id}/return',
        headers=headers,
        json={
            'reason_code': 'DAMAGED',
            'lines': [{'original_line_number': 1, 'return_quantity': quantity}],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    _complete(client, headers, created.json()['id'])


def _on_shelf(db: Session, item: Item, location: StorageLocation) -> Decimal:
    db.expire_all()
    total = db.scalar(
        select(func.sum(Item.quantity)).where(
            Item.template_id == item.template_id,
            Item.storage_location_id == location.id,
        )
    )
    return Decimal(str(total or 0))


def _ledger(db: Session, item: Item, location: StorageLocation) -> Decimal:
    total = db.scalar(
        select(StockLedgerTotal.quantity).where(
            StockLedgerTotal.product_template_id == item.template_id,
            StockLedgerTotal.storage_location_id == location.id,
        )
    )
    return Decimal(str(total or 0))


def _shelves_agree_with_the_ledger(
    db: Session,
    item: Item,
    source: StorageLocation,
    target: StorageLocation,
    on_source: str,
    on_target: str,
) -> None:
    assert _on_shelf(db, item, source) == Decimal(on_source)
    assert _on_shelf(db, item, target) == Decimal(on_target)
    assert _ledger(db, item, source) == Decimal(on_source)
    assert _ledger(db, item, target) == Decimal(on_target)


@pytest.mark.integration
def test_the_rest_of_a_partly_returned_transfer_can_be_returned(
    client: TestClient,
    db_session: Session,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_stock_item: Item,
) -> None:
    transfer_id = _transfer(
        client,
        doc_auth_headers,
        doc_source_location,
        doc_target_location,
        doc_stock_item,
        '5',
    )
    _return_and_complete(client, doc_auth_headers, transfer_id, '2')
    _shelves_agree_with_the_ledger(
        db_session, doc_stock_item, doc_source_location, doc_target_location, '97', '3'
    )

    _return_and_complete(client, doc_auth_headers, transfer_id, '3')

    _shelves_agree_with_the_ledger(
        db_session, doc_stock_item, doc_source_location, doc_target_location, '100', '0'
    )


@pytest.mark.integration
def test_a_partly_returned_transfer_is_undone_on_both_shelves(
    client: TestClient,
    db_session: Session,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_stock_item: Item,
) -> None:
    transfer_id = _transfer(
        client,
        doc_auth_headers,
        doc_source_location,
        doc_target_location,
        doc_stock_item,
        '5',
    )
    _return_and_complete(client, doc_auth_headers, transfer_id, '2')

    undone = client.post(
        f'{API}/documents/{transfer_id}/undo', headers=doc_auth_headers
    )

    assert undone.status_code == status.HTTP_200_OK, undone.text
    _shelves_agree_with_the_ledger(
        db_session, doc_stock_item, doc_source_location, doc_target_location, '100', '0'
    )
