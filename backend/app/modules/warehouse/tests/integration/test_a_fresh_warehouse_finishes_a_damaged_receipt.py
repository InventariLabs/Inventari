"""A fresh warehouse organization finishes a receipt that carries damage.

The floor records what arrived — nine of ten, one of those damaged — through
a receiving session, and the document is closed when the session ends. It
used to be refused there: the document profile named no quarantine
location, so the receipt executor had nowhere to put the damaged unit, and
the answer arrived as a 400 on the last step, after every quantity was
already recorded. The person who met it could not clear it either — the
document settings open for an administrator only.

Onboarding now names the quarantine shelf the product profile seeds, so the
same receipt completes: the good part lands where the receipt was aimed and
the damaged unit stands on the shelf the profile names, held back from what
a picking may draw.

The test walks the flow rather than asserting the field, because the field
being set is not the promise — the receipt completing is.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.core.contracts import UserContextDTO
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.services.onboarding_service import apply_onboarding_profile_async
from tests.integration._shelf import run_in_async_session

#: The seed handle a profile declares its quarantine shelf under — spelled
#: out rather than imported, so this test collects and runs against the tree
#: it is meant to fail on.
QUARANTINE_SHELF_SEED_CODE = 'QUARANTINE'

pytestmark = pytest.mark.integration


async def _onboard_as_a_warehouse(
    session: AsyncSession, organization_id: UUID, user_id: UUID
) -> None:
    """Apply the equipment profile the way a fresh organization gets it.

    The organization arrives by id, not as an object: the fixture rows belong
    to the test's own session, and an instance already attached there cannot
    be added to this one.
    """
    org = await session.get(Organization, organization_id)
    assert org is not None
    await apply_onboarding_profile_async(
        session,
        org,
        'equipment_wms',
        user=UserContextDTO(id=user_id, organization_id=organization_id, role='admin'),
    )


def _the_quarantine_shelf(
    db_session: Session, organization_id: UUID
) -> StorageLocation:
    """The location the profile seeded under the quarantine handle."""
    rows = db_session.scalars(
        select(StorageLocation).where(
            StorageLocation.organization_id == organization_id
        )
    ).all()
    shelf = next(
        (
            row
            for row in rows
            if ((row.settings or {}).get('seed') or {}).get('code')
            == QUARANTINE_SHELF_SEED_CODE
        ),
        None,
    )
    assert shelf is not None, 'the profile seeded no quarantine shelf'
    return shelf


def _stock_at(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    location: StorageLocation,
) -> Decimal:
    resp = client.get(
        '/api/v1/stock-quants',
        headers=headers,
        params={
            'product_template_id': str(template.id),
            'location_id': str(location.id),
        },
    )
    assert resp.status_code == 200, resp.text
    return sum(
        (Decimal(item['quantity']) for item in resp.json()['items']),
        Decimal('0'),
    )


def _receive_with_a_damaged_unit(
    client: TestClient,
    headers: dict[str, str],
    target: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
) -> str:
    """Ten ordered, nine received, one of the nine damaged — through a session."""
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [
                {'product_template_id': str(template.id), 'expected_quantity': 10}
            ],
        },
    )
    assert created.status_code == 201, created.text
    doc_id: str = created.json()['id']
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text

    start = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
    )
    assert start.status_code == 201, start.text
    session_id = start.json()['id']
    line_id = start.json()['lines'][0]['id']

    recorded = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
        headers=headers,
        json={
            'line_id': line_id,
            'received_quantity': '9',
            'held_quantity': '1',
            'discrepancy_code': 'DAMAGE',
            'discrepancy_reason': 'One crushed box',
        },
    )
    assert recorded.status_code == 200, recorded.text
    return doc_id


def test_a_fresh_warehouse_receives_a_damaged_unit_and_completes(
    client: TestClient,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
    doc_user: User,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_template: ProductTemplate,
) -> None:
    """The measured first-use path, end to end.

    Before the shelf was named at onboarding, closing the document here
    answered 400 with ``receipt_needs_quarantine_location`` and the receipt
    stood at CONFIRMED — everything recorded, nothing finished, and a member
    who could only be told to open settings they may not open.
    """
    # The fixture rows have to be committed before another session reads them.
    db_session.commit()

    run_in_async_session(
        async_engine_fixture,
        lambda session: _onboard_as_a_warehouse(session, doc_org.id, doc_user.id),
    )
    db_session.expire_all()

    doc_id = _receive_with_a_damaged_unit(
        client,
        doc_auth_headers,
        doc_target_location,
        doc_partner,
        doc_template,
    )

    # The page closes the document when the session ends — the step that
    # used to answer 400 with ``receipt_needs_quarantine_location`` and leave
    # the receipt at CONFIRMED with every quantity already recorded.
    completed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()['status'] == 'COMPLETED'

    # What the refusal said was missing, written by the profile's own seed
    # rather than by hand: the shelf exists, and the document profile names
    # it the way the settings section shows it.
    shelf = _the_quarantine_shelf(db_session, doc_org.id)
    profile = client.get('/api/v1/warehouse/profile', headers=doc_auth_headers)
    assert profile.status_code == 200, profile.text
    assert profile.json()['quarantine_location_id'] == str(shelf.id)

    # Eight usable pieces where the receipt was aimed — the ninth is the one
    # held back — and that damaged unit on the shelf the profile names, out
    # of reach of what a picking may draw.
    assert _stock_at(
        client, doc_auth_headers, doc_template, doc_target_location
    ) == Decimal('8')
    assert _stock_at(client, doc_auth_headers, doc_template, shelf) == Decimal('1')


def test_a_shelf_somebody_named_stays(
    client: TestClient,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
    doc_user: User,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
) -> None:
    """The name onboarding writes is a default, not a verdict.

    An organization that already answered the question in its document
    settings keeps that answer when its profile is applied — the same rule
    every explicit profile entry follows. Only a profile that names no shelf
    gets the seeded one.
    """
    db_session.commit()
    chosen = client.put(
        '/api/v1/warehouse/profile',
        headers=doc_auth_headers,
        json={'quarantine_location_id': str(doc_target_location.id)},
    )
    assert chosen.status_code == 200, chosen.text

    run_in_async_session(
        async_engine_fixture,
        lambda session: _onboard_as_a_warehouse(session, doc_org.id, doc_user.id),
    )
    db_session.expire_all()

    profile = client.get('/api/v1/warehouse/profile', headers=doc_auth_headers)
    assert profile.status_code == 200, profile.text
    assert profile.json()['quarantine_location_id'] == str(doc_target_location.id)
