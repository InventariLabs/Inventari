"""Reports and lists over more products and places than one statement may bind.

The driver refuses a statement that carries more than 32 767 parameters, and
a query that bound an organization's product or location ids one by one —
``IN (:id_1, :id_2, …)`` — crossed that at a hundred thousand products: the
occupancy overview, stock as of a date and the valuation answered 500, and so
did the product list, the record card and the location list once an
organization had more locations than that. The ids now travel as one array
(``db_utils.in_ids``), or are not listed at all: the product list names the
organization instead of every one of its locations.

The fixture writes one product past the limit, each with stock on one shelf,
and as many locations, straight in SQL — seeding them through the API would
cost minutes. Every answer has to be a 200, and no statement behind it may
carry more than a page's worth of parameters: a 200 alone would not tell a
query that binds one parameter per id from one that does not, below the
driver's limit.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User

pytestmark = pytest.mark.integration

#: One past what a single statement may bind.
_PAST_THE_LIMIT = 32_768

#: More parameters than any statement behind these screens needs once no id
#: list is bound one by one; a statement binding the catalogue carries tens
#: of thousands.
_PARAMETERS_A_STATEMENT_NEEDS = 200

_SEED = text(
    """
    WITH products AS (
        INSERT INTO product_templates (id, organization_id, name, created_at, updated_at)
        SELECT gen_random_uuid(), :org_id, 'Bulk product ' || n, now(), now()
        FROM generate_series(1, :count) AS n
        RETURNING id
    ), anchors AS (
        INSERT INTO stock_anchors (
            id, organization_id, product_template_id, storage_location_id, created_at
        )
        SELECT gen_random_uuid(), :org_id, id, :shelf_id, now() FROM products
        RETURNING product_template_id
    )
    INSERT INTO items (
        id, organization_id, storage_location_id, template_id, name, quantity,
        added_date, is_deleted, is_catalog_entry, created_at, updated_at
    )
    SELECT gen_random_uuid(), :org_id, :shelf_id, product_template_id,
           'Bulk record', 1, current_date, false, false, now(), now()
    FROM anchors
    """
)

_PLACES = text(
    """
    INSERT INTO storage_locations (
        id, organization_id, name, usage, behavior_mode, context_schema,
        field_definitions, created_at, created_by
    )
    SELECT gen_random_uuid(), :org_id, 'Bin ' || n, 'internal', 'STOCK',
           '[]', '[]', now(), :user_id
    FROM generate_series(1, :count) AS n
    """
)


@pytest.fixture
def past_the_limit(
    db_session: Session,
    doc_org: Organization,
    doc_user: User,
    doc_target_location: StorageLocation,
) -> Organization:
    params = {'org_id': doc_org.id, 'count': _PAST_THE_LIMIT}
    db_session.execute(_SEED, {**params, 'shelf_id': doc_target_location.id})
    db_session.execute(_PLACES, {**params, 'user_id': doc_user.id})
    db_session.commit()
    return doc_org


@pytest.fixture
def widest_statement(async_engine_fixture: AsyncEngine) -> Iterator[list[int]]:
    """How many parameters the widest statement of the request carried."""
    widest = [0]

    def measure(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        widest[0] = max(widest[0], len(parameters or ()))

    engine = async_engine_fixture.sync_engine
    event.listen(engine, 'before_cursor_execute', measure)
    yield widest
    event.remove(engine, 'before_cursor_execute', measure)


def _get(client: TestClient, headers: dict[str, str], path: str, **params: Any) -> Any:
    response = client.get(path, headers=headers, params=params)
    assert response.status_code == status.HTTP_200_OK, response.text[:500]
    return response.json()


@pytest.mark.usefixtures('past_the_limit')
class TestPastTheBindLimit:
    def test_the_occupancy_overview_counts_every_product(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        widest_statement: list[int],
    ) -> None:
        """The overview counts a shelf's products rather than listing them;
        the count still reaches every one of them."""
        body = _get(client, doc_auth_headers, '/api/v1/warehouse/putaway/occupancy')

        shelf = next(
            node
            for node in body['nodes']
            if node['location_id'] == str(doc_target_location.id)
        )
        assert shelf['cell']['products'] == _PAST_THE_LIMIT
        assert widest_statement[0] <= _PARAMETERS_A_STATEMENT_NEEDS

    def test_stock_as_of_today_names_and_values_every_product(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        widest_statement: list[int],
    ) -> None:
        """Today's stock is the valuation's question and the as-of report's:
        every product stands on its shelf, the report counts each of them,
        and the page it answers names its rows."""
        # The report answers an organization that has a history; one
        # record put on a shelf through the door writes its first movement.
        added = client.post(
            '/api/v1/items',
            headers=doc_auth_headers,
            json={
                'name': 'First movement',
                'quantity': '1',
                'location_id': str(doc_target_location.id),
            },
        )
        assert added.status_code == status.HTTP_201_CREATED, added.text
        widest_statement[0] = 0

        body = _get(
            client,
            doc_auth_headers,
            '/api/v1/stock-as-of',
            as_of=datetime.now(UTC).isoformat(),
            limit=200,
        )

        # Every bulk product, and the one the first movement put down.
        assert body['total'] == _PAST_THE_LIMIT + 1
        assert len(body['items']) == 200
        assert all(
            row['product_name'] and Decimal(row['quantity']) != 0
            for row in body['items']
        )
        assert widest_statement[0] <= _PARAMETERS_A_STATEMENT_NEEDS

    def test_the_product_list_and_its_record_card_answer(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        widest_statement: list[int],
    ) -> None:
        page = _get(client, doc_auth_headers, '/api/v1/items', limit=50)
        assert len(page['items']) == 50
        assert page['has_more'] is True

        first = page['items'][0]['id']
        card = _get(client, doc_auth_headers, f'/api/v1/items/{first}')
        assert card['id'] == first

        counts = _get(client, doc_auth_headers, '/api/v1/items/attention-counts')
        assert counts['expired'] == 0

        assert widest_statement[0] <= _PARAMETERS_A_STATEMENT_NEEDS

    def test_the_location_list_answers(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        widest_statement: list[int],
    ) -> None:
        page = _get(client, doc_auth_headers, '/api/v1/locations', limit=200)

        assert page['total'] > _PAST_THE_LIMIT
        assert widest_statement[0] <= _PARAMETERS_A_STATEMENT_NEEDS
