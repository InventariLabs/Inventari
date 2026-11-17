"""A production run is not a purchase of the product it made.

Purchase patterns read the records created in the window as purchases, so
two runs of a wine showed "Wine" as a product bought twice at the run's
cost, though nobody bought it. A record a run opened says so in its
history, and the report leaves it out; what was really bought stays.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import post_on_shelf

from .test_role_guards import _template

pytestmark = pytest.mark.integration


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Wine Cellar',
        ['core', 'items', 'locations', 'categories', 'warehouse', 'maker', 'stats'],
    )


@pytest.fixture
def user(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='vintner@example.com')


@pytest.fixture
def headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


@pytest.fixture
def cellar(h: ModuleTestHelper, org: Organization, user: User) -> StorageLocation:
    return h.create_storage_location(
        org, h.create_storage_type('Cellar', 'CELLAR'), user, name='Cellar'
    )


def test_two_runs_of_a_wine_are_not_two_purchases_of_it(
    client: TestClient,
    org: Organization,
    headers: dict[str, str],
    cellar: StorageLocation,
    db_session: Session,
) -> None:
    grapes = _template(db_session, org, name='Grapes')
    wine = _template(db_session, org, name='Wine')
    recipe = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={
            'output_template_id': str(wine.id),
            'name': 'Wine',
            'batch_yield_qty': '1',
            'is_default': True,
        },
    )
    assert recipe.status_code == 201, recipe.text
    line = client.post(
        f'/api/v1/maker/recipes/{recipe.json()["id"]}/bom-lines',
        headers=headers,
        json={'child_template_id': str(grapes.id), 'qty_per_batch': '3', 'unit': 'kg'},
    )
    assert line.status_code == 201, line.text
    for _ in range(2):
        post_on_shelf(client, headers, grapes, cellar.id, '12', purchase_price='2.50')
    for _ in range(2):
        made = client.post(
            '/api/v1/maker/production/orders/made',
            headers=headers,
            json={
                'output_template_id': str(wine.id),
                'planned_qty': '2',
                'output_location_id': str(cellar.id),
            },
        )
        assert made.status_code == 201, made.text

    patterns = client.get('/api/v1/stats/purchase-patterns', headers=headers)

    assert patterns.status_code == 200, patterns.text
    names = {row['name']: row for row in patterns.json()['top_recurring_products']}
    assert 'Wine' not in names
    assert names['Grapes']['total_purchases_last_6_months'] == 2
