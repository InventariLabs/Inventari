"""
Integration tests for Document Register — the paged one.

The register used to fetch every document in the window — the sums
and the rows arrived in one answer, and a year of a busy warehouse grew both
the payload and the DOM it fed. The sums now come from a SQL GROUP BY over
the whole window, the rows are one page of one group, and the CSV export is
the only answer without a limit.

Verifies:
- Summary: date-range filtering, type filter, group_by, group sums and the
  no-label bucket
- Rows: paging inside one group, the group's total, the stable order
- Group sums agree with what the rows add up to — the regression pagination
  could have broken
- CSV export returns the complete set with correct headers
- Organization isolation (no cross-tenant data)
"""

import csv
import io
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from app.core.export_hygiene import defuse
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document


def _create_and_complete_in(
    client: TestClient,
    headers: dict[str, str],
    target_location_id: uuid.UUID,
    template_id: uuid.UUID,
    partner_id: uuid.UUID,
    quantity: int = 5,
) -> dict[str, Any]:
    """Helper: create, confirm, and complete an IN document."""
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                    'done_quantity': quantity,
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()['id']
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == 200, done.text
    # The number is given out at confirmation: the create response was the
    # draft's identifier, and the register rows carry the number.
    return cast(dict[str, Any], {**resp.json(), 'number': confirmed.json()['number']})


def _enable_value_tracking(client: TestClient, headers: dict[str, str]) -> None:
    profile = client.get('/api/v1/warehouse/profile', headers=headers).json()
    client.put(
        '/api/v1/warehouse/profile',
        headers=headers,
        json={
            **{
                k: v
                for k, v in profile.items()
                if k not in ('id', 'organization_id', 'created_at', 'updated_at')
            },
            'value_tracking_enabled': True,
        },
    )


def _summary_url(date_from: date, date_to: date, **kwargs: Any) -> str:
    base = f'/api/v1/warehouse/register/summary?date_from={date_from}&date_to={date_to}'
    for k, v in kwargs.items():
        base += f'&{k}={v}'
    return base


def _rows_url(
    date_from: date,
    date_to: date,
    group_key: str,
    **kwargs: Any,
) -> str:
    base = (
        '/api/v1/warehouse/register/rows'
        f'?date_from={date_from}&date_to={date_to}&group_key={group_key}'
    )
    for k, v in kwargs.items():
        base += f'&{k}={v}'
    return base


def _csv_url(date_from: date, date_to: date, **kwargs: Any) -> str:
    base = f'/api/v1/warehouse/register?date_from={date_from}&date_to={date_to}'
    for k, v in kwargs.items():
        base += f'&{k}={v}'
    return base


@pytest.mark.integration
class TestDocumentRegisterBasic:
    """Basic register summary endpoint tests."""

    def test_register_returns_completed_documents(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Summary returns aggregated data for completed documents."""
        _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        today = date.today()
        url = f'/api/v1/warehouse/register/summary?date_from={today}&date_to={today}'
        resp = client.get(url, headers=doc_auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert 'groups' in data
        assert 'summary' in data
        assert data['summary']['total_documents'] >= 1

    def test_register_empty_range(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """Register returns empty groups for a future date range."""
        resp = client.get(
            '/api/v1/warehouse/register/summary?date_from=2099-01-01&date_to=2099-01-31',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data['summary']['total_documents'] == 0
        assert data['groups'] == []

    def test_register_requires_date_params(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """Register returns 422 when date_from or date_to is missing."""
        resp = client.get(
            '/api/v1/warehouse/register/summary', headers=doc_auth_headers
        )
        assert resp.status_code == 422

    def test_register_summary_carries_no_document_rows(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """The answer's size stops depending on the window's size.

        The register used to fetch every document in the window, so a year of
        a busy warehouse came back as thousands of rows for the DOM to
        render. The summary carries one tuple per group — the rows live at
        the rows endpoint, one page at a time.
        """
        for _ in range(3):
            _create_and_complete_in(
                client,
                doc_auth_headers,
                doc_target_location.id,
                doc_template.id,
                doc_partner.id,
            )
        today = date.today()
        url = f'/api/v1/warehouse/register/summary?date_from={today}&date_to={today}'
        resp = client.get(url, headers=doc_auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data['summary']['total_documents'] >= 3
        assert data['groups'], 'expected at least one group'
        assert all('documents' not in g for g in data['groups']), (
            'the summary must not carry document rows'
        )


@pytest.mark.integration
class TestDocumentRegisterFilters:
    """Tests for type and group_by filters."""

    def test_register_filter_by_type(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Type filter returns only documents of the requested type."""
        _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        today = date.today()
        url = f'{_summary_url(today, today)}&type=OUT'
        resp = client.get(url, headers=doc_auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data['summary']['total_documents'] == 0
        assert data['groups'] == []

    def test_register_group_by_location_names_the_shelf_it_moved_to(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """An IN document groups under its target shelf, named."""
        _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )

        today = date.today()
        data = client.get(
            _summary_url(today, today, group_by='location'), headers=doc_auth_headers
        ).json()

        assert doc_target_location.name in [g['label'] for g in data['groups']]

    def test_an_archived_shelf_still_names_its_group(
        self,
        db_session: Session,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """The register names where a document went, archived or not."""
        _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        # Archived after the goods went there: the completion refuses an
        # archived target, but the document that already landed still has to
        # print the shelf it moved to.
        doc_target_location.settings = {'archived': True}
        db_session.add(doc_target_location)
        db_session.commit()

        today = date.today()
        data = client.get(
            _summary_url(today, today, group_by='location'), headers=doc_auth_headers
        ).json()

        assert doc_target_location.name in [g['label'] for g in data['groups']]

    def test_register_group_by_partner(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """group_by=partner names a group after the partner."""
        _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        today = date.today()
        url = f'{_summary_url(today, today)}&group_by=partner'
        resp = client.get(url, headers=doc_auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data['group_by'] == 'partner'
        assert len(data['groups']) >= 1
        assert doc_partner.name in [g['label'] for g in data['groups']]

    def test_register_partnerless_group_carries_no_label(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """A document with no partner lands in a group with no label.

        The service used to send an em dash as the label, which the register
        then printed as the group's name: a display string, untranslated,
        travelling as data. The bucket has no name of its own — naming it is
        the reader's job.
        """
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 2,
                        'done_quantity': 2,
                    }
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        doc_id = resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        today = date.today()
        data = client.get(
            _summary_url(today, today, group_by='partner'), headers=doc_auth_headers
        ).json()

        partnerless = [g for g in data['groups'] if g['label'] is None]
        assert partnerless, 'the partnerless document did not reach the register'
        for group in partnerless:
            assert group['label'] is None
            assert group['key'] == ''

        # The anonymous bucket is pageable like any other: the rows endpoint
        # serves it by its empty key.
        rows = client.get(
            _rows_url(today, today, '', group_by='partner'),
            headers=doc_auth_headers,
        ).json()
        assert rows['total'] >= 1
        assert all(r['partner_name'] is None for r in rows['items'])

    def test_register_group_by_month(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """group_by=month groups documents by calendar month."""
        _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        today = date.today()
        url = _summary_url(date(today.year, 1, 1), today, group_by='month')
        resp = client.get(url, headers=doc_auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data['group_by'] == 'month'
        # Keys should look like 'YYYY-MM'
        for group in data['groups']:
            assert len(group['key']) == 7
            assert group['key'][4] == '-'


@pytest.mark.integration
class TestDocumentRegisterRows:
    """The rows endpoint: one group, one page."""

    def _make_three(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> list[str]:
        numbers = []
        for _ in range(3):
            doc = _create_and_complete_in(
                client,
                doc_auth_headers,
                doc_target_location.id,
                doc_template.id,
                doc_partner.id,
            )
            numbers.append(doc['number'])
        return numbers

    def test_rows_are_limited_to_one_page(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """The page holds `limit` rows even when the window holds more.

        The row count in the answer must not depend on the size of the
        window — that was the whole point of the change.
        """
        numbers = self._make_three(
            client, doc_auth_headers, doc_target_location, doc_template, doc_partner
        )
        today = date.today()
        resp = client.get(
            _rows_url(today, today, 'IN', limit=2), headers=doc_auth_headers
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data['total'] >= 3
        assert len(data['items']) == 2
        assert all(r['number'] in numbers for r in data['items'])

    def test_rows_pages_do_not_overlap(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Two pages of one group hold different rows and cover the group.

        The order needs a deterministic tiebreaker: several documents created
        in the same test share a created_at second, and an unstable order
        would deal the same row onto two pages and drop another entirely.
        """
        numbers = self._make_three(
            client, doc_auth_headers, doc_target_location, doc_template, doc_partner
        )
        today = date.today()

        page1 = client.get(
            _rows_url(today, today, 'IN', limit=2, offset=0),
            headers=doc_auth_headers,
        ).json()
        page2 = client.get(
            _rows_url(today, today, 'IN', limit=2, offset=2),
            headers=doc_auth_headers,
        ).json()

        assert page1['total'] >= 3
        assert len(page1['items']) == 2
        ids_one = {r['id'] for r in page1['items']}
        ids_two = {r['id'] for r in page2['items']}
        assert ids_one.isdisjoint(ids_two)
        all_seen = client.get(
            _rows_url(today, today, 'IN', limit=200),
            headers=doc_auth_headers,
        ).json()
        assert set(numbers) <= {r['number'] for r in all_seen['items']}
        # oldest first, the order the register reads
        dates = [r['date'] for r in all_seen['items']]
        assert dates == sorted(dates)

    def test_rows_stay_inside_the_requested_group(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """A page for one group never carries another group's rows."""
        self._make_three(
            client, doc_auth_headers, doc_target_location, doc_template, doc_partner
        )
        today = date.today()
        page = client.get(
            _rows_url(today, today, 'IN', limit=200), headers=doc_auth_headers
        ).json()
        assert page['items'], 'expected rows in the IN group'
        assert all(r['type'] == 'IN' for r in page['items'])

    def test_rows_total_counts_the_group_not_the_page(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """`total` counts the group, so the reader knows a page came short."""
        self._make_three(
            client, doc_auth_headers, doc_target_location, doc_template, doc_partner
        )
        today = date.today()
        page = client.get(
            _rows_url(today, today, 'IN', limit=2), headers=doc_auth_headers
        ).json()
        assert page['total'] > len(page['items'])
        assert (page['limit'], page['offset']) == (2, 0)
        assert page['has_more'] is True


@pytest.mark.integration
class TestDocumentRegisterTotals:
    """Group + summary totals over the whole window."""

    def test_register_totals_per_row_and_group(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Row and group expose decimal net/tax/gross strings."""
        _enable_value_tracking(client, doc_auth_headers)

        # A doc with explicit unit_price + tax_rate so totals are deterministic.
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 2,
                        'unit_price': '10.00',
                        'tax_rate': '23.00',
                    }
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        doc_id = resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        today = date.today()
        summary = client.get(
            _summary_url(today, today), headers=doc_auth_headers
        ).json()
        assert summary['groups'], 'expected at least one group'
        group = summary['groups'][0]
        # Group totals match the single document.
        assert group['total_net'] == '20.00'
        assert group['total_tax'] == '4.60'
        assert group['total_gross'] == '24.60'
        # single-currency group carries its currency.
        rows_probe = client.get(
            _rows_url(today, today, group['key']), headers=doc_auth_headers
        ).json()
        row_currency = rows_probe['items'][0]['currency']
        assert group['currency'] == row_currency
        assert len(group['totals_by_currency']) == 1
        assert group['totals_by_currency'][0]['currency'] == group['currency']
        # Summary matches.
        assert summary['summary']['total_net'] == '20.00'
        assert summary['summary']['total_tax'] == '4.60'
        assert summary['summary']['total_gross'] == '24.60'
        assert summary['summary']['currency'] == group['currency']
        assert len(summary['summary']['totals_by_currency']) == 1
        # The row itself, from the rows endpoint, carries the same figures.
        assert rows_probe['items'][0]['total_net'] == '20.00'
        assert rows_probe['items'][0]['total_tax'] == '4.60'
        assert rows_probe['items'][0]['total_gross'] == '24.60'

    def test_register_totals_group_aggregation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Two completed IN docs in the same group sum into group totals."""
        _enable_value_tracking(client, doc_auth_headers)

        # Same line payload twice → both docs land in the same IN group.
        for _ in range(2):
            resp = client.post(
                '/api/v1/warehouse/documents',
                headers=doc_auth_headers,
                json={
                    'type': 'IN',
                    'partner_id': str(doc_partner.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': [
                        {
                            'product_template_id': str(doc_template.id),
                            'expected_quantity': 1,
                            'unit_price': '10.00',
                            'tax_rate': '23.00',
                        }
                    ],
                },
            )
            assert resp.status_code == 201, resp.text
            doc_id = resp.json()['id']
            client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/confirm',
                headers=doc_auth_headers,
            )
            client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/complete',
                headers=doc_auth_headers,
                json={'complete_as_planned': True},
            )

        today = date.today()
        summary = client.get(
            _summary_url(today, today), headers=doc_auth_headers
        ).json()

        assert summary['summary']['total_documents'] >= 2
        assert summary['summary']['total_net'] == '20.00'
        assert summary['summary']['total_tax'] == '4.60'
        assert summary['summary']['total_gross'] == '24.60'
        # Group-level totals also reflect the aggregation.
        assert summary['groups'][0]['total_net'] == '20.00'
        assert summary['groups'][0]['total_tax'] == '4.60'
        assert summary['groups'][0]['total_gross'] == '24.60'

    def test_register_multi_currency_never_cross_sums(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        db_session: Session,
    ) -> None:
        """PLN + EUR docs in one group → per-currency sums, no lie."""
        _enable_value_tracking(client, doc_auth_headers)

        for currency in ('PLN', 'EUR'):
            resp = client.post(
                '/api/v1/warehouse/documents',
                headers=doc_auth_headers,
                json={
                    'type': 'IN',
                    'partner_id': str(doc_partner.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': [
                        {
                            'product_template_id': str(doc_template.id),
                            'expected_quantity': 1,
                            'unit_price': '10.00',
                            'tax_rate': '23.00',
                        }
                    ],
                },
            )
            assert resp.status_code == 201, resp.text
            doc_id = uuid.UUID(resp.json()['id'])
            doc = db_session.get(Document, doc_id)
            assert doc is not None
            doc.currency = currency
            db_session.commit()
            client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/confirm',
                headers=doc_auth_headers,
            )
            client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/complete',
                headers=doc_auth_headers,
                json={'complete_as_planned': True},
            )

        today = date.today()
        data = client.get(_summary_url(today, today), headers=doc_auth_headers).json()

        group = data['groups'][0]
        assert group['currency'] is None
        assert group['total_net'] is None
        assert group['total_tax'] is None
        assert group['total_gross'] is None
        assert len(group['totals_by_currency']) == 2
        by_cur = {t['currency']: t for t in group['totals_by_currency']}
        assert by_cur['PLN']['total_net'] == '10.00'
        assert by_cur['PLN']['total_gross'] == '12.30'
        assert by_cur['EUR']['total_net'] == '10.00'
        assert by_cur['EUR']['total_gross'] == '12.30'

        summary = data['summary']
        assert summary['currency'] is None
        assert summary['total_gross'] is None
        assert {t['currency'] for t in summary['totals_by_currency']} == {
            'PLN',
            'EUR',
        }
        assert summary['totals_by_currency'][0]['total_gross'] == '12.30'

    def test_group_sums_agree_with_the_rows_they_sum(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """The regression pagination could have caused, pinned.

        The sums describe the whole window while the rows come one page at a
        time — a page-based implementation would make the group total equal
        the page instead of the group.
        """
        _enable_value_tracking(client, doc_auth_headers)
        numbers = []
        for _ in range(3):
            resp = client.post(
                '/api/v1/warehouse/documents',
                headers=doc_auth_headers,
                json={
                    'type': 'IN',
                    'partner_id': str(doc_partner.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': [
                        {
                            'product_template_id': str(doc_template.id),
                            'expected_quantity': 1,
                            'unit_price': '10.00',
                            'tax_rate': '23.00',
                        }
                    ],
                },
            )
            assert resp.status_code == 201, resp.text
            doc_id = resp.json()['id']
            numbers.append(doc_id)
            client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/confirm',
                headers=doc_auth_headers,
            )
            client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/complete',
                headers=doc_auth_headers,
                json={'complete_as_planned': True},
            )

        today = date.today()
        summary = client.get(
            _summary_url(today, today), headers=doc_auth_headers
        ).json()
        group = summary['groups'][0]
        # Three documents at 10.00 net: the whole window, not the page of 2.
        assert Decimal(str(group['total_net'])) >= Decimal('30.00')

        rows = client.get(
            _rows_url(today, today, group['key'], limit=200),
            headers=doc_auth_headers,
        ).json()
        page_net = sum(Decimal(r['total_net']) for r in rows['items'] if r['total_net'])
        assert page_net >= Decimal('30.00')


@pytest.mark.integration
class TestDocumentRegisterCsv:
    """CSV export tests — the export stays the way to get everything."""

    def test_register_csv_export_headers(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """CSV export returns correct column headers."""
        _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        today = date.today()
        resp = client.get(_csv_url(today, today), headers=doc_auth_headers)
        assert resp.status_code == 200, resp.text
        assert 'text/csv' in resp.headers.get('content-type', '')
        reader = csv.DictReader(io.StringIO(resp.text))
        expected_headers = {
            'Document Number',
            'Type',
            'Date',
            'Partner',
            'Source Location',
            'Target Location',
            'Net',
            'Tax',
            'Gross',
            'Currency',
            'Status',
        }
        assert set(reader.fieldnames or []) == expected_headers

    def test_register_csv_contains_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """CSV export rows include the created document."""
        doc = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        today = date.today()
        resp = client.get(_csv_url(today, today), headers=doc_auth_headers)
        assert resp.status_code == 200, resp.text
        reader = csv.DictReader(io.StringIO(resp.text))
        numbers = [row['Document Number'] for row in reader]
        assert doc['number'] in numbers

    def test_register_csv_returns_everything_past_any_page(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """The paged register must not shrink the export.

        The export used to read the register's groups; once the register
        started serving pages, the export would have silently lost everything
        past page one. It queries its own rows, and no limit touches it.
        """
        numbers = []
        for _ in range(3):
            doc = _create_and_complete_in(
                client,
                doc_auth_headers,
                doc_target_location.id,
                doc_template.id,
                doc_partner.id,
            )
            numbers.append(doc['number'])
        today = date.today()
        resp = client.get(_csv_url(today, today), headers=doc_auth_headers)
        assert resp.status_code == 200, resp.text
        reader = csv.DictReader(io.StringIO(resp.text))
        exported = [row['Document Number'] for row in reader]
        assert set(numbers) <= set(exported)

    def test_the_export_reads_no_line_and_no_column_it_does_not_print(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """The file prints document headers, so a header is all it reads.

        Asking for whole documents loaded every line, product, partner and
        user of the window through the relations: 1.2 GB of memory for a
        1.8 MB file of 20 000 documents of ten lines.
        """
        _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        statements: list[str] = []

        def _record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            statements.append(statement)

        # The request runs on the app's engine; the listener sits on the class.
        event.listen(Engine, 'before_cursor_execute', _record)
        try:
            today = date.today()
            resp = client.get(_csv_url(today, today), headers=doc_auth_headers)
        finally:
            event.remove(Engine, 'before_cursor_execute', _record)

        assert resp.status_code == 200, resp.text
        assert not [s for s in statements if 'document_lines' in s]
        (rows_read,) = [s for s in statements if 'documents.number' in s]
        assert 'documents.meta_data' not in rows_read

    def test_the_export_prints_what_the_rows_of_the_register_print(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Each fallback of a row, read back from the file and from the page.

        The frozen partner name wins over the live one, the live one stands in
        when nothing was frozen, and a document with no planned date is filed
        under the day it was written.
        """
        frozen, live, undated = (
            _create_and_complete_in(
                client,
                doc_auth_headers,
                doc_target_location.id,
                doc_template.id,
                doc_partner.id,
            )
            for _ in range(3)
        )
        today = date.today()
        for doc, snapshot in (
            (frozen, {'name': '=Frozen Ltd'}),
            (live, None),
            (undated, {'tax_id': '123'}),
        ):
            stored = db_session.get(Document, uuid.UUID(doc['id']))
            assert stored is not None
            stored.partner_snapshot = snapshot
            stored.scheduled_date = None if doc is undated else today
            if doc is undated:
                stored.total_net = None
                stored.total_tax = None
                stored.total_gross = None
                stored.currency = None
            else:
                stored.total_net = Decimal('10.00')
                stored.total_tax = Decimal('2.30')
                stored.total_gross = Decimal('12.30')
                stored.currency = 'PLN'
        db_session.commit()

        resp = client.get(_csv_url(today, today), headers=doc_auth_headers)
        assert resp.status_code == 200, resp.text
        rows = {
            row['Document Number']: row
            for row in csv.DictReader(io.StringIO(resp.text))
        }
        page = client.get(
            _rows_url(today, today, 'IN', group_by='type'), headers=doc_auth_headers
        ).json()['items']

        assert rows[frozen['number']]['Partner'] == defuse('=Frozen Ltd')
        assert rows[live['number']]['Partner'] == doc_partner.name
        assert rows[undated['number']]['Partner'] == doc_partner.name
        for shown in page:
            row = rows[shown['number']]
            assert row['Type'] == shown['type']
            assert row['Status'] == shown['status']
            assert row['Date'] == shown['date'] == str(today)
            assert row['Target Location'] == shown['target_location_name']
            assert row['Source Location'] == ''
        assert rows[frozen['number']]['Net'] == '10.00'
        assert rows[frozen['number']]['Tax'] == '2.30'
        assert rows[frozen['number']]['Gross'] == '12.30'
        assert rows[frozen['number']]['Currency'] == 'PLN'
        for column in ('Net', 'Tax', 'Gross', 'Currency'):
            assert rows[undated['number']][column] == ''

    @pytest.mark.parametrize(
        ('language', 'sentence'),
        [
            ('en', 'The start date must not be after the end date'),
            ('pl', 'Data początkowa nie może być późniejsza niż data końcowa'),
        ],
    )
    def test_a_range_that_ends_before_it_starts_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        language: str,
        sentence: str,
    ) -> None:
        """An empty file says nothing about why it is empty; the refusal does."""
        resp = client.get(
            _csv_url(date(2026, 2, 1), date(2026, 1, 31)),
            headers={**doc_auth_headers, 'Accept-Language': language},
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()['detail']['message'] == sentence

    def test_a_range_of_one_day_is_not_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        day = date(2026, 1, 31)
        resp = client.get(_csv_url(day, day), headers=doc_auth_headers)
        assert resp.status_code == 200, resp.text


@pytest.mark.integration
class TestDocumentRegisterSecurity:
    """Organization isolation and auth tests."""

    def test_register_requires_auth(self, client: TestClient) -> None:
        """Register endpoints require authentication."""
        today = date.today()
        resp = client.get(
            f'/api/v1/warehouse/register/summary?date_from={today}&date_to={today}'
        )
        assert resp.status_code == 401
        resp = client.get(
            f'/api/v1/warehouse/register/rows?date_from={today}&date_to={today}'
        )
        assert resp.status_code == 401

    def test_register_org_isolation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        db_session: Session,
    ) -> None:
        """Register does not return documents from other organizations."""
        from app.models import Organization, User
        from app.services.token_service import get_password_hash

        # Create a second org and user
        other_org = Organization(
            name='Other Org Register', enabled_modules=['warehouse']
        )
        db_session.add(other_org)
        db_session.commit()
        db_session.refresh(other_org)

        other_user = User(
            email='other_register@example.com',
            hashed_password=get_password_hash('password123'),
            organization_id=other_org.id,
            is_active=True,
            is_superuser=False,
        )
        db_session.add(other_user)
        db_session.commit()

        # Get auth token for second user
        login = client.post(
            '/api/v1/auth/login',
            data={'username': 'other_register@example.com', 'password': 'password123'},
        )
        assert login.status_code == 200, login.text
        other_headers = {'Authorization': f'Bearer {login.json()["access_token"]}'}

        # Register for other org should be empty
        today = date.today()
        url = f'/api/v1/warehouse/register/summary?date_from={today}&date_to={today}'
        resp = client.get(url, headers=other_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data['summary']['total_documents'] == 0


@pytest.mark.integration
class TestDocumentRegisterIndex:
    """The index the pagination leans on."""

    def test_the_window_index_exists(
        self,
        db_session: Session,
    ) -> None:
        """(organization_id, status, created_at) is on the table.

        The register filters by org + status and sorts by created_at; without
        this index every page sorted the whole matching set, so pagination
        moved the cost instead of removing it. The tests build the schema
        from model metadata, so this pins the model declaration that the
        production migration mirrors.
        """
        from sqlalchemy import inspect

        bind = db_session.bind
        assert bind is not None
        inspector = inspect(bind)
        indexes = {
            ix['name']: ix['column_names'] for ix in inspector.get_indexes('documents')
        }
        assert indexes.get('ix_document_org_status_created_at') == [
            'organization_id',
            'status',
            'created_at',
        ]
