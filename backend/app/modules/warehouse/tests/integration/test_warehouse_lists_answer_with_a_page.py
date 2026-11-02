"""A warehouse list answers with a page: ``items`` plus how to ask for the rest.

The warehouse lists answered with a bare JSON array. They now answer with the
documented ``PaginatedResponse`` (``docs/subsystems/PAGINATION.md``). Two roads
reach it and both are pinned: a list sliced whole in memory (the tax rates),
and a list whose rows are dressed with display names only for the page served
(the putaway rules) — the second is where ``total`` could quietly become the
size of the page instead of the size of the list.
"""

from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.organization import Organization
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration

TAX_RATES_URL = '/api/v1/warehouse/tax-rates'
PUTAWAY_RULES_URL = '/api/v1/warehouse/putaway-rules'


def _page(
    client: TestClient, headers: dict[str, str], path: str, **params: Any
) -> dict[str, Any]:
    response = client.get(path, headers=headers, params=params)
    assert response.status_code == status.HTTP_200_OK, response.text
    page: dict[str, Any] = response.json()
    return page


class TestASmallListIsSlicedWithItsTrueTotal:
    def test_the_pages_together_hold_every_rate_once(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        for rate in ('23.00', '8.00', '5.00'):
            created = client.post(
                TAX_RATES_URL,
                headers=doc_auth_headers,
                json={'name': f'VAT {rate}', 'rate': rate},
            )
            assert created.status_code == status.HTTP_201_CREATED, created.text

        first = _page(client, doc_auth_headers, TAX_RATES_URL, limit=2)
        rest = _page(client, doc_auth_headers, TAX_RATES_URL, limit=2, offset=2)
        whole = _page(client, doc_auth_headers, TAX_RATES_URL)

        assert first['total'] == rest['total'] == 3
        assert (len(first['items']), first['has_more']) == (2, True)
        assert (len(rest['items']), rest['has_more']) == (1, False)
        assert [r['id'] for r in first['items'] + rest['items']] == [
            r['id'] for r in whole['items']
        ]

    def test_a_page_larger_than_the_cap_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            TAX_RATES_URL, headers=doc_auth_headers, params={'limit': 201}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestADressedListCountsEveryRow:
    def test_the_rules_page_names_its_category_and_counts_the_rest(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        for priority, name in enumerate(('Dry goods', 'Chilled', 'Frozen'), start=1):
            category = Category(organization_id=doc_org.id, name=name)
            db_session.add(category)
            db_session.commit()
            created = client.post(
                PUTAWAY_RULES_URL,
                headers=doc_auth_headers,
                json={
                    'category_id': str(category.id),
                    'target_location_id': str(doc_target_location.id),
                    'priority': priority,
                },
            )
            assert created.status_code == status.HTTP_201_CREATED, created.text

        page = _page(client, doc_auth_headers, PUTAWAY_RULES_URL, limit=1, offset=1)

        assert page['total'] == 3
        assert page['has_more'] is True
        (rule,) = page['items']
        assert rule['category_name'] == 'Chilled'
        assert rule['target_location_name'] == doc_target_location.name
