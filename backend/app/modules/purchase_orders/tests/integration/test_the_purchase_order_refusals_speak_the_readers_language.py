"""The purchase-order refusals speak the reader's language.

Every refusal this module's services and routers answered with used to be an
English literal: a supplier who sent an order past its draft state, or cleared
a price the schema refuses to clear, read "Only DRAFT purchase orders can be
updated" on a screen the rest of the workspace had already answered in Polish.
Each of them now raises through a catalogue key, and these tests pin the
sentence the reader gets.

The assertions are equalities against the Polish text, not status codes: with
a service reverted to its literal the response still answers 400 (or 409), and
only the sentence tells the two builds apart. Where the envelope carries a
language claim it is asserted too — it used to be possible for the claim and
the text to disagree.

Covered here, one class per file: ``_service_crud.py``, ``reorder_service.py``,
``pricelist_service.py``, ``_router_import.py``, ``_router_templates.py`` and
``_update_canon.py``. The two refusals of ``po_import_service.py`` and the two
no-HTTP-threshold guards of ``reorder_service.py`` / ``pricelist_service.py``
cannot be reached through a door — see their unit twin,
``test_the_service_refusals_speak_the_readers_language.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.modules.purchase_orders.models import PurchaseOrder, PurchaseOrderLine

pytestmark = pytest.mark.integration

PL_HEADERS = {'Accept-Language': 'pl'}

ORDERS_URL = '/api/v1/purchase-orders'
RULES_URL = f'{ORDERS_URL}/reorder-rules'
PRICELIST_URL = f'{ORDERS_URL}/pricelist'
TEMPLATES_URL = f'{ORDERS_URL}/templates'


def _polish(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, **PL_HEADERS}


def _message(response: Any) -> str:
    detail: dict[str, Any] = response.json()['detail']
    message: str = detail['message']
    return message


def _line(template_id: uuid.UUID) -> dict[str, Any]:
    return {'product_template_id': str(template_id), 'quantity_ordered': 2}


def _create_order(
    client: TestClient,
    headers: dict[str, str],
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    **extra: Any,
) -> str:
    resp = client.post(
        ORDERS_URL,
        headers=headers,
        json={
            'partner_id': str(partner_id),
            'lines': [_line(template_id)],
            **extra,
        },
    )
    assert resp.status_code == 201, resp.text
    created_id: str = resp.json()['id']
    return created_id


def _create_rule(
    client: TestClient,
    headers: dict[str, str],
    template_id: uuid.UUID,
    location_id: uuid.UUID,
    **extra: Any,
) -> str:
    resp = client.post(
        RULES_URL,
        headers=headers,
        json={
            'product_template_id': str(template_id),
            'location_id': str(location_id),
            'min_quantity': '5',
            'max_quantity': '20',
            **extra,
        },
    )
    assert resp.status_code == 201, resp.text
    created_id: str = resp.json()['id']
    return created_id


def _create_entry(
    client: TestClient,
    headers: dict[str, str],
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    **extra: Any,
) -> str:
    resp = client.post(
        PRICELIST_URL,
        headers=headers,
        json={
            'partner_id': str(partner_id),
            'product_template_id': str(template_id),
            'unit_price': '10.0000',
            'valid_from': '2026-01-01',
            **extra,
        },
    )
    assert resp.status_code == 201, resp.text
    created_id: str = resp.json()['id']
    return created_id


class TestCrudRefusalsSpeakPolish:
    """``_service_crud.py`` — creating and editing an order."""

    def test_a_line_naming_an_unknown_product_template_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        unknown_template = str(uuid.uuid4())

        resp = client.post(
            ORDERS_URL,
            headers=_polish(po_auth_headers),
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': unknown_template,
                        'quantity_ordered': 1,
                    }
                ],
            },
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            f'Szablon produktu {unknown_template} nie został znaleziony'
        )
        assert resp.json()['detail']['lang'] == 'pl'

    def test_an_order_naming_an_unknown_supplier_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_template: Any,
    ) -> None:
        unknown_partner = str(uuid.uuid4())

        resp = client.post(
            ORDERS_URL,
            headers=_polish(po_auth_headers),
            json={
                'partner_id': unknown_partner,
                'lines': [_line(po_template.id)],
            },
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == 'Kontrahent nie został znaleziony'
        assert resp.json()['detail']['lang'] == 'pl'

    def test_editing_a_missing_order_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
    ) -> None:
        """The update path answers 400 (not 404) for an unknown id — that
        is this service's own refusal, and it is the one that has to read
        in the reader's language."""
        resp = client.patch(
            f'{ORDERS_URL}/{uuid.uuid4()}',
            headers=_polish(po_auth_headers),
            json={'notes': 'not there yet'},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == 'Zamówienie zakupu nie zostało znalezione'
        assert resp.json()['detail']['lang'] == 'pl'

    def test_editing_a_confirmed_order_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        db_session: Session,
    ) -> None:
        po_id = _create_order(client, po_auth_headers, po_partner.id, po_template.id)
        db_session.execute(
            update(PurchaseOrder)
            .where(PurchaseOrder.id == uuid.UUID(po_id))
            .values(status='CONFIRMED')
        )
        db_session.commit()

        resp = client.patch(
            f'{ORDERS_URL}/{po_id}',
            headers=_polish(po_auth_headers),
            json={'notes': 'no longer a draft'},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'Można aktualizować tylko zamówienia zakupowe w wersji roboczej'
        )
        assert resp.json()['detail']['lang'] == 'pl'

    def test_editing_a_missing_supplier_on_a_draft_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """The second ``partner_not_found`` site: one on create, one on the
        presence-decides PATCH that re-validates a named supplier."""
        po_id = _create_order(client, po_auth_headers, po_partner.id, po_template.id)

        resp = client.patch(
            f'{ORDERS_URL}/{po_id}',
            headers=_polish(po_auth_headers),
            json={'partner_id': str(uuid.uuid4())},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == 'Kontrahent nie został znaleziony'
        assert resp.json()['detail']['lang'] == 'pl'

    def test_replacing_the_lines_of_a_partly_received_order_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        db_session: Session,
    ) -> None:
        po_id = _create_order(client, po_auth_headers, po_partner.id, po_template.id)
        line = db_session.scalars(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.purchase_order_id == uuid.UUID(po_id)
            )
        ).one()
        line.quantity_received = Decimal('1')
        db_session.commit()

        resp = client.patch(
            f'{ORDERS_URL}/{po_id}',
            headers=_polish(po_auth_headers),
            json={'lines': [_line(po_template.id)]},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'Nie można zaktualizować pozycji: część towaru została już przyjęta. '
            'Najpierw anuluj powiązane dokumenty przyjęcia.'
        )
        assert resp.json()['detail']['lang'] == 'pl'


class TestReorderRefusalsSpeakPolish:
    """``reorder_service.py`` — the two guards a request can still reach.

    The create schema types ``min_quantity`` as ``gt=0`` and
    ``safety_stock`` as ``ge=0``, so those two service guards answer 422
    before the service runs and are pinned at the service boundary in the
    unit twin instead.
    """

    def test_creating_a_rule_whose_maximum_is_below_its_minimum_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_template: Any,
        po_location: Any,
    ) -> None:
        resp = client.post(
            RULES_URL,
            headers=_polish(po_auth_headers),
            json={
                'product_template_id': str(po_template.id),
                'location_id': str(po_location.id),
                'min_quantity': '20',
                'max_quantity': '5',
            },
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == ('max_quantity (5) musi być >= min_quantity (20)')
        assert resp.json()['detail']['lang'] == 'pl'

    def test_patching_a_rule_into_a_negative_safety_stock_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_template: Any,
        po_location: Any,
    ) -> None:
        rule_id = _create_rule(client, po_auth_headers, po_template.id, po_location.id)

        resp = client.patch(
            f'{RULES_URL}/{rule_id}',
            headers=_polish(po_auth_headers),
            json={'safety_stock': '-1'},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == 'safety_stock musi być >= 0, otrzymano -1'
        assert resp.json()['detail']['lang'] == 'pl'


class TestPricelistRefusalsSpeakPolish:
    """``pricelist_service.py`` — the window and the duplicate offer.

    ``unit_price`` and ``min_quantity`` are ``gt=0`` in both write schemas,
    so the two positivity guards are unreachable over HTTP and are pinned at
    the service boundary in the unit twin.
    """

    def test_patching_an_end_date_before_the_start_date_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        entry_id = _create_entry(client, po_auth_headers, po_partner.id, po_template.id)

        resp = client.patch(
            f'{PRICELIST_URL}/{entry_id}',
            headers=_polish(po_auth_headers),
            json={'valid_to': '2025-06-01'},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'valid_to (2025-06-01) musi być >= valid_from (2026-01-01)'
        )
        assert resp.json()['detail']['lang'] == 'pl'

    def test_a_second_price_on_the_same_terms_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """The duplicate offer answers 409 through the AppException
        envelope, whose ``detail`` carries no language claim — the message
        itself is translated before it is raised."""
        _create_entry(client, po_auth_headers, po_partner.id, po_template.id)

        resp = client.post(
            PRICELIST_URL,
            headers=_polish(po_auth_headers),
            json={
                'partner_id': str(po_partner.id),
                'product_template_id': str(po_template.id),
                'unit_price': '12.0000',
                'valid_from': '2026-01-01',
            },
        )

        assert resp.status_code == 409, resp.text
        assert _message(resp) == (
            'Ten dostawca ma już cenę tego produktu na te same daty i przy tej '
            'samej minimalnej ilości. Popraw tamtą pozycję, zamiast dodawać drugą.'
        )
        assert resp.json()['detail']['code'] == 'PRICELIST_DUPLICATE'


class TestImportLinesRefusalSpeaksPolish:
    """``_router_import.py`` — the door that checks before the file is read.

    The service's own twin of this refusal never runs over HTTP: the router
    answers first, which is what makes the service half defense in depth.
    """

    def test_importing_lines_into_a_confirmed_order_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        db_session: Session,
    ) -> None:
        po_id = _create_order(client, po_auth_headers, po_partner.id, po_template.id)
        db_session.execute(
            update(PurchaseOrder)
            .where(PurchaseOrder.id == uuid.UUID(po_id))
            .values(status='CONFIRMED')
        )
        db_session.commit()

        resp = client.post(
            f'{ORDERS_URL}/{po_id}/import-lines',
            headers=_polish(po_auth_headers),
            files={
                'file': (
                    'lines.csv',
                    b'name,quantity_ordered\nWidget,1\n',
                    'text/csv',
                )
            },
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'Można importować linie tylko do zamówienia zakupowego w wersji ROBOCZEJ'
        )


class TestTemplateRefusalSpeaksPolish:
    """``_router_templates.py`` — a template declared for another module."""

    def test_creating_a_template_for_another_module_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            TEMPLATES_URL,
            headers=_polish(po_auth_headers),
            json={
                'name': 'Not an order template',
                'module': 'warehouse',
                'body_html': '<p>{{ po_number }}</p>',
            },
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == 'Moduł musi być "purchase_orders"'

    def test_a_template_for_the_right_module_still_lands(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
    ) -> None:
        """The refusal is keyed, not a blanket ``module`` check: the key's
        English wording changed with the migration, and this half pins that
        the guard still opens for this module's own templates."""
        resp = client.post(
            TEMPLATES_URL,
            headers=po_auth_headers,
            json={
                'name': 'Standard order',
                'module': 'purchase_orders',
                'body_html': '<p>{{ po_number }}</p>',
            },
        )

        assert resp.status_code == 201, resp.text
        assert resp.json()['module'] == 'purchase_orders'


class TestNamedNullCanonSpeaksPolish:
    """``_update_canon.py`` — the §2b refusal, in the reader's language.

    The field names in the sentence are catalogue data, not prose, so they
    survive translation: a test that only looks for them would pass on
    either build, this one asks for the Polish sentence around them.
    """

    def test_clearing_a_price_list_field_that_cannot_be_cleared_speaks_polish(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        entry_id = _create_entry(client, po_auth_headers, po_partner.id, po_template.id)

        resp = client.patch(
            f'{PRICELIST_URL}/{entry_id}',
            headers=_polish(po_auth_headers),
            json={'unit_price': None},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == ('Tych pól nie można wyczyścić: unit_price.')
