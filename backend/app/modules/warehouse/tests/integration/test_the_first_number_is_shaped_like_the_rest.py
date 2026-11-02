"""The first document an organization ever issues is numbered like the rest.

The number was built before the numbering profile existed. ``get_profile``
returned nothing, so a default written in the numbering code decided the
padding; the profile created moments later — in the same request — carried
the preset's, and it was a different number. Measured on a clean
organization: ``IN/2026/0001``, then ``IN/2026/002``, then ``OUT/2026/001``.
The register shows numbering that looks broken, on the first document the
user will ever issue.

The fix is not to make the two defaults agree. It is to have one: the
profile is created before the number is drawn, and the default the numbering
code falls back to is the same constant the preset and the column use.

The number is drawn at confirmation now, so a document is *issued* here —
the draft that precedes it carries an identifier of its own, and the
padding question is asked of the number the register hands out.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import sow as _sow


def _issued(client: TestClient, headers: dict[str, str], body: dict[str, Any]) -> str:
    """Create a draft from *body* and confirm it; return its number."""
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=body)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{resp.json()["id"]}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return str(confirmed.json()['number'])


def _receipt_body(
    partner_id: Any, target_location_id: Any, template_id: Any
) -> dict[str, Any]:
    return {
        'type': 'IN',
        'partner_id': str(partner_id),
        'target_location_id': str(target_location_id),
        'lines': [{'product_template_id': str(template_id), 'expected_quantity': '1'}],
    }


def _digits(number: str) -> int:
    match = re.search(r'(\d+)$', number)
    assert match, number
    return len(match.group(1))


@pytest.mark.integration
class TestTheFirstNumberMatchesTheRest:
    def test_three_documents_in_a_row_are_padded_the_same(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_item: Item,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '10',
        )
        numbers = [
            _issued(
                client,
                doc_auth_headers,
                _receipt_body(doc_partner.id, doc_target_location.id, doc_template.id),
            )
            for _ in range(2)
        ]
        numbers.append(
            _issued(
                client,
                doc_auth_headers,
                {
                    'type': 'OUT',
                    'partner_id': str(doc_partner.id),
                    'source_location_id': str(doc_source_location.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': [
                        {
                            'item_id': str(doc_item.id),
                            'product_template_id': str(doc_template.id),
                            'expected_quantity': '1',
                        }
                    ],
                },
            )
        )

        widths = {_digits(n) for n in numbers}
        assert len(widths) == 1, (
            f'the register shows three widths for three documents: {numbers}'
        )

    def test_the_first_number_agrees_with_the_profile_that_numbers_the_rest(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        first = _issued(
            client,
            doc_auth_headers,
            _receipt_body(doc_partner.id, doc_target_location.id, doc_template.id),
        )

        profile = client.get(
            '/api/v1/warehouse/profile', headers=doc_auth_headers
        ).json()

        assert _digits(first) == profile['number_padding']
