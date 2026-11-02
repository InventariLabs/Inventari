"""Stock is kept in the product's own unit, whatever the line says.

The shelf's quantity and `StockMove` carry a number and no unit. Whose unit it
was depended entirely on which line last wrote to them: a receipt added
`done_quantity` straight to the quant without ever looking at `line.uom_id`,
and the API is happy to accept a unit other than the product's. Receive
500 g of something kept in kilograms and the shelf gains 500 kg — the same
mistake production made before it converted, and the reason it was possible
there too.

The rule is now the one every WMS keeps: the product names one stock unit,
every entry is converted into it, and a unit that cannot be converted is
refused instead of guessed at.

The rule holds on every step of a document, not only on the one that writes
the stock. Confirmation reserves, and a reservation that counts grams as
kilograms blocks a thousand times the goods — or refuses a dispatch the shelf
could cover. Adjustments and corrections write deltas, and a delta in the
supplier's unit lands on the shelf as a number in the product's.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.uom import Uom


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    location_id: UUID,
    template_id: UUID,
    quantity: str,
    uom_id: UUID | None,
    unit_price: str | None = None,
) -> tuple[int, str]:
    line: dict[str, object] = {
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
    if uom_id is not None:
        line['uom_id'] = str(uom_id)
    if unit_price is not None:
        line['unit_price'] = unit_price
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    client.patch(f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers)
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    return done.status_code, done.text


@pytest.mark.integration
class TestStockIsKeptInOneUnit:
    def test_a_line_in_grams_lands_as_kilograms(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template_with_uom: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        gram = ModuleTestHelper(db_session).get_uom('g')

        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template_with_uom.id,
            quantity='500',
            uom_id=gram.id,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template_with_uom.id
            )
        ).one()
        assert shelf.quantity == Decimal('0.500')

        # And the record on the shelf holds it in the same unit.
        item = db_session.scalars(
            select(Item).where(Item.template_id == doc_template_with_uom.id)
        ).one()
        assert item.quantity == Decimal('0.500')
        assert item.uom_id == doc_template_with_uom.uom_id

    def test_the_price_is_converted_with_the_quantity(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template_with_uom: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        """The layer is priced per kilogram, not per gram.

        The quantity conversion was pinned on all four document paths; the
        cost that travels with it was not. Half a kilogram bought at two
        grosze a gram cost ten złotych — so the shelf holds 0.5 at 20.00 the
        kilo. Left unconverted the layer reads 0.5 at 0.02, and every figure
        drawn off the cost history afterwards is a thousandth of the truth.
        """
        gram = ModuleTestHelper(db_session).get_uom('g')

        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template_with_uom.id,
            quantity='500',
            uom_id=gram.id,
            unit_price='0.02',
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        layer = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == doc_template_with_uom.id,
                StockValuationLayer.direction == 'IN',
            )
        ).one()

        assert layer.quantity == Decimal('0.500')
        assert layer.unit_cost == Decimal('20.0000')
        # What the delivery actually cost, unchanged by the unit it is
        # recorded in: 500 x 0.02.
        assert layer.total_value == Decimal('10.00')

    def test_a_line_in_the_products_own_unit_is_untouched(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template_with_uom: ProductTemplate,
        doc_uom_kg: Uom,
        db_session: Session,
    ) -> None:
        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template_with_uom.id,
            quantity='3',
            uom_id=doc_uom_kg.id,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template_with_uom.id
            )
        ).one()
        assert shelf.quantity == Decimal('3.000')

    def test_a_unit_that_does_not_convert_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template_with_uom: ProductTemplate,
        doc_uom_pcs: Uom,
        db_session: Session,
    ) -> None:
        """Pieces do not become kilograms, and the refusal names both."""
        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template_with_uom.id,
            quantity='4',
            uom_id=doc_uom_pcs.id,
        )
        assert code == status.HTTP_400_BAD_REQUEST, body
        assert 'kg' in body and 'pcs' in body

        db_session.expire_all()
        assert (
            db_session.scalars(
                select(ShelfRow).where(
                    ShelfRow.product_template_id == doc_template_with_uom.id
                )
            ).first()
            is None
        )


def _dispatch(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    source_location_id: UUID,
    item_id: UUID,
    template_id: UUID,
    quantity: str,
    uom_id: UUID | None,
) -> tuple[int, str]:
    line: dict[str, object] = {
        'item_id': str(item_id),
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
    if uom_id is not None:
        line['uom_id'] = str(uom_id)
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(source_location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    if confirm.status_code != status.HTTP_200_OK:
        return confirm.status_code, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    return complete.status_code, complete.text


@pytest.mark.integration
class TestAReservationCountsTheProductsUnit:
    """Confirmation blocks stock, and it has to block the right amount."""

    def test_a_dispatch_in_grams_reserves_grams_worth_of_kilograms(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_partner: Partner,
        doc_template_with_uom: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Half a kilo asked for in grams comes off a three-kilo shelf.

        Reservation read the line's own number and the shelf's, so 500 g
        against 3 kg was a shortage of 497 — of goods that were there.
        """
        gram = ModuleTestHelper(db_session).get_uom('g')
        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_source_location.id,
            template_id=doc_template_with_uom.id,
            quantity='3',
            uom_id=doc_template_with_uom.uom_id,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        item = db_session.scalars(
            select(Item).where(Item.template_id == doc_template_with_uom.id)
        ).one()

        code, body = _dispatch(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            item_id=item.id,
            template_id=doc_template_with_uom.id,
            quantity='500',
            uom_id=gram.id,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template_with_uom.id
            )
        ).one()
        assert shelf.quantity == Decimal('2.500')
        assert shelf.reserved_quantity == Decimal('0')

    def test_a_dispatch_the_shelf_cannot_cover_is_still_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_partner: Partner,
        doc_template_with_uom: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The control: converting must not turn every shortage into a pass."""
        gram = ModuleTestHelper(db_session).get_uom('g')
        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_source_location.id,
            template_id=doc_template_with_uom.id,
            quantity='1',
            uom_id=doc_template_with_uom.uom_id,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        item = db_session.scalars(
            select(Item).where(Item.template_id == doc_template_with_uom.id)
        ).one()

        code, body = _dispatch(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            item_id=item.id,
            template_id=doc_template_with_uom.id,
            quantity='5000',
            uom_id=gram.id,
        )
        assert code == status.HTTP_400_BAD_REQUEST, body


def _complete(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> tuple[int, str]:
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    if confirm.status_code != status.HTTP_200_OK:
        return confirm.status_code, confirm.text
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    return done.status_code, done.text


@pytest.mark.integration
class TestADeltaCountsTheProductsUnit:
    """Adjustments and corrections write signed deltas — in whose unit?

    Every other executor converts before it writes. These two took the line's
    own number, so a correction of a delivery booked in grams moved kilograms
    off the shelf.
    """

    def test_an_adjustment_in_grams_adds_grams(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template_with_uom: ProductTemplate,
        db_session: Session,
    ) -> None:
        gram = ModuleTestHelper(db_session).get_uom('g')
        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template_with_uom.id,
            quantity='3',
            uom_id=doc_template_with_uom.uom_id,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        item = db_session.scalars(
            select(Item).where(Item.template_id == doc_template_with_uom.id)
        ).one()

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'ADJUSTMENT',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(item.id),
                        'product_template_id': str(doc_template_with_uom.id),
                        'expected_quantity': '500',
                        'uom_id': str(gram.id),
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        code, body = _complete(client, doc_auth_headers, cast(str, resp.json()['id']))
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        db_session.refresh(item)
        assert item.quantity == Decimal('3.500')
        shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template_with_uom.id
            )
        ).one()
        assert shelf.quantity == Decimal('3.500')

    def test_a_correction_in_grams_takes_back_grams(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template_with_uom: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A correction inherits the original line's unit, so it inherits the risk."""
        gram = ModuleTestHelper(db_session).get_uom('g')
        line: dict[str, object] = {
            'product_template_id': str(doc_template_with_uom.id),
            'expected_quantity': '2000',
            'uom_id': str(gram.id),
        }
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [line],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        receipt_id = cast(str, resp.json()['id'])
        code, body = _complete(client, doc_auth_headers, receipt_id)
        assert code == status.HTTP_200_OK, body

        correction = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': receipt_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': '-500'}],
            },
        )
        assert correction.status_code == status.HTTP_201_CREATED, correction.text
        code, body = _complete(
            client, doc_auth_headers, cast(str, correction.json()['id'])
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template_with_uom.id
            )
        ).one()
        assert shelf.quantity == Decimal('1.500')
