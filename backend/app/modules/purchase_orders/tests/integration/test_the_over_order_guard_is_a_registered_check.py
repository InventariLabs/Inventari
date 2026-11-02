"""The over-order guard is a pre-post check this module registers.

The warehouse used to import the orders module to weigh a receipt against
the order it names, so neither module could be taken out without the other.
The rule is now ours: the warehouse asks every module's pre-post check when it
confirms and completes a document, and ours refuses a receipt that overdraws
an order line. Where the module is off for an organization nobody asks, and a
receipt that names an order line is a receipt like any other.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.modules.purchase_orders._over_order_check import (
    MODULE,
    refuse_receipt_past_order_async,
)
from app.modules.warehouse import pre_post_checks

from .test_over_receipt_on_an_order import (
    _complete_receipt,
    _confirmed_po_line,
    _receipt_against,
    _receiver_headers,
)


@pytest.mark.unit
def test_the_orders_module_has_registered_its_check() -> None:
    assert pre_post_checks._CHECKS[MODULE] is refuse_receipt_past_order_async


@pytest.mark.integration
class TestTheCheckIsAskedWhileTheModuleIsOn:
    def test_a_receipt_past_the_order_is_refused_at_confirmation(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        receiver = _receiver_headers(
            h, po_org, may_exceed=False, email='guard-on@example.com'
        )
        _po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        doc = _receipt_against(
            client,
            receiver,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='12',
        )

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=receiver
        )

        assert confirm.status_code == status.HTTP_400_BAD_REQUEST, confirm.text
        assert 'order' in confirm.text


@pytest.mark.integration
class TestNobodyAsksItWhileTheModuleIsOff:
    def test_a_receipt_naming_an_order_line_is_a_plain_receipt(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        receiver = _receiver_headers(
            h, po_org, may_exceed=False, email='guard-off@example.com'
        )
        _po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        doc = _receipt_against(
            client,
            receiver,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='12',
        )
        po_org.enabled_modules = [m for m in po_org.enabled_modules if m != MODULE]
        db_session.commit()

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=receiver
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        complete = _complete_receipt(client, receiver, doc, done_quantity='12')
        assert complete.status_code == status.HTTP_200_OK, complete.text
