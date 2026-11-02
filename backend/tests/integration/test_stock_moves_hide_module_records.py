"""The movement ledger hides what a vertical module owns, like the lists do.

The inventory overview's "Recent moves" listed a laptop's receipt although
the products list, the storage counts and the attention card all hide the
module's records. A move that names its record is judged by that record; any
other move carries only a product, so the question is asked of the product: a
ledger row is hidden when the product has records and every one of them
belongs to a module.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status

from app.models.category import Category
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from tests.integration._shelf import anchor_pending_records


def _product_with_a_record(db_session, org_id, storage_id, category, name):
    template = ProductTemplate(organization_id=org_id, name=name)
    db_session.add(template)
    db_session.flush()
    db_session.add(
        Item(
            name=name,
            organization_id=org_id,
            storage_location_id=storage_id,
            template_id=template.id,
            category_id=category.id if category else None,
            quantity=1,
        )
    )
    anchor_pending_records(db_session)
    db_session.add(
        StockMove(
            organization_id=org_id,
            product_template_id=template.id,
            from_location_id=None,
            to_location_id=storage_id,
            quantity=Decimal(1),
            state='done',
            reference_type='item',
            reference_id=uuid4(),
        )
    )
    db_session.commit()
    return template


@pytest.fixture
def ledger(db_session, test_household, test_storage_location):
    equipment = Category(
        name='IT Equipment',
        code='LEDGER_EQUIPMENT',
        context_tag='equipment',
        organization_id=test_household.id,
    )
    food = Category(
        name='Food',
        code='LEDGER_FOOD',
        context_tag=None,
        organization_id=test_household.id,
    )
    db_session.add_all([equipment, food])
    db_session.commit()
    args = (db_session, test_household.id, test_storage_location.id)
    return {
        'laptop': _product_with_a_record(*args, equipment, 'ThinkPad'),
        'milk': _product_with_a_record(*args, food, 'Milk'),
    }


def _names(client, auth_headers, **params):
    response = client.get('/api/v1/stock-moves', headers=auth_headers, params=params)
    assert response.status_code == status.HTTP_200_OK
    return response.json()['items'], response.json()['total']


@pytest.mark.integration
class TestStockMovesHideModuleRecords:
    def test_the_ledger_without_the_flag_shows_every_move(
        self, client, auth_headers, ledger
    ):
        rows, total = _names(client, auth_headers)
        assert {r['product_name'] for r in rows} == {'ThinkPad', 'Milk'}
        assert total == 2

    def test_the_flag_hides_the_move_of_a_module_record(
        self, client, auth_headers, ledger
    ):
        rows, total = _names(client, auth_headers, exclude_module_contexts='true')
        assert [r['product_name'] for r in rows] == ['Milk']
        assert total == 1

    def test_a_product_with_one_ordinary_record_stays_visible(
        self, client, auth_headers, db_session, test_household, ledger
    ):
        """The list shows a product as soon as one of its records is ordinary."""
        food = db_session.query(Category).filter_by(code='LEDGER_FOOD').one()
        laptop = ledger['laptop']
        record = db_session.query(Item).filter_by(template_id=laptop.id).one()
        db_session.add(
            Item(
                name='ThinkPad',
                organization_id=test_household.id,
                storage_location_id=record.storage_location_id,
                template_id=laptop.id,
                category_id=food.id,
                quantity=1,
            )
        )
        anchor_pending_records(db_session)
        db_session.commit()

        rows, _ = _names(client, auth_headers, exclude_module_contexts='true')
        assert {r['product_name'] for r in rows} == {'ThinkPad', 'Milk'}

    def test_the_export_takes_the_same_flag(self, client, auth_headers, ledger):
        response = client.get(
            '/api/v1/stock-moves/export/xlsx',
            headers=auth_headers,
            params={'exclude_module_contexts': 'true'},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_a_move_naming_a_module_record_is_hidden_beside_an_ordinary_one(
        self, client, auth_headers, db_session, test_household, ledger
    ):
        """A mixed product: the move follows the record it names."""
        food = db_session.query(Category).filter_by(code='LEDGER_FOOD').one()
        laptop = ledger['laptop']
        asset = db_session.query(Item).filter_by(template_id=laptop.id).one()
        ordinary = Item(
            name='ThinkPad',
            organization_id=test_household.id,
            storage_location_id=asset.storage_location_id,
            template_id=laptop.id,
            category_id=food.id,
            quantity=1,
        )
        db_session.add(ordinary)
        anchor_pending_records(db_session)
        db_session.flush()
        for record in (asset, ordinary):
            db_session.add(
                StockMove(
                    organization_id=test_household.id,
                    product_template_id=laptop.id,
                    from_location_id=None,
                    to_location_id=asset.storage_location_id,
                    quantity=Decimal(1),
                    state='done',
                    reference_type='item',
                    reference_id=record.id,
                )
            )
        db_session.commit()

        everything, _ = _names(client, auth_headers, product_template_id=str(laptop.id))
        hidden, _ = _names(
            client,
            auth_headers,
            product_template_id=str(laptop.id),
            exclude_module_contexts='true',
        )
        refs = {r['reference_id'] for r in hidden}
        assert str(asset.id) not in refs
        assert str(ordinary.id) in refs
        assert str(asset.id) in {r['reference_id'] for r in everything}
