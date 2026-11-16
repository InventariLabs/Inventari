"""A made product's label and its batch's label carry its ingredient list.

The list and the allergens come from the product's formula (the maker
module); the label prints them under the name, never smaller than the
letter the food regulation allows, and refuses a label too small to hold
them rather than printing them unreadable or cut short.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.maker.models import (
    BoMLine,
    MakerLabelFacts,
    MakerRecipe,
    ProductionOrder,
    ProductionPortion,
)
from app.modules.printing.models import PrintJob
from app.modules.printing.schemas import PROTOCOL_VERSION
from app.modules.printing.services.product_label_service import barcode_modules
from app.modules.printing.tests.bars import read_bars

pytestmark = pytest.mark.integration

_BASE = '/api/v1/printing'
_LIST = 'Ingredients: Plums, SUGAR. May contain: nuts.'


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Jam Kitchen', ['core', 'items', 'locations', 'printing', 'maker']
    )


@pytest.fixture
def user(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='jam@example.com')


@pytest.fixture
def headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


def _grams(db: Session) -> Uom:
    gram = db.scalars(select(Uom).where(Uom.symbol == 'g')).first()
    assert gram is not None
    return gram


def _made(
    db: Session, org: Organization, name: str, ingredients: list[tuple[str, str]]
) -> ProductTemplate:
    """A product made of (ingredient name, grams) by its default formula."""
    product = ProductTemplate(
        organization_id=org.id, name=name, sku=f'JAM-{uuid.uuid4().hex[:6]}'
    )
    db.add(product)
    db.flush()
    _formula(db, org, product, ingredients, default=True)
    db.add(
        MakerLabelFacts(
            organization_id=org.id, product_template_id=product.id, may_contain=['nuts']
        )
    )
    db.commit()
    return product


def _formula(
    db: Session,
    org: Organization,
    product: ProductTemplate,
    ingredients: list[tuple[str, str]],
    *,
    default: bool = False,
) -> MakerRecipe:
    """One more formula of *product*, of (ingredient name, grams)."""
    gram = _grams(db)
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=product.id,
        name='Batch' if default else 'Batch with honey',
        batch_yield_qty=Decimal('1000'),
        batch_yield_uom_id=gram.id,
        is_default=default,
    )
    db.add(recipe)
    db.flush()
    for ingredient_name, grams in ingredients:
        ingredient = ProductTemplate(
            organization_id=org.id, name=ingredient_name, uom_id=gram.id
        )
        db.add(ingredient)
        db.flush()
        db.add(
            BoMLine(
                organization_id=org.id,
                recipe_id=recipe.id,
                parent_template_id=product.id,
                child_template_id=ingredient.id,
                qty_per_batch=Decimal(grams),
                uom_id=gram.id,
                unit='g',
            )
        )
        if ingredient_name == 'Sugar':
            db.add(
                MakerLabelFacts(
                    organization_id=org.id,
                    product_template_id=ingredient.id,
                    # Not an allergen in law: here only to be emphasised.
                    allergens=['sulphites'],
                )
            )
    db.flush()
    return recipe


@pytest.fixture
def jam(db_session: Session, org: Organization) -> ProductTemplate:
    return _made(db_session, org, 'Plum jam', [('Plums', '700'), ('Sugar', '300')])


@pytest.fixture
def batch(db_session: Session, org: Organization, jam: ProductTemplate) -> StockLot:
    lot = StockLot(
        organization_id=org.id,
        product_template_id=jam.id,
        name='20251116-1',
        production_date=date(2025, 11, 16),
        expiry_date=date(2026, 5, 16),
    )
    db_session.add(lot)
    db_session.commit()
    return lot


@pytest.fixture
def shelf(h: ModuleTestHelper, org: Organization, user: User) -> StorageLocation:
    kind = h.create_storage_type('Shelf', 'SHELF', organization_id=org.id)
    return h.create_storage_location(org, kind, user, name='Shelf A')


@pytest.fixture
def jar(
    client: TestClient,
    headers: dict[str, str],
    jam: ProductTemplate,
    shelf: StorageLocation,
) -> str:
    resp = client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': 'Plum jam',
            'template_id': str(jam.id),
            'location_id': str(shelf.id),
            'quantity': 1,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


def _register_printer(client: TestClient, headers: dict[str, str]) -> None:
    agent = client.post(
        f'{_BASE}/agent/register',
        headers=headers,
        json={
            'name': 'kitchen',
            'printer_type': 'cups',
            'agent_version': '1.0.0',
            'protocol_version': PROTOCOL_VERSION,
        },
    )
    assert agent.status_code == status.HTTP_200_OK, agent.text


def _queued_composition(
    client: TestClient, db: Session, headers: dict[str, str], **target: list[str]
) -> str | None:
    """The ingredient list a print job stores for its one label."""
    queued = client.post(
        f'{_BASE}/jobs',
        headers=headers,
        json={**target, 'composition': True, 'width_mm': 62, 'height_mm': 40},
    )
    assert queued.status_code == status.HTTP_201_CREATED, queued.text
    stored = db.scalar(select(PrintJob).where(PrintJob.id == queued.json()['id']))
    assert stored is not None
    return cast('str | None', stored.labels[0]['composition'])


def _run(
    db: Session,
    org: Organization,
    shelf: StorageLocation,
    recipe: MakerRecipe,
    lot: StockLot | None = None,
) -> ProductionOrder:
    """A finished run of *recipe* whose output went into *lot*."""
    order = ProductionOrder(
        organization_id=org.id,
        output_template_id=recipe.output_template_id,
        recipe_id=recipe.id,
        planned_qty=Decimal('1'),
        actual_qty=Decimal('1'),
        output_storage_location_id=shelf.id,
        status='COMPLETED',
        output_lot_id=lot.id if lot is not None else None,
    )
    db.add(order)
    db.flush()
    return order


def _lot_png(
    client: TestClient, headers: dict[str, str], lot: StockLot, **options: Any
) -> Any:
    return client.post(
        f'{_BASE}/lot-labels/png',
        headers=headers,
        json={'lot_ids': [str(lot.id)], **options},
    )


def test_a_batch_label_prints_the_list_under_the_name(
    client: TestClient, headers: dict[str, str], batch: StockLot
) -> None:
    plain = _lot_png(client, headers, batch, width_mm=62, height_mm=40)
    listed = _lot_png(
        client, headers, batch, width_mm=62, height_mm=40, composition=True
    )

    assert plain.status_code == status.HTTP_200_OK, plain.text
    assert listed.status_code == status.HTTP_200_OK, listed.text
    # Fails without the change: the header is not sent.
    assert plain.headers['X-Labels-With-Composition'] == '1'
    assert listed.content != plain.content
    assert read_bars(listed.content) == barcode_modules('20251116-1')


def test_a_queued_batch_label_keeps_the_list(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    batch: StockLot,
) -> None:
    _register_printer(client, headers)

    queued = client.post(
        f'{_BASE}/jobs',
        headers=headers,
        json={
            'lot_ids': [str(batch.id)],
            'composition': True,
            'width_mm': 62,
            'height_mm': 40,
        },
    )

    assert queued.status_code == status.HTTP_201_CREATED, queued.text
    stored = db_session.scalar(
        select(PrintJob).where(PrintJob.id == queued.json()['id'])
    )
    assert stored is not None
    label: dict[str, Any] = stored.labels[0]
    assert label['composition'] == _LIST
    assert label['details'] == 'Made Nov 16, 2025\nBest before May 16, 2026'


def test_the_made_products_own_label_prints_the_list(
    client: TestClient, db_session: Session, headers: dict[str, str], jar: str
) -> None:
    resp = client.post(
        f'{_BASE}/product-labels/png',
        headers=headers,
        json={'item_ids': [jar], 'composition': True, 'width_mm': 62, 'height_mm': 40},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert resp.headers['X-Labels-With-Composition'] == '1'

    _register_printer(client, headers)
    queued = client.post(
        f'{_BASE}/jobs',
        headers=headers,
        json={'item_ids': [jar], 'composition': True, 'width_mm': 62, 'height_mm': 40},
    )
    assert queued.status_code == status.HTTP_201_CREATED, queued.text
    stored = db_session.scalar(
        select(PrintJob).where(PrintJob.id == queued.json()['id'])
    )
    assert stored is not None
    assert stored.labels[0]['composition'] == _LIST


def test_a_list_that_does_not_fit_the_label_is_refused(
    client: TestClient,
    db_session: Session,
    org: Organization,
    headers: dict[str, str],
) -> None:
    long = _made(
        db_session,
        org,
        'Festive fruit cake',
        [(f'Candied fruit number {n} in syrup', str(100 - n)) for n in range(20)],
    )
    lot = StockLot(organization_id=org.id, product_template_id=long.id, name='FC-1')
    db_session.add(lot)
    db_session.commit()

    small = _lot_png(client, headers, lot, composition=True)
    large = _lot_png(
        client, headers, lot, composition=True, width_mm=100, height_mm=100
    )

    assert small.status_code == status.HTTP_400_BAD_REQUEST, small.text
    assert small.json()['detail']['code'] == 'PRODUCT_LABEL_COMPOSITION_DOES_NOT_FIT'
    assert '50 × 24 mm' in small.json()['detail']['message']
    assert large.status_code == status.HTTP_200_OK, large.text


def test_without_production_a_label_carries_no_list(
    client: TestClient,
    db_session: Session,
    org: Organization,
    headers: dict[str, str],
    batch: StockLot,
) -> None:
    org.enabled_modules = [m for m in org.enabled_modules or [] if m != 'maker']
    db_session.commit()

    resp = _lot_png(client, headers, batch, composition=True)

    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert resp.headers['X-Labels-With-Composition'] == '0'


def test_a_batch_is_labelled_from_the_formula_its_run_used(
    client: TestClient,
    db_session: Session,
    org: Organization,
    headers: dict[str, str],
    jam: ProductTemplate,
    batch: StockLot,
    shelf: StorageLocation,
    jar: str,
) -> None:
    """Not from the product's default: a product has several formulas."""
    honey = _formula(db_session, org, jam, [('Plums', '600'), ('Honey', '400')])
    _run(db_session, org, shelf, honey, batch)
    record = db_session.get(Item, uuid.UUID(jar))
    assert record is not None
    record.lot_id = batch.id
    db_session.commit()
    _register_printer(client, headers)

    batch_label = _queued_composition(
        client, db_session, headers, lot_ids=[str(batch.id)]
    )
    record_label = _queued_composition(client, db_session, headers, item_ids=[jar])

    # Fails without the change: both print the default formula's sugar.
    assert batch_label == 'Ingredients: Plums, Honey. May contain: nuts.'
    assert record_label == batch_label


def test_a_batch_two_formulas_filled_carries_no_list(
    client: TestClient,
    db_session: Session,
    org: Organization,
    headers: dict[str, str],
    jam: ProductTemplate,
    batch: StockLot,
    shelf: StorageLocation,
) -> None:
    """Neither list is the batch's: it holds what both put in."""
    default = db_session.scalar(
        select(MakerRecipe).where(
            MakerRecipe.output_template_id == jam.id, MakerRecipe.is_default
        )
    )
    assert default is not None
    honey = _formula(db_session, org, jam, [('Plums', '600'), ('Honey', '400')])
    _run(db_session, org, shelf, default, batch)
    # The second run put a portion into the same batch by its name.
    portioned = _run(db_session, org, shelf, honey)
    db_session.add(
        ProductionPortion(
            organization_id=org.id,
            production_order_id=portioned.id,
            qty=Decimal('1'),
            made_on=date(2025, 11, 16),
            lot_name=batch.name,
        )
    )
    db_session.commit()

    resp = _lot_png(client, headers, batch, width_mm=62, height_mm=40, composition=True)

    assert resp.status_code == status.HTTP_200_OK, resp.text
    # Fails without the change: the default formula's list is counted.
    assert resp.headers['X-Labels-With-Composition'] == '0'
