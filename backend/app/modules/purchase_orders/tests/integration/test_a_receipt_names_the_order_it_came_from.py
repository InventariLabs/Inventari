"""A receipt posted against an order names that order, on its page and its print.

The order lists its receipts; the receipt has to lead back the same way, so
whoever holds the PZ months later reaches the order it was received
against. The link is read from the receipt's lines (``source_po_line_id``),
not from a reference somebody typed.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.modules.warehouse.document_pdf_service import _svc, build_pdf_context
from app.modules.warehouse.models import Document, DocumentLine


def _confirmed_order(
    client: TestClient, headers: dict[str, str], *, partner_id: Any, template_id: Any
) -> dict[str, Any]:
    created = client.post(
        '/api/v1/purchase-orders',
        headers=headers,
        json={
            'partner_id': str(partner_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'quantity_ordered': 8,
                    'unit_price': '2.50',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    po_id = cast(str, created.json()['id'])
    confirmed = client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return cast(dict[str, Any], confirmed.json())


def _post_receipt(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    template_id: Any,
    location_id: Any,
    order_line_id: str | None,
) -> dict[str, Any]:
    line: dict[str, Any] = {
        'product_template_id': str(template_id),
        'expected_quantity': 3,
    }
    if order_line_id is not None:
        line['source_po_line_id'] = order_line_id
    posted = client.post(
        '/api/v1/warehouse/documents/post',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': [line],
        },
    )
    assert posted.status_code == status.HTTP_201_CREATED, posted.text
    return cast(dict[str, Any], posted.json())


def _printed_receipt(*, external_reference: str | None, order_number: str) -> Document:
    """An in-memory receipt carrying the order the read path attaches."""
    doc = Document(
        organization_id=uuid4(),
        type='IN',
        number='PZ/2026/11/0001',
        status='COMPLETED',
        external_reference=external_reference,
    )
    doc.lines.append(
        DocumentLine(
            id=uuid4(),
            name='Coffee',
            quantity=3,
            expected_quantity=3,
            done_quantity=3,
            line_number=1,
        )
    )
    doc.source_orders = [{'id': uuid4(), 'number': order_number}]  # type: ignore[attr-defined]
    return doc


@pytest.mark.integration
class TestAReceiptNamesTheOrderItCameFrom:
    def test_the_receipt_page_reads_the_order_of_its_lines(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        order = _confirmed_order(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        receipt = _post_receipt(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            location_id=po_location.id,
            order_line_id=order['lines'][0]['id'],
        )

        shown = client.get(
            f'/api/v1/warehouse/documents/{receipt["id"]}', headers=po_auth_headers
        )

        assert shown.status_code == status.HTTP_200_OK, shown.text
        assert shown.json()['source_orders'] == [
            {'id': order['id'], 'number': order['number']}
        ]

    def test_a_receipt_without_an_order_names_none(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        receipt = _post_receipt(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            location_id=po_location.id,
            order_line_id=None,
        )

        shown = client.get(
            f'/api/v1/warehouse/documents/{receipt["id"]}', headers=po_auth_headers
        )

        assert shown.json()['source_orders'] == []

    @pytest.mark.parametrize('layout', ['standard.html', 'pl_pz.html'])
    def test_both_printed_layouts_name_the_order(self, layout: str) -> None:
        doc = _printed_receipt(
            external_reference='WZ-778/2026', order_number='PO/2026/11/0001'
        )

        html = _svc.render_filesystem_template(
            layout, build_pdf_context(doc, None, lang='en')
        )

        assert 'PO/2026/11/0001' in html
        assert 'WZ-778/2026' in html, "the supplier's own reference still prints"

    @pytest.mark.parametrize('layout', ['standard.html', 'pl_pz.html'])
    def test_an_order_number_kept_as_the_reference_prints_once(
        self, layout: str
    ) -> None:
        doc = _printed_receipt(
            external_reference='PO/2026/11/0001', order_number='PO/2026/11/0001'
        )

        html = _svc.render_filesystem_template(
            layout, build_pdf_context(doc, None, lang='en')
        )

        assert html.count('PO/2026/11/0001') == 1
