"""A line with no price leaves the order without a total, not with a smaller one.

The approval rule has long refused to call such an order "below the limit"
(``po_net_total``), while the card, the list and the lines' footer summed what
they could: 0.00 for an order of unpriced lines, and a partial sum for the rest.
The reader saw an order worth nothing going to approval and could not tell why.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.models.partner import Partner

pytestmark = pytest.mark.integration

URL = '/api/v1/purchase-orders'
TOTALS = ('total_net', 'total_tax', 'total_gross')


def _order(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    made = client.post(
        URL, headers=headers, json={'partner_id': str(partner.id), 'lines': lines}
    )
    assert made.status_code == status.HTTP_201_CREATED, made.text
    return cast(dict[str, Any], made.json())


def _row(client: TestClient, headers: dict[str, str], po_id: str) -> dict[str, Any]:
    listing = client.get(URL, headers=headers)
    assert listing.status_code == status.HTTP_200_OK, listing.text
    return next(row for row in listing.json()['items'] if row['id'] == po_id)


@pytest.mark.parametrize(
    'lines',
    [
        [{'name': 'Yoghurt', 'quantity_ordered': 2}],
        [
            {'name': 'Yoghurt', 'quantity_ordered': 2},
            {'name': 'Plums', 'quantity_ordered': 3, 'unit_price': '4.00'},
        ],
    ],
    ids=['no-line-priced', 'one-line-priced'],
)
def test_a_line_without_a_price_leaves_the_total_unknown(
    client: TestClient,
    po_auth_headers: dict[str, str],
    po_partner: Partner,
    lines: list[dict[str, Any]],
) -> None:
    po = _order(client, po_auth_headers, po_partner, lines)
    row = _row(client, po_auth_headers, po['id'])
    card = client.get(f'{URL}/{po["id"]}', headers=po_auth_headers).json()

    for shown in (po, row, card):
        assert [shown[field] for field in TOTALS] == [None, None, None]


def test_a_price_of_zero_is_a_price(
    client: TestClient, po_auth_headers: dict[str, str], po_partner: Partner
) -> None:
    po = _order(
        client,
        po_auth_headers,
        po_partner,
        [{'name': 'Sample', 'quantity_ordered': 2, 'unit_price': '0'}],
    )
    row = _row(client, po_auth_headers, po['id'])

    for shown in (po, row):
        assert Decimal(shown['total_gross']) == 0


def test_every_line_priced_is_a_total(
    client: TestClient, po_auth_headers: dict[str, str], po_partner: Partner
) -> None:
    po = _order(
        client,
        po_auth_headers,
        po_partner,
        [
            {'name': 'Plums', 'quantity_ordered': 3, 'unit_price': '10.00'},
            {
                'name': 'Sugar',
                'quantity_ordered': 1,
                'unit_price': '5.00',
                'tax_rate': '20',
            },
        ],
    )
    row = _row(client, po_auth_headers, po['id'])

    for shown in (po, row):
        assert Decimal(shown['total_net']) == 35
        assert Decimal(shown['total_tax']) == 1
        assert Decimal(shown['total_gross']) == 36
