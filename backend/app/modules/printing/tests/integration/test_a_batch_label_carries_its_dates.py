"""A batch's label: the product, the batch code in bars, made and best-before.

A run of fifty jars prints fifty labels, one per jar, so a batch label goes
up to two hundred copies where any other label stops at twenty. The code in
bars is the batch's own name — what a scan at the next step looks the batch
up by — read back off the PNG, not taken from the function that chose it.
"""

from datetime import date
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.user import User
from app.modules.printing.models import PrintJob
from app.modules.printing.schemas import PROTOCOL_VERSION
from app.modules.printing.services.product_label_service import barcode_modules
from app.modules.printing.tests.bars import read_bars

pytestmark = pytest.mark.integration

_BASE = '/api/v1/printing'


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Jam Kitchen', ['core', 'items', 'locations', 'printing'])


@pytest.fixture
def headers(h: ModuleTestHelper, org: Organization) -> dict[str, str]:
    user: User = h.create_user(org, email='jars@example.com')
    return h.get_auth_headers(user)


@pytest.fixture
def batch(db_session: Session, org: Organization) -> StockLot:
    jam = ProductTemplate(organization_id=org.id, name='Plum jam')
    db_session.add(jam)
    db_session.flush()
    lot = StockLot(
        organization_id=org.id,
        product_template_id=jam.id,
        name='20261102-1',
        production_date=date(2026, 11, 2),
        expiry_date=date(2027, 5, 1),
    )
    db_session.add(lot)
    db_session.commit()
    return lot


def _register_printer(client: TestClient, headers: dict[str, str]) -> None:
    agent = client.post(
        f'{_BASE}/agent/register',
        headers=headers,
        json={
            'name': 'kitchen',
            'printer_type': 'brother-p710bt',
            'agent_version': '1.0.0',
            'protocol_version': PROTOCOL_VERSION,
        },
    )
    assert agent.status_code == status.HTTP_200_OK, agent.text


def test_the_label_carries_the_batch_code_in_bars(
    client: TestClient, headers: dict[str, str], batch: StockLot
) -> None:
    # Fails without the change: there is no batch label (404).
    resp = client.post(
        f'{_BASE}/lot-labels/png', headers=headers, json={'lot_ids': [str(batch.id)]}
    )

    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert read_bars(resp.content) == barcode_modules('20261102-1')


def test_a_queued_batch_label_says_when_it_was_made_and_until_when_it_keeps(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    batch: StockLot,
) -> None:
    _register_printer(client, headers)

    queued = client.post(
        f'{_BASE}/jobs',
        headers=headers,
        json={'lot_ids': [str(batch.id)], 'copies': 50},
    )

    assert queued.status_code == status.HTTP_201_CREATED, queued.text
    assert queued.json()['count'] == 50
    stored = db_session.scalar(
        select(PrintJob).where(PrintJob.id == queued.json()['id'])
    )
    assert stored is not None
    label: dict[str, Any] = stored.labels[0]
    assert (label['name'], label['short_code']) == ('Plum jam', '20261102-1')
    assert label['details'] == 'Made Nov 2, 2026\nBest before May 1, 2027'


def test_other_labels_still_stop_at_twenty_copies(
    client: TestClient, headers: dict[str, str], batch: StockLot
) -> None:
    _register_printer(client, headers)

    too_many = client.post(
        f'{_BASE}/jobs',
        headers=headers,
        json={'short_codes': ['STM-AAAA'], 'copies': 21},
    )
    batch_too_many = client.post(
        f'{_BASE}/lot-labels/png',
        headers=headers,
        json={'lot_ids': [str(batch.id)], 'copies': 201},
    )

    assert too_many.status_code == status.HTTP_400_BAD_REQUEST, too_many.text
    assert too_many.json()['detail']['code'] == 'PRINT_JOB_TOO_MANY_COPIES'
    assert batch_too_many.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_another_organizations_batch_does_not_print(
    client: TestClient,
    h: ModuleTestHelper,
    db_session: Session,
    batch: StockLot,
) -> None:
    other = h.create_org('Elsewhere', ['core', 'items', 'locations', 'printing'])
    stranger = h.get_auth_headers(h.create_user(other, email='stranger@example.com'))

    resp = client.post(
        f'{_BASE}/lot-labels/png', headers=stranger, json={'lot_ids': [str(batch.id)]}
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
