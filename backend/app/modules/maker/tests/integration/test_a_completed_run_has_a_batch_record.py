"""A completed run has a batch record, and keeps the photos and files filed under it.

The record is one page: formula and variant, planned and actual quantity,
every ingredient with the batches and quantities taken, costs, who and when,
notes and attachments. The batches are read from the movements the run
wrote, so the record says what the shelves gave. A run's photos and files
have the limits a product's attachments have, and each one filed or removed
is a journal entry on the run.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import put_on_shelf, run_in_async_session

pytestmark = pytest.mark.integration

ORDERS = '/api/v1/maker/production/orders'

#: The smallest PNG there is: an 8-byte signature and the chunks of a pixel.
_PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082'
)


@pytest.fixture
def run_id(
    client: TestClient,
    db_session: Session,
    mk_org: Organization,
    mk_user: User,
    mk_auth_headers: dict[str, str],
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    async_engine_fixture: AsyncEngine,
) -> str:
    """Two loaves of rye bread made from flour of batch F-07, recorded as made."""
    flour = ProductTemplate(
        organization_id=mk_org.id, name='Rye flour', sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    bread = ProductTemplate(
        organization_id=mk_org.id, name='Rye bread', sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db_session.add_all([flour, bread])
    db_session.flush()
    recipe = MakerRecipe(
        organization_id=mk_org.id,
        output_template_id=bread.id,
        name='Sourdough loaf',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.flush()
    db_session.add(
        BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=bread.id,
            child_template_id=flour.id,
            qty_per_batch=Decimal('0.5'),
            unit='pcs',
        )
    )
    lot = StockLot(
        organization_id=mk_org.id,
        product_template_id=flour.id,
        name='F-07',
        # Still in date whenever the suite runs: an expired batch is not drawn.
        expiry_date=date.today() + timedelta(days=100),
    )
    db_session.add(lot)
    db_session.commit()
    lot_id = lot.id

    async def _put(session: AsyncSession) -> None:
        await put_on_shelf(
            session,
            mk_user,
            flour,
            mk_input_loc.id,
            10,
            lot_id=lot_id,
            purchase_price='2',
        )

    run_in_async_session(async_engine_fixture, _put)
    made = client.post(
        f'{ORDERS}/made',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(bread.id),
            'planned_qty': '2',
            'output_location_id': str(mk_output_loc.id),
            'production_date': '2026-11-03',
            'notes': 'Proofed overnight',
        },
    )
    assert made.status_code == 201, made.text
    return str(made.json()['id'])


def test_the_record_names_each_ingredient_batch_and_who_made_it(
    client: TestClient, mk_auth_headers: dict[str, str], run_id: str
) -> None:
    # Fails without the change: there is no record endpoint.
    response = client.get(f'{ORDERS}/{run_id}/record', headers=mk_auth_headers)

    assert response.status_code == 200, response.text
    record = response.json()
    assert record['recipe_name'] == 'Sourdough loaf'
    assert record['output_template_name'] == 'Rye bread'
    assert record['output_lot_name'] == '20261103-1'
    assert record['production_date'] == '2026-11-03'
    assert Decimal(record['planned_qty']) == Decimal('2')
    assert Decimal(record['actual_qty']) == Decimal('2')
    assert record['notes'] == 'Proofed overnight'
    assert record['completed_by_name']
    [flour] = record['ingredients']
    assert flour['template_name'] == 'Rye flour'
    assert [(b['lot_name'], Decimal(b['quantity'])) for b in flour['batches']] == [
        ('F-07', Decimal('1'))
    ]
    assert Decimal(flour['cost']) == Decimal('2.00')
    assert Decimal(record['material_cost']) == Decimal('2.00')


def test_a_draft_has_no_record(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    run_id: str,
) -> None:
    copy = client.post(f'{ORDERS}/{run_id}/duplicate', headers=mk_auth_headers)

    response = client.get(
        f'{ORDERS}/{copy.json()["id"]}/record', headers=mk_auth_headers
    )

    assert response.status_code == 400, response.text


def test_a_photo_is_filed_under_the_run_and_journalled(
    client: TestClient,
    db_session: Session,
    mk_auth_headers: dict[str, str],
    run_id: str,
) -> None:
    # Fails without the change: a run takes no attachments.
    uploaded = client.post(
        f'{ORDERS}/{run_id}/attachments',
        headers=mk_auth_headers,
        files={'file': ('jars.png', io.BytesIO(_PNG), 'image/png')},
    )

    assert uploaded.status_code == 201, uploaded.text
    attachment = uploaded.json()
    listed = client.get(f'{ORDERS}/{run_id}/attachments', headers=mk_auth_headers)
    assert [a['original_name'] for a in listed.json()['items']] == ['jars.png']
    served = client.get(attachment['url'], headers=mk_auth_headers)
    assert served.status_code == 200, served.text
    record = client.get(f'{ORDERS}/{run_id}/record', headers=mk_auth_headers).json()
    assert [a['original_name'] for a in record['attachments']] == ['jars.png']

    removed = client.delete(
        f'{ORDERS}/{run_id}/attachments/{attachment["id"]}', headers=mk_auth_headers
    )

    assert removed.status_code == 204, removed.text
    entries = db_session.scalars(
        select(AuditLog).where(AuditLog.target_id == uuid.UUID(run_id))
    ).all()
    changes = [
        (e.snapshot['before']['attachment'], e.snapshot['after']['attachment'])
        for e in entries
        if e.snapshot
        and 'before' in e.snapshot
        and 'attachment' in e.snapshot['before']
    ]
    assert sorted(changes, key=str) == sorted(
        [(None, 'jars.png'), ('jars.png', None)], key=str
    )


def test_a_file_past_a_product_attachments_limits_is_refused(
    client: TestClient, mk_auth_headers: dict[str, str], run_id: str
) -> None:
    wrong_type = client.post(
        f'{ORDERS}/{run_id}/attachments',
        headers=mk_auth_headers,
        files={
            'file': ('run.exe', io.BytesIO(b'MZ\x90\x00'), 'application/x-msdownload')
        },
    )
    too_large = client.post(
        f'{ORDERS}/{run_id}/attachments',
        headers=mk_auth_headers,
        files={
            'file': (
                'huge.png',
                io.BytesIO(_PNG + b'\x00' * (10 * 1024 * 1024)),
                'image/png',
            )
        },
    )

    assert wrong_type.status_code == 415, wrong_type.text
    assert too_large.status_code == 413, too_large.text
