"""The order stock leaves in is the product's, and a reader can set it.

Stock leaves FIFO unless the product's ``removal_strategy`` says FEFO, and
nothing a reader could reach wrote that column: no schema carried it, so FEFO
held only for whoever edited the database. The product-level fields of the
item payload (the threshold, the unit weight) are written to the product
(ADR-015); the strategy travels the same way. A category can name the
strategy its new products start with, so a reader who files every perishable
under one category does not have to set each product by hand.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models.product_template import ProductTemplate

pytestmark = pytest.mark.integration

ITEM_URL = '/api/v1/items'
CATEGORY_URL = '/api/v1/categories'


def _create_item(client, auth_headers, storage_id, name: str, **extra) -> dict:
    response = client.post(
        ITEM_URL,
        headers=auth_headers,
        json={'name': name, 'location_id': str(storage_id), **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _strategy_of(db: Session, template_id: str) -> str | None:
    db.expire_all()
    template = db.get(ProductTemplate, template_id)
    assert template is not None
    return template.removal_strategy


def test_an_edit_sets_the_products_removal_strategy_and_the_product_reads_it(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    item = _create_item(client, auth_headers, test_storage_location.id, 'Yoghurt')

    response = client.put(
        f'{ITEM_URL}/{item["id"]}',
        headers=auth_headers,
        json={'removal_strategy': 'FEFO'},
    )

    assert response.status_code == 200, response.text
    assert _strategy_of(db_session, item['template_id']) == 'FEFO'
    assert response.json()['template']['removal_strategy'] == 'FEFO'
    product = client.get(
        f'{ITEM_URL}/product-templates/{item["template_id"]}', headers=auth_headers
    )
    assert product.status_code == 200, product.text
    assert product.json()['removal_strategy'] == 'FEFO'


def test_an_edit_can_put_a_product_back_on_fifo(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    item = _create_item(
        client,
        auth_headers,
        test_storage_location.id,
        'Cream',
        removal_strategy='FEFO',
    )
    assert _strategy_of(db_session, item['template_id']) == 'FEFO'

    response = client.put(
        f'{ITEM_URL}/{item["id"]}',
        headers=auth_headers,
        json={'removal_strategy': 'FIFO'},
    )

    assert response.status_code == 200, response.text
    assert _strategy_of(db_session, item['template_id']) == 'FIFO'


def test_a_strategy_the_engine_does_not_know_is_refused(
    client, auth_headers, test_storage_location
) -> None:
    item = _create_item(client, auth_headers, test_storage_location.id, 'Milk')

    response = client.put(
        f'{ITEM_URL}/{item["id"]}',
        headers=auth_headers,
        json={'removal_strategy': 'LIFO'},
    )

    assert response.status_code in (400, 422), response.text


def test_a_new_product_starts_with_its_categorys_strategy(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    category = client.post(
        CATEGORY_URL,
        headers=auth_headers,
        json={'name': 'Chilled', 'default_removal_strategy': 'FEFO'},
    )
    assert category.status_code == 201, category.text
    assert category.json()['default_removal_strategy'] == 'FEFO'

    item = _create_item(
        client,
        auth_headers,
        test_storage_location.id,
        'Kefir',
        category_id=category.json()['id'],
    )

    assert _strategy_of(db_session, item['template_id']) == 'FEFO'


def test_a_strategy_named_on_the_new_product_wins_over_the_category(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    category = client.post(
        CATEGORY_URL,
        headers=auth_headers,
        json={'name': 'Chilled', 'default_removal_strategy': 'FEFO'},
    )
    assert category.status_code == 201, category.text

    item = _create_item(
        client,
        auth_headers,
        test_storage_location.id,
        'Butter',
        category_id=category.json()['id'],
        removal_strategy='FIFO',
    )

    assert _strategy_of(db_session, item['template_id']) == 'FIFO'


def test_the_category_default_leaves_an_existing_product_as_it_is(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    first = _create_item(client, auth_headers, test_storage_location.id, 'Cheese')
    category = client.post(
        CATEGORY_URL,
        headers=auth_headers,
        json={'name': 'Chilled', 'default_removal_strategy': 'FEFO'},
    )
    assert category.status_code == 201, category.text

    second = _create_item(
        client,
        auth_headers,
        test_storage_location.id,
        'Cheese',
        category_id=category.json()['id'],
    )

    assert second['template_id'] == first['template_id']
    assert _strategy_of(db_session, first['template_id']) is None


def test_a_category_edit_sets_and_clears_the_default(
    client, auth_headers, test_storage_location
) -> None:
    category = client.post(CATEGORY_URL, headers=auth_headers, json={'name': 'Dry'})
    assert category.status_code == 201, category.text
    assert category.json()['default_removal_strategy'] is None
    url = f'{CATEGORY_URL}/{category.json()["id"]}'

    set_ = client.put(
        url, headers=auth_headers, json={'default_removal_strategy': 'FEFO'}
    )
    assert set_.status_code == 200, set_.text
    assert set_.json()['default_removal_strategy'] == 'FEFO'

    cleared = client.put(
        url, headers=auth_headers, json={'default_removal_strategy': None}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()['default_removal_strategy'] is None


def _shared_product(db: Session, name: str) -> ProductTemplate:
    """A catalogue product: no organization owns it, every one reads it."""
    template = ProductTemplate(organization_id=None, name=name)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def test_a_shared_products_strategy_is_refused_rather_than_dropped(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    # The product is every organization's, so this one cannot reorder its
    # stock for all of them. The edit used to answer 200 and leave FIFO in
    # place: the form said "Updated" and the dispatch kept drawing FIFO.
    shared = _shared_product(db_session, 'Shared yoghurt')
    item = _create_item(
        client,
        auth_headers,
        test_storage_location.id,
        'Shared yoghurt',
        template_id=str(shared.id),
    )
    assert item['template_id'] == str(shared.id)

    response = client.put(
        f'{ITEM_URL}/{item["id"]}',
        headers=auth_headers,
        json={'removal_strategy': 'FEFO'},
    )

    assert response.status_code == 400, response.text
    assert _strategy_of(db_session, str(shared.id)) is None


def test_a_shared_products_unchanged_strategy_does_not_stop_the_edit(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    # The form posts its whole state; the strategy the product already reads
    # (unset is FIFO) is not a change, and the rest of the edit goes through.
    shared = _shared_product(db_session, 'Shared rice')
    item = _create_item(
        client,
        auth_headers,
        test_storage_location.id,
        'Shared rice',
        template_id=str(shared.id),
    )

    response = client.put(
        f'{ITEM_URL}/{item["id"]}',
        headers=auth_headers,
        json={'removal_strategy': 'FIFO', 'name': 'Shared rice, top shelf'},
    )

    assert response.status_code == 200, response.text
    assert response.json()['name'] == 'Shared rice, top shelf'
    assert _strategy_of(db_session, str(shared.id)) is None


def test_a_new_record_on_a_shared_product_cannot_reorder_its_stock(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    # The create door wrote the strategy to the organization's own card only
    # and dropped it for a shared one, answering 201 as if it had taken.
    shared = _shared_product(db_session, 'Shared milk')

    refused = client.post(
        ITEM_URL,
        headers=auth_headers,
        json={
            'name': 'Shared milk',
            'location_id': str(test_storage_location.id),
            'template_id': str(shared.id),
            'removal_strategy': 'FEFO',
        },
    )
    assert refused.status_code == 400, refused.text
    assert _strategy_of(db_session, str(shared.id)) is None

    accepted = _create_item(
        client,
        auth_headers,
        test_storage_location.id,
        'Shared milk',
        template_id=str(shared.id),
        removal_strategy='FIFO',
    )
    assert accepted['template_id'] == str(shared.id)
