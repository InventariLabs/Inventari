"""The warehouse module refuses in the reader's language.

Returns, corrections, the checks a new document goes through and the
configuration screens (putaway rules, capacity, templates, tax rates, type
settings, profile presets) refused with English sentences, assembled in
code. The frontend shows a refusal's message as it stands, so a Polish
reader got English — on a phone, in a toast, the only thing on screen. Each
refusal now carries a catalogue key and the answer is translated with the
request's language; the 400 envelope also says which language that is.

One refusal per source file that raises them, each asked in Polish. The
equality against the Polish sentence is what fails while a site still raises
its English literal.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.approvals.models import ApprovalWorkflow
from app.modules.warehouse.document_profile_service import PRESETS
from app.modules.warehouse.models import Document, DocumentStatus

pytestmark = pytest.mark.integration

PL = {'Accept-Language': 'pl'}


def _pl(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, **PL}


def _refused_in_polish(resp: Any, message: str, status: int = 400) -> None:
    assert resp.status_code == status, resp.text
    detail = resp.json()['detail']
    assert detail['message'] == message
    assert detail['lang'] == 'pl'


def _draft_in(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    target: StorageLocation,
    template: ProductTemplate,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [
                {'product_template_id': str(template.id), 'expected_quantity': 3}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()['id'])


class TestReturns:
    def test_a_return_against_a_draft(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _draft_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/return',
            headers=_pl(doc_auth_headers),
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 1}],
            },
        )

        _refused_in_polish(resp, 'Zwrot można utworzyć tylko do zakończonego dokumentu')


class TestCorrections:
    def test_a_correction_of_a_draft(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _draft_in(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=_pl(doc_auth_headers),
            json={
                'corrects_document_id': doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': -1}],
            },
        )

        _refused_in_polish(resp, 'Korygować można tylko zakończony dokument')

    def test_a_correction_of_a_type_with_no_direction(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """An adjustment's lines are already differences (``document_types``)."""
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'ADJUSTMENT',
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 2}],
            },
        )
        assert created.status_code == 201, created.text
        doc_id = created.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == 200, done.text

        resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=_pl(doc_auth_headers),
            json={
                'corrects_document_id': doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': -1}],
            },
        )

        _refused_in_polish(resp, 'Dokumentów tego typu nie można korygować')


class TestNewDocumentChecks:
    def test_a_receipt_without_a_target_location(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=_pl(doc_auth_headers),
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'lines': [{'name': 'Item', 'expected_quantity': 1}],
            },
        )

        _refused_in_polish(resp, 'Ten typ dokumentu wymaga miejsca docelowego')


class TestProfilePresets:
    def test_applying_a_preset_nobody_declares(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/profile/apply-preset/Nope',
            headers=_pl(doc_auth_headers),
        )

        _refused_in_polish(
            resp, f'Nie ma szablonu o nazwie Nope. Dostępne: {", ".join(PRESETS)}'
        )

    def test_reading_a_preset_nobody_declares(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/profile/presets/Nope', headers=_pl(doc_auth_headers)
        )

        _refused_in_polish(
            resp,
            f'Nie ma szablonu o nazwie Nope. Dostępne: {", ".join(PRESETS)}',
            status=404,
        )


class TestTypeSettings:
    def test_settings_for_a_type_that_does_not_exist(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/settings/type-configs/NOPE',
            headers=_pl(doc_auth_headers),
            json={'document_type': 'NOPE'},
        )

        _refused_in_polish(resp, 'Nie ma typu dokumentu NOPE')

    def test_removing_settings_nobody_saved(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """The service's refusal is answered by the router as its own 404."""
        resp = client.delete(
            '/api/v1/warehouse/settings/type-configs/IN',
            headers=_pl(doc_auth_headers),
        )

        assert resp.status_code == 404, resp.text
        assert resp.json()['detail']['message'] == (
            'Konfiguracja typu dokumentu nie została znaleziona'
        )


class TestPutawayRules:
    def test_a_rule_left_without_a_condition(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(doc_template.id),
                'target_location_id': str(doc_target_location.id),
                'priority': 100,
            },
        )
        assert created.status_code == 201, created.text

        resp = client.put(
            f'/api/v1/warehouse/putaway-rules/{created.json()["id"]}',
            headers=_pl(doc_auth_headers),
            json={'product_template_id': None},
        )

        _refused_in_polish(
            resp,
            'Reguła rozmieszczania musi mieć co najmniej jeden warunek — produkt, '
            'kategorię, tag kontekstu lub typ miejsca.',
        )


class TestPutawayCapacity:
    def test_a_second_capacity_for_the_same_product(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        payload = {
            'location_id': str(doc_target_location.id),
            'product_template_id': str(doc_template.id),
            'max_quantity': 10,
        }
        first = client.post(
            '/api/v1/warehouse/putaway/capacity', headers=doc_auth_headers, json=payload
        )
        assert first.status_code == 201, first.text

        resp = client.post(
            '/api/v1/warehouse/putaway/capacity',
            headers=_pl(doc_auth_headers),
            json=payload,
        )

        _refused_in_polish(
            resp,
            'To miejsce ma już pojemność dla tego produktu — zmień istniejący wpis.',
        )


class TestTemplates:
    def test_a_template_for_another_module(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/templates',
            headers=_pl(doc_auth_headers),
            json={
                'name': 'Elsewhere',
                'module': 'purchase_orders',
                'document_type': 'STANDARD',
                'body_html': '<html><body></body></html>',
                'is_default': False,
            },
        )

        _refused_in_polish(resp, 'Szablon dokumentu należy do modułu dokumentów')


class TestTaxRates:
    def test_an_update_that_changes_nothing(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.put(
            f'/api/v1/warehouse/tax-rates/{uuid.uuid4()}',
            headers=_pl(doc_auth_headers),
            json={},
        )

        _refused_in_polish(resp, 'Brak pól do zmiany')


class TestProductSearch:
    def test_an_empty_query(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/product-search',
            headers=_pl(doc_auth_headers),
            params={'q': '   '},
        )

        _refused_in_polish(resp, 'Wpisz, czego szukasz')


def _create_document(
    client: TestClient, headers: dict[str, str], payload: dict[str, Any]
) -> str:
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return str(resp.json()['id'])


def _confirm(client: TestClient, headers: dict[str, str], doc_id: str) -> None:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == 200, resp.text


def _out_document(
    client: TestClient,
    headers: dict[str, str],
    source: StorageLocation,
    target: StorageLocation,
    partner: Partner,
    template: ProductTemplate | None,
    item: Item,
    quantity: int = 5,
) -> str:
    line: dict[str, Any] = {
        'item_id': str(item.id),
        'expected_quantity': quantity,
    }
    if template is not None:
        line['product_template_id'] = str(template.id)
    return _create_document(
        client,
        headers,
        {
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(source.id),
            'target_location_id': str(target.id),
            'lines': [line],
        },
    )


def _in_document(
    client: TestClient,
    headers: dict[str, str],
    target: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
    quantity: int = 5,
) -> str:
    return _create_document(
        client,
        headers,
        {
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [
                {'product_template_id': str(template.id), 'expected_quantity': quantity}
            ],
        },
    )


class TestWarehouseSessionRefusals:
    """The phone screens: a scan, a completion and a release, in Polish."""

    def test_a_pick_scan_without_a_barcode(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        doc_id = _out_document(
            client,
            doc_auth_headers,
            doc_source_location,
            doc_target_location,
            doc_partner,
            doc_template,
            doc_stock_item,
        )
        _confirm(client, doc_auth_headers, doc_id)
        session_id = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        ).json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=_pl(doc_auth_headers),
            json={'quantity': 1},
        )

        _refused_in_polish(resp, 'Najpierw zeskanuj kod kreskowy.')

    def test_a_receive_scan_without_a_barcode(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _in_document(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        _confirm(client, doc_auth_headers, doc_id)
        session_id = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        ).json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=_pl(doc_auth_headers),
            json={'quantity': 1},
        )

        _refused_in_polish(resp, 'Najpierw zeskanuj kod kreskowy.')

    def test_completing_a_session_with_pending_lines(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        doc_id = _out_document(
            client,
            doc_auth_headers,
            doc_source_location,
            doc_target_location,
            doc_partner,
            doc_template,
            doc_stock_item,
        )
        _confirm(client, doc_auth_headers, doc_id)
        session_id = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        ).json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/complete',
            headers=_pl(doc_auth_headers),
        )

        _refused_in_polish(resp, 'Nie można zakończyć sesji — oczekujących pozycji: 1.')

    def test_cancelling_a_session_that_is_already_cancelled(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        doc_id = _out_document(
            client,
            doc_auth_headers,
            doc_source_location,
            doc_target_location,
            doc_partner,
            doc_template,
            doc_stock_item,
        )
        _confirm(client, doc_auth_headers, doc_id)
        session_id = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        ).json()['id']
        first = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/cancel',
            headers=doc_auth_headers,
        )
        assert first.status_code == 204, first.text

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/cancel',
            headers=_pl(doc_auth_headers),
        )

        _refused_in_polish(
            resp,
            'Nie znaleziono aktywnej sesji. Być może została już zakończona '
            'albo anulowana.',
        )


class TestExecutionRefusals:
    """Completion refusals: the quantities a document may be executed with."""

    def test_an_execution_line_of_another_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        doc_id = _out_document(
            client,
            doc_auth_headers,
            doc_source_location,
            doc_target_location,
            doc_partner,
            doc_template,
            doc_stock_item,
        )
        _confirm(client, doc_auth_headers, doc_id)

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=_pl(doc_auth_headers),
            json={'lines': [{'line_id': str(uuid.uuid4()), 'done_quantity': 1}]},
        )

        _refused_in_polish(resp, 'Ta pozycja wykonania nie należy do tego dokumentu.')


class TestStockExecutorRefusals:
    """The executor's own refusals, reached through a real completion."""

    def test_a_dispatch_whose_shelf_no_longer_holds_the_goods(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        doc_id = _out_document(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_target_location,
            doc_partner,
            None,
            doc_item,
        )
        _confirm(client, doc_auth_headers, doc_id)
        # The delivery's confirmation reserved what the shelf held; another
        # movement then took most of it before this document was completed.
        doc_item.quantity = Decimal('1')
        db_session.commit()

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=_pl(doc_auth_headers),
            json={'complete_as_planned': True},
        )

        assert resp.status_code == 400, resp.text
        detail = resp.json()['detail']
        assert detail['lang'] == 'pl'
        assert detail['message'].startswith('Za mało stanu dla „Widget A”: dostępne ')

    def test_a_receipt_without_a_target_location(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        doc_id = _in_document(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        _confirm(client, doc_auth_headers, doc_id)
        doc = db_session.get(Document, uuid.UUID(doc_id))
        assert doc is not None
        doc.target_location_id = None
        db_session.commit()

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=_pl(doc_auth_headers),
            json={'complete_as_planned': True},
        )

        _refused_in_polish(resp, 'Dokument przyjęcia nie ma miejsca docelowego.')

    def test_a_transfer_without_a_target_location(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
        db_session: Session,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_stock_item.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        _confirm(client, doc_auth_headers, doc_id)
        doc = db_session.get(Document, uuid.UUID(doc_id))
        assert doc is not None
        doc.target_location_id = None
        db_session.commit()

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=_pl(doc_auth_headers),
            json={'complete_as_planned': True},
        )

        _refused_in_polish(resp, 'Dokument przesunięcia nie ma miejsca docelowego.')

    def test_a_correction_that_would_take_the_stock_below_zero(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        original_id = _in_document(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template, 2
        )
        _confirm(client, doc_auth_headers, original_id)
        received = client.patch(
            f'/api/v1/warehouse/documents/{original_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert received.status_code == 200, received.text

        correction = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': -2}],
            },
        )
        assert correction.status_code == 201, correction.text
        correction_id = correction.json()['id']
        _confirm(client, doc_auth_headers, correction_id)

        record = db_session.scalars(
            select(Item).where(
                Item.organization_id == doc_target_location.organization_id,
                Item.template_id == doc_template.id,
                Item.storage_location_id == doc_target_location.id,
            )
        ).first()
        assert record is not None
        record.quantity = Decimal('1')
        db_session.commit()

        resp = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/complete',
            headers=_pl(doc_auth_headers),
            json={'complete_as_planned': True},
        )

        assert resp.status_code == 400, resp.text
        detail = resp.json()['detail']
        assert detail['lang'] == 'pl'
        assert detail['message'].startswith('Korekta wprowadziłaby ')


class TestReworkRefusals:
    def test_rejecting_a_request_for_a_document_that_cannot_be_reworked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            },
        )
        _confirm(client, doc_auth_headers, doc_id)
        approval = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        )
        assert approval.status_code == 200, approval.text
        assert approval.json()['status'] in ('PENDING', 'IN_PROGRESS'), approval.text

        # The ordinary doors keep this state out; a document can still reach
        # it through a path that bypasses the approval gate, and the refusal
        # has to speak the reader's language when it does.
        doc = db_session.get(Document, uuid.UUID(doc_id))
        assert doc is not None
        doc.status = DocumentStatus.COMPLETED.value
        db_session.commit()

        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/reject',
            headers=_pl(doc_auth_headers),
        )

        _refused_in_polish(
            resp,
            'Dokumentu o statusie COMPLETED nie można przywrócić do wersji '
            'roboczej; można to zrobić tylko z zatwierdzonego albo '
            'oczekującego na zatwierdzenie.',
        )
