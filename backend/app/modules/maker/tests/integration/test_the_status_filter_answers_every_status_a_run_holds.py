"""Every status the runs list offers narrows the list to that status.

The list's In progress tab asks for ``status=IN_PROGRESS``; a filter that
accepts every other status but that one answers 422, and the screen a run
under way is read from says "Failed to load production orders". Each
status a run can hold is a filter, and each one answers only the runs
holding it.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import ProductionOrder
from app.modules.maker.tests.integration.test_a_run_opens_the_card_at_its_cost import (
    _template,
)

pytestmark = pytest.mark.integration

#: The statuses a run holds at some point in its life, one per tab the list
#: offers plus the undone one a reversal leaves.
STATUSES = ('DRAFT', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'REVERSED')


def _order(
    db: Session,
    org: Organization,
    output: ProductTemplate,
    location: StorageLocation,
    status: str,
) -> ProductionOrder:
    order = ProductionOrder(
        organization_id=org.id,
        output_template_id=output.id,
        planned_qty=Decimal('1'),
        output_storage_location_id=location.id,
        status=status,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


class TestTheStatusFilter:
    @pytest.mark.parametrize('status', STATUSES)
    def test_the_tab_of_a_status_answers_the_runs_holding_it(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
        status: str,
    ) -> None:
        output = _template(db_session, mk_org, 'Output for the status tabs')
        by_status = {
            held: _order(db_session, mk_org, output, mk_output_loc, held)
            for held in STATUSES
        }

        listed = client.get(
            '/api/v1/maker/production/orders',
            params={'status': status},
            headers=mk_auth_headers,
        )

        assert listed.status_code == 200, listed.text
        items = listed.json()['items']
        assert [item['id'] for item in items] == [str(by_status[status].id)]
        assert items[0]['status'] == status
