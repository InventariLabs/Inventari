"""API tests for draft-PO creation from replenishment alerts.

The one-click action on the alerts view: the requested reorder rules are
re-checked against current stock, grouped by their preferred supplier, and
each group lands in the register as a normal editable DRAFT purchase
order — quantities from the rule's suggestion, prices from the supplier's
pricelist, and every line remembering the rule that raised it. A rule
with no supplier is reported back, never turned into an empty order.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.modules.purchase_orders.models import (
    PartnerPricelist,
    PurchaseOrder,
    ReorderRule,
)
from tests.integration._shelf import post_on_shelf

URL = '/api/v1/purchase-orders/replenishment/draft-pos'


def _rule(
    db_session: Session,
    org: Any,
    template: Any,
    location: Any,
    *,
    min_qty: str = '10',
    max_qty: str = '20',
    partner_id: Any = None,
) -> ReorderRule:
    rule = ReorderRule(
        organization_id=org.id,
        product_template_id=template.id,
        storage_location_id=location.id,
        min_quantity=Decimal(min_qty),
        max_quantity=Decimal(max_qty),
        safety_stock=Decimal('0'),
        preferred_partner_id=partner_id,
    )
    db_session.add(rule)
    db_session.commit()
    return rule


def _stock(
    client: TestClient,
    headers: dict[str, str],
    template: Any,
    location: Any,
    quantity: str,
) -> None:
    post_on_shelf(client, headers, template, location.id, quantity)


def _price(
    db_session: Session,
    org: Any,
    partner: Any,
    template: Any,
    unit_price: str,
    *,
    currency: str = 'PLN',
    min_quantity: str | None = None,
) -> None:
    db_session.add(
        PartnerPricelist(
            organization_id=org.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal(unit_price),
            currency=currency,
            min_quantity=Decimal(min_quantity) if min_quantity else None,
            valid_from=date.today() - timedelta(days=1),
        )
    )
    db_session.commit()


@pytest.mark.integration
class TestReplenishmentDraftPos:
    def test_two_suppliers_two_draft_pos(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_user: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
        h: Any,
    ) -> None:
        second_partner = h.create_partner(
            po_org, po_user, name='Second Supplier', email='s2@example.com'
        )
        second_template = h.create_template(
            po_org, name='Second Product', sku='PO-DRAFT-002'
        )
        rule_a = _rule(
            db_session, po_org, po_template, po_location, partner_id=po_partner.id
        )
        rule_b = _rule(
            db_session,
            po_org,
            second_template,
            po_location,
            partner_id=second_partner.id,
        )
        _stock(client, po_auth_headers, po_template, po_location, '3')
        _stock(client, po_auth_headers, second_template, po_location, '1')
        _price(db_session, po_org, po_partner, po_template, '12.50')
        _price(db_session, po_org, second_partner, second_template, '7.99')

        resp = client.post(
            URL,
            headers=po_auth_headers,
            json={'reorder_rule_ids': [str(rule_a.id), str(rule_b.id)]},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert body['skipped'] == []
        created = body['created']
        assert len(created) == 2

        by_partner = {po['partner_id']: po for po in created}
        po_a = by_partner[str(po_partner.id)]
        po_b = by_partner[str(second_partner.id)]

        assert po_a['status'] == 'DRAFT'
        assert len(po_a['lines']) == 1
        line_a = po_a['lines'][0]
        # suggested = max (20) - available (3)
        assert Decimal(line_a['quantity_ordered']) == Decimal('17')
        assert Decimal(line_a['unit_price']) == Decimal('12.50')
        assert line_a['source_reorder_rule_id'] == str(rule_a.id)
        assert line_a['product_template_id'] == str(po_template.id)

        assert po_b['status'] == 'DRAFT'
        line_b = po_b['lines'][0]
        assert Decimal(line_b['quantity_ordered']) == Decimal('19')
        assert Decimal(line_b['unit_price']) == Decimal('7.99')
        assert line_b['source_reorder_rule_id'] == str(rule_b.id)

    def test_same_supplier_groups_into_one_po(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
        h: Any,
    ) -> None:
        second_template = h.create_template(
            po_org, name='Second Product', sku='PO-DRAFT-003'
        )
        rule_a = _rule(
            db_session, po_org, po_template, po_location, partner_id=po_partner.id
        )
        rule_b = _rule(
            db_session,
            po_org,
            second_template,
            po_location,
            partner_id=po_partner.id,
        )
        _stock(client, po_auth_headers, po_template, po_location, '0')
        _stock(client, po_auth_headers, second_template, po_location, '0')

        resp = client.post(
            URL,
            headers=po_auth_headers,
            json={'reorder_rule_ids': [str(rule_a.id), str(rule_b.id)]},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert body['skipped'] == []
        assert len(body['created']) == 1
        po = body['created'][0]
        assert po['partner_id'] == str(po_partner.id)
        assert len(po['lines']) == 2
        refs = {line['source_reorder_rule_id'] for line in po['lines']}
        assert refs == {str(rule_a.id), str(rule_b.id)}

    def test_rule_without_supplier_is_skipped_not_an_empty_po(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
        h: Any,
    ) -> None:
        orphan_template = h.create_template(
            po_org, name='Orphan Product', sku='PO-DRAFT-004'
        )
        with_supplier = _rule(
            db_session, po_org, po_template, po_location, partner_id=po_partner.id
        )
        without_supplier = _rule(
            db_session, po_org, orphan_template, po_location, partner_id=None
        )
        _stock(client, po_auth_headers, po_template, po_location, '0')
        _stock(client, po_auth_headers, orphan_template, po_location, '0')

        resp = client.post(
            URL,
            headers=po_auth_headers,
            json={
                'reorder_rule_ids': [str(with_supplier.id), str(without_supplier.id)]
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert len(body['created']) == 1
        assert body['created'][0]['partner_id'] == str(po_partner.id)

        assert len(body['skipped']) == 1
        skipped = body['skipped'][0]
        assert skipped['reorder_rule_id'] == str(without_supplier.id)
        assert skipped['reason'] == 'no_supplier'

        # no order exists for the skipped rule — above all, no empty one
        orphan_pos = (
            db_session.query(PurchaseOrder)
            .filter(PurchaseOrder.organization_id == po_org.id)
            .filter(PurchaseOrder.partner_id.is_(None))
            .all()
        )
        assert orphan_pos == []

    def test_a_rule_without_a_supplier_proposes_the_one_the_price_list_names(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        # No preferred supplier on the rule, but the price list holds an offer:
        # the alert names that supplier instead of "none", and the draft order
        # goes to it rather than being reported as `no_supplier`.
        rule = _rule(db_session, po_org, po_template, po_location, partner_id=None)
        _price(db_session, po_org, po_partner, po_template, '12.50')
        _stock(client, po_auth_headers, po_template, po_location, '0')

        alerts = client.get(
            '/api/v1/purchase-orders/replenishment/alerts', headers=po_auth_headers
        )
        assert alerts.status_code == status.HTTP_200_OK
        [alert] = [
            a for a in alerts.json()['items'] if a['reorder_rule_id'] == str(rule.id)
        ]
        assert alert['preferred_partner_id'] == str(po_partner.id)
        assert alert['preferred_partner_name'] == po_partner.name

        resp = client.post(
            URL,
            headers=po_auth_headers,
            json={'reorder_rule_ids': [str(rule.id)]},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert body['skipped'] == []
        assert body['created'][0]['partner_id'] == str(po_partner.id)

    @pytest.mark.parametrize(
        ('tier_from', 'winner'),
        [('1000', 'plain'), ('10', 'bulk')],
        ids=['tier-out-of-reach', 'tier-reached'],
    )
    def test_a_volume_price_names_the_supplier_only_when_the_order_reaches_it(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_user: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
        h: Any,
        tier_from: str,
        winner: str,
    ) -> None:
        # The cheaper offer is a volume price. The proposal passes it over
        # while the quantity to buy stays below its tier, and the draft order
        # goes to the supplier whose price applies to what is really ordered.
        bulk = h.create_partner(
            po_org, po_user, name='Bulk Only Ltd', email='bulk@example.com'
        )
        rule = _rule(db_session, po_org, po_template, po_location, partner_id=None)
        _price(db_session, po_org, bulk, po_template, '2.00', min_quantity=tier_from)
        _price(db_session, po_org, po_partner, po_template, '5.00')
        _stock(client, po_auth_headers, po_template, po_location, '0')
        expected = bulk if winner == 'bulk' else po_partner

        alerts = client.get(
            '/api/v1/purchase-orders/replenishment/alerts', headers=po_auth_headers
        )
        [alert] = [
            a for a in alerts.json()['items'] if a['reorder_rule_id'] == str(rule.id)
        ]
        assert alert['preferred_partner_id'] == str(expected.id)

        resp = client.post(
            URL, headers=po_auth_headers, json={'reorder_rule_ids': [str(rule.id)]}
        )
        assert resp.status_code == status.HTTP_201_CREATED
        [po] = resp.json()['created']
        assert po['partner_id'] == str(expected.id)

    def test_each_rule_of_one_product_picks_its_supplier_by_its_own_quantity(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_user: Any,
        po_storage_type: Any,
        po_location: Any,
        po_template: Any,
        h: Any,
    ) -> None:
        # One product is ordered for two locations: the small order stays
        # below the volume tier, the large one reaches it. The small rule
        # must not drag the large one away from the supplier it qualifies for.
        bulk = h.create_partner(
            po_org, po_user, name='Bulk Only Ltd', email='bulk@example.com'
        )
        other = h.create_storage_location(
            po_org, po_storage_type, po_user, name='Second Warehouse'
        )
        small = _rule(
            db_session, po_org, po_template, po_location, min_qty='10', max_qty='29'
        )
        large = _rule(
            db_session, po_org, po_template, other, min_qty='10', max_qty='1500'
        )
        _price(db_session, po_org, bulk, po_template, '2.00', min_quantity='1000')

        alerts = client.get(
            '/api/v1/purchase-orders/replenishment/alerts', headers=po_auth_headers
        )
        by_rule = {a['reorder_rule_id']: a for a in alerts.json()['items']}
        assert by_rule[str(small.id)]['preferred_partner_id'] is None
        assert by_rule[str(large.id)]['preferred_partner_id'] == str(bulk.id)

        resp = client.post(
            URL, headers=po_auth_headers, json={'reorder_rule_ids': [str(large.id)]}
        )
        assert resp.status_code == status.HTTP_201_CREATED
        [po] = resp.json()['created']
        assert po['partner_id'] == str(bulk.id)

    def test_a_deactivated_supplier_is_never_the_proposed_one(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_user: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
        h: Any,
    ) -> None:
        # The cheapest offer belongs to a supplier that was switched off. An
        # order to it would be refused at confirmation, so the proposal goes to
        # the cheapest offer of a supplier that can still be ordered from.
        gone = h.create_partner(
            po_org, po_user, name='Gone Traders', email='gone@example.com'
        )
        gone.is_active = False
        db_session.commit()
        rule = _rule(db_session, po_org, po_template, po_location, partner_id=None)
        _price(db_session, po_org, gone, po_template, '3.00')
        _price(db_session, po_org, po_partner, po_template, '4.00')
        _stock(client, po_auth_headers, po_template, po_location, '0')

        alerts = client.get(
            '/api/v1/purchase-orders/replenishment/alerts', headers=po_auth_headers
        )
        [alert] = [
            a for a in alerts.json()['items'] if a['reorder_rule_id'] == str(rule.id)
        ]
        assert alert['preferred_partner_id'] == str(po_partner.id)

        resp = client.post(
            URL, headers=po_auth_headers, json={'reorder_rule_ids': [str(rule.id)]}
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()['created'][0]['partner_id'] == str(po_partner.id)

    def test_the_line_is_priced_from_a_tier_its_quantity_reaches(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        # 3.00 with no minimum, 2.00 from 1000 pieces; 15 are needed. The
        # order is for 15 x 3.00 — the 1000-piece price is not one it can get.
        rule = _rule(
            db_session, po_org, po_template, po_location, partner_id=po_partner.id
        )
        _price(db_session, po_org, po_partner, po_template, '3.00')
        _price(db_session, po_org, po_partner, po_template, '2.00', min_quantity='1000')
        _stock(client, po_auth_headers, po_template, po_location, '5')

        resp = client.post(
            URL, headers=po_auth_headers, json={'reorder_rule_ids': [str(rule.id)]}
        )
        assert resp.status_code == status.HTTP_201_CREATED
        line = resp.json()['created'][0]['lines'][0]
        assert Decimal(line['unit_price']) == Decimal('3.00')

    def test_a_supplier_whose_only_price_is_out_of_reach_is_not_proposed(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        rule = _rule(db_session, po_org, po_template, po_location, partner_id=None)
        _price(db_session, po_org, po_partner, po_template, '2.00', min_quantity='1000')
        _stock(client, po_auth_headers, po_template, po_location, '0')

        alerts = client.get(
            '/api/v1/purchase-orders/replenishment/alerts', headers=po_auth_headers
        )
        [alert] = [
            a for a in alerts.json()['items'] if a['reorder_rule_id'] == str(rule.id)
        ]
        assert alert['preferred_partner_id'] is None

    def test_an_offer_in_the_house_currency_beats_a_smaller_number_in_another(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_user: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
        h: Any,
    ) -> None:
        other = 'EUR' if po_org.currency != 'EUR' else 'PLN'
        abroad = h.create_partner(
            po_org, po_user, name='Abroad Ltd', email='abroad@example.com'
        )
        rule = _rule(db_session, po_org, po_template, po_location, partner_id=None)
        _price(db_session, po_org, abroad, po_template, '4.00', currency=other)
        _price(
            db_session,
            po_org,
            po_partner,
            po_template,
            '5.00',
            currency=po_org.currency,
        )
        _stock(client, po_auth_headers, po_template, po_location, '0')

        resp = client.post(
            URL, headers=po_auth_headers, json={'reorder_rule_ids': [str(rule.id)]}
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()['created'][0]['partner_id'] == str(po_partner.id)

    def test_missing_pricelist_leaves_unit_price_null(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        rule = _rule(
            db_session, po_org, po_template, po_location, partner_id=po_partner.id
        )
        _stock(client, po_auth_headers, po_template, po_location, '5')

        resp = client.post(
            URL,
            headers=po_auth_headers,
            json={'reorder_rule_ids': [str(rule.id)]},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert len(body['created']) == 1
        line = body['created'][0]['lines'][0]
        assert line['unit_price'] is None
        assert Decimal(line['quantity_ordered']) == Decimal('15')

    def test_rule_not_alerting_is_skipped(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        rule = _rule(
            db_session,
            po_org,
            po_template,
            po_location,
            min_qty='2',
            partner_id=po_partner.id,
        )
        _stock(client, po_auth_headers, po_template, po_location, '50')

        resp = client.post(
            URL,
            headers=po_auth_headers,
            json={'reorder_rule_ids': [str(rule.id)]},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert body['created'] == []
        assert len(body['skipped']) == 1
        assert body['skipped'][0]['reason'] == 'not_alerting'

    def test_unknown_rule_id_is_skipped(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            URL,
            headers=po_auth_headers,
            json={'reorder_rule_ids': [str(uuid4())]},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert body['created'] == []
        assert len(body['skipped']) == 1
        assert body['skipped'][0]['reason'] == 'not_found'

    def test_draft_quantities_stay_editable(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        rule = _rule(
            db_session, po_org, po_template, po_location, partner_id=po_partner.id
        )
        _stock(client, po_auth_headers, po_template, po_location, '3')

        resp = client.post(
            URL,
            headers=po_auth_headers,
            json={'reorder_rule_ids': [str(rule.id)]},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        po = resp.json()['created'][0]

        edited = client.patch(
            f'/api/v1/purchase-orders/{po["id"]}',
            headers=po_auth_headers,
            json={
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': '25',
                    }
                ]
            },
        )
        assert edited.status_code == status.HTTP_200_OK
        assert edited.json()['status'] == 'DRAFT'
        assert Decimal(edited.json()['lines'][0]['quantity_ordered']) == Decimal('25')
