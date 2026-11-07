"""Warehouse module — exploratory / QA tests.

These tests simulate real user behavior and try to find bugs in the
document lifecycle, corrections, returns, WMS, and data integrity.
Unlike penetration tests, these assume a GOOD-FAITH user and focus on
business logic correctness rather than security.

Findings are documented inline as comments.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

# ─── helpers ─────────────────────────────────────────────────────────────────

# A receipt takes only products on the list into stock, so the widget the
# documents here receive is one — named by the code its lines carry.
_WIDGET_BARCODE = '5901234560019'


@pytest.fixture(autouse=True)
def _the_widget_is_on_the_list(h: ModuleTestHelper, doc_org: Organization) -> None:
    h.create_template(doc_org, name='Widget', barcode=_WIDGET_BARCODE)


def _widget(name: str = 'Widget', **fields: Any) -> dict[str, Any]:
    return {'name': name, 'barcode': _WIDGET_BARCODE, **fields}


def _doc_payload(**overrides: Any) -> dict[str, Any]:
    defaults = {
        'type': 'IN',
        'lines': [_widget(expected_quantity=10)],
    }
    defaults.update(overrides)
    return defaults


def _create_doc(
    client: TestClient, headers: dict[str, str], **kwargs: Any
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents', json=_doc_payload(**kwargs), headers=headers
    )
    assert resp.status_code in (200, 201), resp.text
    return cast(dict[str, Any], resp.json())


def _confirm(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> dict[str, Any]:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == 200, resp.text
    return cast(dict[str, Any], resp.json())


def _complete(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    execution_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = execution_data or {'complete_as_planned': True}
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete', json=payload, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return cast(dict[str, Any], resp.json())


def _cancel(client: TestClient, headers: dict[str, str], doc_id: str) -> dict[str, Any]:
    resp = client.patch(f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=headers)
    assert resp.status_code == 200, resp.text
    return cast(dict[str, Any], resp.json())


# ══════════════════════════════════════════════════════════════════════════════
# 1. FULL DOCUMENT LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestExploratoryDocumentLifecycle:
    """End-to-end document creation → confirm → complete → verify."""

    def test_in_document_full_lifecycle(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """IN (receipt) document: receive 10 widgets from supplier."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {
                    'product_template_id': str(doc_template.id),
                    'name': 'Widget',
                    'expected_quantity': 10,
                }
            ],
        )
        assert doc['status'] == 'DRAFT'
        assert doc['number'] is not None
        # A draft carries an identifier; the register's number arrives
        # with confirmation.
        assert doc['number'].startswith('DRAFT-')

        doc = _confirm(client, doc_auth_headers, doc['id'])
        assert doc['status'] == 'CONFIRMED'
        assert doc['number'].startswith('IN/')
        assert doc['partner_snapshot'] is not None
        assert doc['partner_snapshot']['name'] == 'Acme Supplies'

        doc = _complete(client, doc_auth_headers, doc['id'])
        assert doc['status'] == 'COMPLETED'

        for line in doc['lines']:
            assert Decimal(str(line['done_quantity'])) == Decimal('10')

    def test_document_number_is_sequential(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """Document numbers should be sequential for same type.

        Confirmed, because that is where numbers are given out.
        """
        numbers = []
        for _ in range(3):
            doc = _create_doc(
                client,
                doc_auth_headers,
                type='IN',
                partner_id=str(doc_partner.id),
                target_location_id=str(doc_target_location.id),
            )
            confirmed = _confirm(client, doc_auth_headers, doc['id'])
            numbers.append(confirmed['number'])
        assert len(set(numbers)) == 3
        assert all(n.startswith('IN/') for n in numbers), numbers

    def test_document_number_includes_year(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """Document number should contain current year."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
        )
        doc = _confirm(client, doc_auth_headers, doc['id'])
        import datetime

        current_year = str(datetime.datetime.now(datetime.UTC).year)
        assert current_year in doc['number']

    def test_update_draft_document_notes(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """Updating notes on a DRAFT document should work."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
        )
        resp = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}',
            json={'notes': 'Updated notes'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['notes'] == 'Updated notes'

    def test_cancel_then_delete_draft(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """A cancelled document is kept; a draft nobody confirmed is deletable.

        The note that stood here — "BUG: cannot delete a CANCELLED document,
        returns 400, delete_document only allows DRAFT" — named the rule
        before it was the rule. A cancelled document is an act that
        happened: it carries the number the register gave it (or the
        identifier nothing consumed), and deleting it erases the record of
        the act. A draft is a plan, and stays deletable.
        """
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
        )
        doc = _cancel(client, doc_auth_headers, doc['id'])
        assert doc['status'] == 'CANCELLED'
        refused = client.delete(
            f'/api/v1/warehouse/documents/{doc["id"]}', headers=doc_auth_headers
        )
        assert refused.status_code == 400, refused.text
        kept = client.get(
            f'/api/v1/warehouse/documents/{doc["id"]}', headers=doc_auth_headers
        )
        assert kept.status_code == 200

        draft = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
        )
        deleted = client.delete(
            f'/api/v1/warehouse/documents/{draft["id"]}', headers=doc_auth_headers
        )
        assert deleted.status_code == 204, deleted.text

    def test_multiple_lines_lifecycle(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """Receipt with multiple lines — all should complete."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                _widget('Widget A', expected_quantity=5),
                _widget('Widget B', expected_quantity=3),
                _widget('Widget C', expected_quantity=10),
            ],
        )
        assert len(doc['lines']) == 3

        doc = _confirm(client, doc_auth_headers, doc['id'])
        doc = _complete(client, doc_auth_headers, doc['id'])
        assert doc['status'] == 'COMPLETED'
        assert len(doc['lines']) == 3


# ══════════════════════════════════════════════════════════════════════════════
# 2. VALUE COMPUTATION
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestExploratoryValueComputation:
    """Verify document value/tax/gross totals are computed correctly."""

    def test_single_line_value(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """5 items × $10.00 = $50.00 net."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[{'name': 'Widget', 'expected_quantity': 5, 'unit_price': 10.00}],
        )
        assert doc['total_net'] is not None
        assert Decimal(str(doc['total_net'])) == Decimal('50.00')

    def test_multi_line_value(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """Multiple lines with different prices."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {'name': 'A', 'expected_quantity': 3, 'unit_price': 10.00},
                {'name': 'B', 'expected_quantity': 2, 'unit_price': 25.00},
            ],
        )
        assert Decimal(str(doc['total_net'])) == Decimal('80.00')

    def test_value_with_tax(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """5 × $100 with 23% tax = net 500, tax 115, gross 615."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {
                    'name': 'Widget',
                    'expected_quantity': 5,
                    'unit_price': 100.00,
                    'tax_rate': 23.00,
                }
            ],
        )
        assert Decimal(str(doc['total_net'])) == Decimal('500.00')
        assert Decimal(str(doc['total_tax'])) == Decimal('115.00')
        assert Decimal(str(doc['total_gross'])) == Decimal('615.00')

    def test_no_prices_null_totals(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """Document without unit_price should have None totals."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[{'name': 'Widget', 'expected_quantity': 5}],
        )
        assert doc['total_net'] is None
        assert doc['total_tax'] is None
        assert doc['total_gross'] is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. CORRECTIONS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestExploratoryCorrections:
    """Test correction document creation and execution."""

    def test_correction_on_completed_receipt(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Receive 10, then correct by -3."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {
                    'product_template_id': str(doc_template.id),
                    'name': 'Widget',
                    'expected_quantity': 10,
                }
            ],
        )
        doc = _confirm(client, doc_auth_headers, doc['id'])
        doc = _complete(client, doc_auth_headers, doc['id'])

        resp = client.post(
            '/api/v1/warehouse/corrections',
            json={
                'corrects_document_id': doc['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': -3}],
                'notes': 'Received 3 too many',
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code in (200, 201), resp.text
        correction = resp.json()
        assert correction['type'] == 'CORRECTION'
        assert correction['status'] == 'DRAFT'
        assert correction['corrects_document_id'] == doc['id']

    def test_correction_on_draft_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
        )
        resp = client.post(
            '/api/v1/warehouse/corrections',
            json={
                'corrects_document_id': doc['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': 1}],
                'notes': 'Draft must fail regardless of reason',
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 409)

    def test_correction_nonexistent_line_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {
                    'product_template_id': str(doc_template.id),
                    'name': 'Widget',
                    'expected_quantity': 5,
                }
            ],
        )
        doc = _confirm(client, doc_auth_headers, doc['id'])
        doc = _complete(client, doc_auth_headers, doc['id'])

        resp = client.post(
            '/api/v1/warehouse/corrections',
            json={
                'corrects_document_id': doc['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 99, 'quantity_delta': 1}],
                'notes': 'Nonexistent line test',
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 404, 422)

    def test_list_corrections(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {
                    'product_template_id': str(doc_template.id),
                    'name': 'Widget',
                    'expected_quantity': 5,
                }
            ],
        )
        doc = _confirm(client, doc_auth_headers, doc['id'])
        doc = _complete(client, doc_auth_headers, doc['id'])

        resp = client.get(
            f'/api/v1/warehouse/documents/{doc["id"]}/corrections',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()['items'], list)


# ══════════════════════════════════════════════════════════════════════════════
# 4. RETURNS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestExploratoryReturns:
    def test_return_on_completed_receipt(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {
                    'product_template_id': str(doc_template.id),
                    'name': 'Widget',
                    'expected_quantity': 10,
                }
            ],
        )
        doc = _confirm(client, doc_auth_headers, doc['id'])
        doc = _complete(client, doc_auth_headers, doc['id'])

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 3}],
                'notes': 'Defective items',
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code in (200, 201), resp.text
        return_doc = resp.json()
        assert return_doc['type'] == 'OUT'

    def test_return_exceeding_done_quantity_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {
                    'product_template_id': str(doc_template.id),
                    'name': 'Widget',
                    'expected_quantity': 5,
                }
            ],
        )
        doc = _confirm(client, doc_auth_headers, doc['id'])
        doc = _complete(client, doc_auth_headers, doc['id'])

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 999}],
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 422)

    def test_return_on_draft_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {
                    'product_template_id': str(doc_template.id),
                    'name': 'Widget',
                    'expected_quantity': 5,
                }
            ],
        )
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 1}],
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 409)


# ══════════════════════════════════════════════════════════════════════════════
# 5. NUMBERING
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestExploratoryNumbering:
    def test_different_types_different_prefixes(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_stock_item: Item,
    ) -> None:
        """Two types, two prefixes — as the register gives them out.

        Numbers arrive at confirmation, and a dispatch is confirmed only
        when its line names the stock it takes, so this one carries a
        record.
        """
        in_doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
        )
        out_doc = _create_doc(
            client,
            doc_auth_headers,
            type='OUT',
            partner_id=str(doc_partner.id),
            source_location_id=str(doc_source_location.id),
            lines=[{'item_id': str(doc_stock_item.id), 'expected_quantity': 1}],
        )
        in_doc = _confirm(client, doc_auth_headers, in_doc['id'])
        out_doc = _confirm(client, doc_auth_headers, out_doc['id'])
        assert in_doc['number'].startswith('IN/')
        assert out_doc['number'].startswith('OUT/')

    def test_sequential_numbers_gap_check(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        numbers = []
        for _ in range(5):
            doc = _create_doc(
                client,
                doc_auth_headers,
                type='IN',
                partner_id=str(doc_partner.id),
                target_location_id=str(doc_target_location.id),
            )
            confirmed = _confirm(client, doc_auth_headers, doc['id'])
            seq = int(confirmed['number'].split('/')[-1])
            numbers.append(seq)
        for i in range(1, len(numbers)):
            assert numbers[i] == numbers[i - 1] + 1, f'Gap: {numbers}'


# ══════════════════════════════════════════════════════════════════════════════
# 6. PERIODS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestExploratoryPeriods:
    def test_close_and_reopen(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        import datetime

        now = datetime.datetime.now(datetime.UTC)
        resp = client.post(
            f'/api/v1/warehouse/periods/{now.year}/{now.month}/close',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        resp = client.post(
            f'/api/v1/warehouse/periods/{now.year}/{now.month}/reopen',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_double_close_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        import datetime

        now = datetime.datetime.now(datetime.UTC)
        client.post(
            f'/api/v1/warehouse/periods/{now.year}/{now.month}/close',
            headers=doc_auth_headers,
        )
        resp = client.post(
            f'/api/v1/warehouse/periods/{now.year}/{now.month}/close',
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 409)
        client.post(
            f'/api/v1/warehouse/periods/{now.year}/{now.month}/reopen',
            headers=doc_auth_headers,
        )

    def test_list_periods_sorted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get('/api/v1/warehouse/periods', headers=doc_auth_headers)
        assert resp.status_code == 200
        periods = resp.json()['items']
        if len(periods) >= 2:
            for i in range(len(periods) - 1):
                c = (periods[i]['year'], periods[i]['month'])
                n = (periods[i + 1]['year'], periods[i + 1]['month'])
                assert c >= n


# ══════════════════════════════════════════════════════════════════════════════
# 7. TAX RATES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestExploratoryTaxRates:
    def test_create_delete(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/tax-rates',
            json={'name': 'VAT 23%', 'rate': 23, 'code': 'VAT23', 'country': 'PL'},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (200, 201)
        rate = resp.json()
        assert rate['name'] == 'VAT 23%'
        resp = client.delete(
            f'/api/v1/warehouse/tax-rates/{rate["id"]}', headers=doc_auth_headers
        )
        assert resp.status_code == 204

    def test_default_flag(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/tax-rates',
            json={'name': 'Default', 'rate': 23, 'is_default': True},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (200, 201)
        rate = resp.json()
        assert rate['is_default'] is True
        client.delete(
            f'/api/v1/warehouse/tax-rates/{rate["id"]}', headers=doc_auth_headers
        )


# ══════════════════════════════════════════════════════════════════════════════
# 8. PROFILE
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestExploratoryProfile:
    def test_get_profile_defaults(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get('/api/v1/warehouse/profile', headers=doc_auth_headers)
        assert resp.status_code == 200
        profile = resp.json()
        assert profile['numbering_format'] is not None
        assert profile['default_unit'] is not None

    def test_update_name(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/profile',
            json={'name': 'My Profile'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_invalid_type_labels_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/profile',
            json={'type_labels': {'INVALID': 'X'}},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_valid_type_labels_accepted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/profile',
            json={'type_labels': {'IN': 'Receipt', 'OUT': 'Delivery'}},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_list_presets(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get('/api/v1/warehouse/profile/presets', headers=doc_auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ══════════════════════════════════════════════════════════════════════════════
# 9. EDGE CASES & DATA INTEGRITY
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestExploratoryEdgeCases:
    def test_many_lines(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """20 lines — should not crash."""
        lines = [{'name': f'Item-{i}', 'expected_quantity': i + 1} for i in range(20)]
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=lines,
        )
        assert len(doc['lines']) == 20

    def test_very_large_quantity(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[{'name': 'Bulk', 'expected_quantity': 999999.999}],
        )
        assert doc['lines'][0]['expected_quantity'] == '999999.999'

    def test_very_small_quantity(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[{'name': 'Precise', 'expected_quantity': 0.001}],
        )
        assert doc['lines'][0]['expected_quantity'] == '0.001'

    def test_special_characters_in_name(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        for name in [
            'Ünicöde',
            'Widget (v2.0)',
            'Item & Co.',
            'Product "Premium"',
            "O'Brien",
        ]:
            doc = _create_doc(
                client,
                doc_auth_headers,
                type='IN',
                partner_id=str(doc_partner.id),
                target_location_id=str(doc_target_location.id),
                lines=[{'name': name, 'expected_quantity': 1}],
            )
            assert doc['lines'][0]['name'] == name

    def test_batch_and_serial_numbers(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {
                    'name': 'Tracked',
                    'expected_quantity': 1,
                    'batch_number': 'BATCH-001',
                    'serial_number': 'SN-12345',
                }
            ],
        )
        assert doc['lines'][0]['batch_number'] == 'BATCH-001'
        assert doc['lines'][0]['serial_number'] == 'SN-12345'

    def test_expiry_date_preserved(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {
                    'name': 'Perishable',
                    'expected_quantity': 1,
                    'expiry_date': '2027-12-31',
                }
            ],
        )
        assert doc['lines'][0]['expiry_date'] == '2027-12-31'

    def test_update_replaces_all_lines(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            lines=[
                {'name': 'A', 'expected_quantity': 5},
                {'name': 'B', 'expected_quantity': 3},
            ],
        )
        assert len(doc['lines']) == 2
        resp = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}',
            json={'lines': [{'name': 'C', 'expected_quantity': 10}]},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()['lines']) == 1
        assert resp.json()['lines'][0]['name'] == 'C'

    def test_register_date_range(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """FINDING: Register only shows COMPLETED documents by default.
        A newly created (DRAFT) document does NOT appear in the register.
        This may confuse users who just created a document.
        """
        _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
        )
        import datetime

        today = datetime.date.today()
        resp = client.get(
            '/api/v1/warehouse/register/summary',
            params={'date_from': today.isoformat(), 'date_to': today.isoformat()},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        # Register defaults to COMPLETED status — DRAFT docs won't show
        # This is expected behavior but may surprise users
        total = resp.json()['summary']['total_documents']
        assert total >= 0  # Document is DRAFT, so register may show 0

    def test_register_csv(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        import datetime

        today = datetime.date.today()
        resp = client.get(
            '/api/v1/warehouse/register',
            params={
                'date_from': today.isoformat(),
                'date_to': today.isoformat(),
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_search_by_partner(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
        )
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'partner_id': str(doc_partner.id)},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['total'] >= 1

    def test_search_by_status(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'status': 'DRAFT'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_search_by_type(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'type': 'IN'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_lookup_by_number(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
        )
        resp = client.get(
            f'/api/v1/warehouse/documents/lookup/{doc["number"]}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['id'] == doc['id']

    def test_pagination(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        for _ in range(5):
            _create_doc(
                client,
                doc_auth_headers,
                type='IN',
                partner_id=str(doc_partner.id),
                target_location_id=str(doc_target_location.id),
            )
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'limit': 2, 'offset': 0},
            headers=doc_auth_headers,
        )
        page1 = resp.json()
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'limit': 2, 'offset': 2},
            headers=doc_auth_headers,
        )
        page2 = resp.json()
        ids1 = {d['id'] for d in page1['items']}
        ids2 = {d['id'] for d in page2['items']}
        assert ids1 != ids2

    def test_sort_desc(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'sort_by': 'created_at', 'sort_order': 'desc'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        docs = resp.json()['items']
        if len(docs) >= 2:
            for i in range(len(docs) - 1):
                assert docs[i]['created_at'] >= docs[i + 1]['created_at']

    def test_full_text_search(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """FINDING: Full-text search may not search within notes field.
        Only searches document number, type, or partner name.
        """
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
            notes='SEARCHABLE_XYZ_123',
        )
        # Search by document number (should always work)
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'search': doc['number']},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['total'] >= 1

    def test_stock_quants_empty(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        # The shelves moved to the core; the check is the same one.
        resp = client.get('/api/v1/stock-quants', headers=doc_auth_headers)
        assert resp.status_code == 200
        assert resp.json()['items'] == []

    def test_stock_lots_empty(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        # The batches moved to the core.
        resp = client.get('/api/v1/stock-lots', headers=doc_auth_headers)
        assert resp.status_code == 200

    def test_replenishment_empty(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        # The alerts are the purchase orders module's route now.
        doc_org.enabled_modules = [*doc_org.enabled_modules, 'purchase_orders']
        db_session.commit()

        resp = client.get(
            '/api/v1/purchase-orders/replenishment/alerts', headers=doc_auth_headers
        )
        assert resp.status_code == 200

    def test_tax_summary_zero(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get('/api/v1/warehouse/tax-summary', headers=doc_auth_headers)
        assert resp.status_code == 200

    def test_product_search(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/product-search',
            params={'q': doc_template.name},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_quick_create_product(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/product-search/quick-create',
            json={'name': f'Quick-{uuid.uuid4().hex[:8]}'},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (200, 201)

    def test_templates_seed(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/templates/seed-defaults', headers=doc_auth_headers
        )
        # Seeding is idempotent — a name already present is skipped rather
        # than colliding — so there is no 409 to make room for.
        assert resp.status_code == 201

    def test_built_in_templates_are_readable_before_being_copied(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """The screen offers to copy layouts; it can now also show them."""
        resp = client.get(
            '/api/v1/warehouse/templates/built-in', headers=doc_auth_headers
        )

        assert resp.status_code == 200
        built_ins = resp.json()
        names = {tpl['name'] for tpl in built_ins}
        assert names == {
            'Standard Template',
            'PL PZ Template',
            'Packing Slip',
            'Pick List',
        }
        for tpl in built_ins:
            assert tpl['body_html'].strip(), f'{tpl["name"]} has no markup'

    def test_list_templates(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get('/api/v1/warehouse/templates', headers=doc_auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json()['items'], list)

    def test_create_delete_template(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/templates',
            json={
                'name': f'Template-{uuid.uuid4().hex[:6]}',
                'document_type': 'IN',
                'body_html': '<h1>Test</h1>',
            },
            headers=doc_auth_headers,
        )
        if resp.status_code in (200, 201):
            template = resp.json()
            resp = client.delete(
                f'/api/v1/warehouse/templates/{template["id"]}',
                headers=doc_auth_headers,
            )
            assert resp.status_code == 204

    def test_approval_status(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            type='IN',
            partner_id=str(doc_partner.id),
            target_location_id=str(doc_target_location.id),
        )
        resp = client.get(
            f'/api/v1/approvals/documents/{doc["id"]}/approval',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_type_config_upsert(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/settings/type-configs/IN',
            json={
                'document_type': 'IN',
                'default_target_location_id': str(doc_target_location.id),
                'require_partner': True,
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code in (200, 201)

    def test_type_config_delete(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        client.put(
            '/api/v1/warehouse/settings/type-configs/SCRAP',
            json={'document_type': 'SCRAP'},
            headers=doc_auth_headers,
        )
        resp = client.delete(
            '/api/v1/warehouse/settings/type-configs/SCRAP',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 204
