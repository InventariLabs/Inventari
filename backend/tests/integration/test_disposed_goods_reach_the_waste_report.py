"""Disposed goods answer the one question the waste report exists for.

The remove-from-stock window used to file every exit as USED — the discard
endpoint existed and nobody called it — so ``total_wasted`` read 0.00 over a
bin holding 26.00 worth of stock, and the journal's verb said "Use" beside
the word "DISPOSED".
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.stock_valuation_layer import StockValuationLayer

pytestmark = pytest.mark.integration


def _buy(
    client: TestClient,
    headers: dict[str, str],
    storage_id: Any,
    *,
    name: str,
    quantity: str,
    price: str,
) -> str:
    response = client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': name,
            'quantity': quantity,
            'purchase_price': price,
            'location_id': str(storage_id),
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return str(response.json()['id'])


def _discard(
    client: TestClient,
    headers: dict[str, str],
    item_id: str,
    quantity: str,
    reason: str = 'DISPOSED',
) -> None:
    response = client.patch(
        f'/api/v1/items/{item_id}/discard',
        headers=headers,
        json={'quantity': quantity, 'reason': reason},
    )
    assert response.status_code == status.HTTP_200_OK, response.text


def _get(client: TestClient, headers: dict[str, str], path: str) -> Any:
    response = client.get(path, headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


class TestDisposedGoodsReachTheWasteReport:
    def test_stock_thrown_out_is_worth_what_it_cost(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location,
    ) -> None:
        item_id = _buy(
            client,
            auth_headers,
            test_storage_location.id,
            name='Yoghurt',
            quantity='4',
            price='6.50',
        )

        _discard(client, auth_headers, item_id, '4')

        summary = _get(client, auth_headers, '/api/v1/stats/cost-analysis')
        assert summary['total_wasted'] == pytest.approx(26.0, abs=0.01)

    def test_the_ledger_and_the_journal_name_a_disposal_a_disposal(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location,
        db_session: Session,
    ) -> None:
        org_id = test_storage_location.organization_id
        item_id = _buy(
            client,
            auth_headers,
            test_storage_location.id,
            name='Yoghurt',
            quantity='4',
            price='6.50',
        )

        _discard(client, auth_headers, item_id, '4')
        db_session.expire_all()

        out_layer = db_session.scalar(
            select(StockValuationLayer).where(
                StockValuationLayer.organization_id == org_id,
                StockValuationLayer.direction == 'OUT',
            )
        )
        assert out_layer is not None
        assert out_layer.reason == 'DISPOSED'

        entry = db_session.scalar(
            select(AuditLog).where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'item',
                AuditLog.target_id == item_id,
                # item creation logs a CREATE of its own; the outflow is the
                # entry this test is about
                AuditLog.action.in_(['USE', 'DISPOSE']),
            )
        )
        assert entry is not None
        assert entry.action == 'DISPOSE'
