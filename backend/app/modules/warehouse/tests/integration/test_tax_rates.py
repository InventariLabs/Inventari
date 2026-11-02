from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from app.models.organization import Organization

pytestmark = pytest.mark.integration


TAX_RATES_URL = '/api/v1/warehouse/tax-rates'
TAX_SUMMARY_URL = '/api/v1/warehouse/tax-summary'


def _create_rate(
    client: TestClient,
    auth_headers: dict[str, str],
    name: str = 'Standard VAT',
    rate: str = '23.00',
    **kwargs: Any,
) -> Response:
    payload = {'name': name, 'rate': rate, **kwargs}
    return client.post(TAX_RATES_URL, json=payload, headers=auth_headers)  # type: ignore[no-any-return]


class TestTaxRateCRUD:
    def test_create_tax_rate_success(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = _create_rate(client, doc_auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data['name'] == 'Standard VAT'
        assert Decimal(data['rate']) == Decimal('23.00')
        assert data['is_default'] is False

    def test_list_tax_rates_empty(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(TAX_RATES_URL, headers=doc_auth_headers)
        assert resp.status_code == 200
        assert resp.json()['items'] == []

    def test_list_tax_rates_returns_created(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        _create_rate(client, doc_auth_headers, name='VAT 23', rate='23.00')
        _create_rate(client, doc_auth_headers, name='VAT 8', rate='8.00')
        resp = client.get(TAX_RATES_URL, headers=doc_auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()['items']) == 2

    def test_get_tax_rate_by_id(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        created = _create_rate(client, doc_auth_headers)
        rate_id = created.json()['id']
        resp = client.get(f'{TAX_RATES_URL}/{rate_id}', headers=doc_auth_headers)
        assert resp.status_code == 200
        assert resp.json()['name'] == 'Standard VAT'

    def test_get_tax_rate_not_found(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            f'{TAX_RATES_URL}/00000000-0000-0000-0000-000000000000',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 404

    def test_update_tax_rate(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        created = _create_rate(client, doc_auth_headers)
        rate_id = created.json()['id']
        resp = client.put(
            f'{TAX_RATES_URL}/{rate_id}',
            json={'name': 'Reduced VAT', 'rate': '8.00'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['name'] == 'Reduced VAT'
        assert Decimal(resp.json()['rate']) == Decimal('8.00')

    def test_delete_tax_rate(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        created = _create_rate(client, doc_auth_headers)
        rate_id = created.json()['id']
        resp = client.delete(f'{TAX_RATES_URL}/{rate_id}', headers=doc_auth_headers)
        assert resp.status_code == 204
        resp = client.get(f'{TAX_RATES_URL}/{rate_id}', headers=doc_auth_headers)
        assert resp.status_code == 404

    def test_delete_tax_rate_not_found(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.delete(
            f'{TAX_RATES_URL}/00000000-0000-0000-0000-000000000000',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 404


class TestTaxRateDefault:
    def test_single_default_enforced(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        r1 = _create_rate(
            client, doc_auth_headers, name='VAT 23', rate='23.00', is_default=True
        )
        _create_rate(
            client, doc_auth_headers, name='VAT 8', rate='8.00', is_default=True
        )
        assert r1.json()['is_default'] is True
        check = client.get(
            f'{TAX_RATES_URL}/{r1.json()["id"]}', headers=doc_auth_headers
        )
        assert check.json()['is_default'] is False

    def test_set_default_via_update(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        r1 = _create_rate(
            client, doc_auth_headers, name='VAT 23', rate='23.00', is_default=True
        )
        r2 = _create_rate(client, doc_auth_headers, name='VAT 8', rate='8.00')
        client.put(
            f'{TAX_RATES_URL}/{r2.json()["id"]}',
            json={'is_default': True},
            headers=doc_auth_headers,
        )
        check = client.get(
            f'{TAX_RATES_URL}/{r1.json()["id"]}', headers=doc_auth_headers
        )
        assert check.json()['is_default'] is False


class TestTaxSummary:
    def test_tax_summary_empty(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(TAX_SUMMARY_URL, headers=doc_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['lines'] == []
        assert Decimal(data['total_net']) == Decimal('0.00')
        assert data['org_tax_id'] is None

    def test_tax_summary_with_org_tax_id(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        doc_org.tax_id = 'PL1234567890'
        doc_org.country = 'PL'
        db_session.commit()

        resp = client.get(TAX_SUMMARY_URL, headers=doc_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['org_tax_id'] == 'PL1234567890'
        assert data['org_country'] == 'PL'
