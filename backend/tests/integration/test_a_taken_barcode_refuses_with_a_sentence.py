"""A scanned code lands on the product; a taken one-off code refuses.

Two lives for one number, one column each: the code a scan reads is the
*product's* — it belongs to ``product_templates.barcode``, where receipts
write it and where a scan looks it up. The record's own column is for the
one-off nobody catalogued.

Creation used to copy a scanned code onto the record as well, so the
second record of the same product died on ``uq_items_org_barcode_active``
with a blind refusal — and the form has no code field to recover with.
Creation now lets the catalogue row carry the code and keeps the record
bare; the one-off that genuinely collides at the record level still gets
the clean, naming refusal.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import status
from sqlalchemy import select

pytestmark = pytest.mark.integration


def _barcode() -> str:
    return f'BRC-{uuid.uuid4().hex[:12]}'


def _create(client, auth_headers, storage_id, **overrides):
    payload = {
        'name': 'Barcode holder',
        'quantity': 1,
        'location_id': str(storage_id),
    }
    payload.update(overrides)
    return client.post('/api/v1/items', headers=auth_headers, json=payload)


def test_a_second_record_of_the_same_product_links_the_same_template(
    client, auth_headers, test_storage_location, db_session
):
    """The scan says "this code is this product" — the second record of
    that product is not a refusal, it is more stock of it."""
    from app.models.item import Item
    from app.models.product_template import ProductTemplate

    barcode = _barcode()
    first = _create(client, auth_headers, test_storage_location.id, barcode=barcode)
    assert first.status_code == status.HTTP_201_CREATED, first.text

    second = _create(
        client,
        auth_headers,
        test_storage_location.id,
        name='Second holder',
        barcode=barcode,
    )

    assert second.status_code == status.HTTP_201_CREATED, second.text

    # The code lives once, on the catalogue row both records share; the
    # records themselves stay bare.
    template = db_session.scalars(
        select(ProductTemplate).where(ProductTemplate.barcode == barcode)
    ).first()
    assert template is not None
    assert first.json()['template_id'] == str(template.id)
    assert second.json()['template_id'] == str(template.id)
    holders = db_session.scalars(select(Item).where(Item.barcode == barcode)).all()
    assert holders == []


def test_an_item_level_duplicate_still_refuses_with_the_sentence(
    client, auth_headers, test_storage_location, db_session
):
    """The record-level column survives for one-offs, and so does the rule
    that two live records cannot hold the same code: a create matched by
    name against a template with a *different* code keeps the scanned one
    on the record, and the next record claiming it is refused by name."""

    from app.models.item import Item

    template_code, one_off = _barcode(), _barcode()

    # The template exists with its own code; a create under that name
    # carrying a *different* code cannot backfill it, so the scanned one
    # stays at the record level (the one-off case).
    seeded = _create(
        client,
        auth_headers,
        test_storage_location.id,
        barcode=template_code,
    )
    assert seeded.status_code == status.HTTP_201_CREATED

    keeper = _create(
        client,
        auth_headers,
        test_storage_location.id,
        name='Barcode holder',
        barcode=one_off,
    )
    assert keeper.status_code == status.HTTP_201_CREATED, keeper.text

    second = _create(
        client,
        auth_headers,
        test_storage_location.id,
        barcode=one_off,
    )

    assert second.status_code == status.HTTP_400_BAD_REQUEST
    detail = second.json()['detail']
    message = detail['message'] if isinstance(detail, dict) else str(detail)
    assert f'Barcode already in use: {one_off}' in message
    holders = db_session.scalars(select(Item).where(Item.barcode == one_off)).all()
    assert [str(item.id) for item in holders] == [keeper.json()['id']]


def test_an_edit_refuses_with_the_same_sentence(
    client, auth_headers, test_storage_location
):
    """The update path and the create path run one check, so they speak
    one sentence — a caller refused on creation gets the same words as
    one refused on edit. The holder here carries a *record-level* code,
    the one-off case the column keeps."""
    # The holder got its code the one-off way: a template with a different
    # code existed under that name, so the scanned one stayed on the record.
    template_code, one_off = _barcode(), _barcode()
    seeded = _create(
        client,
        auth_headers,
        test_storage_location.id,
        barcode=template_code,
    )
    assert seeded.status_code == status.HTTP_201_CREATED
    holder = _create(
        client,
        auth_headers,
        test_storage_location.id,
        barcode=one_off,
    )
    assert holder.status_code == status.HTTP_201_CREATED, holder.text
    other = _create(client, auth_headers, test_storage_location.id)
    assert other.status_code == status.HTTP_201_CREATED, other.text

    edit = client.put(
        f'/api/v1/items/{other.json()["id"]}',
        json={'barcode': one_off},
        headers=auth_headers,
    )

    assert edit.status_code == status.HTTP_400_BAD_REQUEST
    detail = edit.json()['detail']
    message = detail['message'] if isinstance(detail, dict) else str(detail)
    assert f'Barcode already in use: {one_off}' in message


def _record_level_holder(client, auth_headers, storage_id) -> str:
    """A code worn by a *record*, not by the catalogue row.

    Creation routes a scanned code onto the product template whenever the
    name matches a template with no code of its own, so the record column —
    the one the unique index guards — is reached only the one-off way: a
    template with a *different* code under that name. Returns the code.
    """
    template_code, one_off = _barcode(), _barcode()
    seeded = _create(client, auth_headers, storage_id, barcode=template_code)
    assert seeded.status_code == status.HTTP_201_CREATED
    holder = _create(client, auth_headers, storage_id, barcode=one_off)
    assert holder.status_code == status.HTTP_201_CREATED, holder.text
    return one_off


def _message(response) -> str:
    detail = response.json()['detail']
    return detail['message'] if isinstance(detail, dict) else str(detail)


def test_the_bulk_edit_refuses_a_taken_code_with_the_same_sentence(
    client, auth_headers, test_storage_location
):
    """The fifth write path, the taken case. A batch of one record is the
    single edit's own shape, so it runs the single edit's check and answers
    with the sentence POST and PUT answer with. It used to skip the check,
    reach ``uq_items_org_barcode_active`` and hand back a raw 500."""
    taken = _record_level_holder(client, auth_headers, test_storage_location.id)
    other = _create(client, auth_headers, test_storage_location.id, name='Bulk target')
    assert other.status_code == status.HTTP_201_CREATED, other.text

    resp = client.patch(
        '/api/v1/items/bulk',
        headers=auth_headers,
        json={
            'item_ids': [other.json()['id']],
            'update_data': {'barcode': taken},
        },
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
    assert f'Barcode already in use: {taken}' in _message(resp)


def test_the_bulk_edit_refuses_to_share_one_code_between_records(
    client, auth_headers, test_storage_location, db_session
):
    """What one code on many records means: nothing the record column can
    hold. The request contradicts itself whatever the database holds — the
    unique index allows one live bearer — and the measured repro used a code
    no record wore yet and still died on the second record's flush. So the
    refusal names the contradiction and writes nothing."""
    from app.models.item import Item

    first = _create(client, auth_headers, test_storage_location.id, name='Bulk A')
    second = _create(client, auth_headers, test_storage_location.id, name='Bulk B')
    assert first.status_code == status.HTTP_201_CREATED, first.text
    assert second.status_code == status.HTTP_201_CREATED, second.text
    code = _barcode()

    resp = client.patch(
        '/api/v1/items/bulk',
        headers=auth_headers,
        json={
            'item_ids': [first.json()['id'], second.json()['id']],
            'update_data': {'barcode': code},
        },
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
    assert f'One barcode cannot name 2 records: {code}' in _message(resp)

    db_session.expire_all()
    holders = db_session.scalars(
        select(Item).where(Item.id.in_([first.json()['id'], second.json()['id']]))
    ).all()
    assert [item.barcode for item in holders] == [None, None]


def test_the_bulk_edit_still_sets_a_free_code_on_one_record(
    client, auth_headers, test_storage_location
):
    """The guard refuses contradictions, not the operation: a batch of one
    naming a code nothing wears goes through, as it always did."""
    target = _create(client, auth_headers, test_storage_location.id, name='Bulk one')
    assert target.status_code == status.HTTP_201_CREATED, target.text
    code = _barcode()

    resp = client.patch(
        '/api/v1/items/bulk',
        headers=auth_headers,
        json={
            'item_ids': [target.json()['id']],
            'update_data': {'barcode': code},
        },
    )

    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert resp.json()['updated'] == 1

    fetched = client.get(f'/api/v1/items/{target.json()["id"]}', headers=auth_headers)
    assert fetched.json()['barcode'] == code


def test_the_item_without_a_barcode_is_untouched(
    client, auth_headers, test_storage_location
):
    """The check exists for callers who name a barcode; the vast majority
    of creates pass none and must not pay a query for it."""
    response = _create(client, auth_headers, test_storage_location.id)

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()['barcode'] is None


def test_two_creates_racing_for_one_new_code_share_the_template(
    client, auth_headers, test_storage_location, db_session, monkeypatch
):
    """Both requests look before either writes; the loser joins the winner.

    The look is made to find nothing once, as it does for a request that ran
    before the other one committed — the card already stands when the write
    comes, and the unique code refuses it. That used to surface as a 500.
    """
    from app.models.product_template import ProductTemplate
    from app.services.items import _template

    barcode = _barcode()
    first = _create(client, auth_headers, test_storage_location.id, barcode=barcode)
    assert first.status_code == status.HTTP_201_CREATED, first.text

    real_find = _template.find_template_async
    looks = {'blind': 1}

    async def find_once_blind(*args, **kwargs):
        if looks['blind']:
            looks['blind'] -= 1
            return None
        return await real_find(*args, **kwargs)

    monkeypatch.setattr(_template, 'find_template_async', find_once_blind)

    second = _create(
        client,
        auth_headers,
        test_storage_location.id,
        name='Second holder',
        barcode=barcode,
    )

    assert second.status_code == status.HTTP_201_CREATED, second.text
    assert second.json()['template_id'] == first.json()['template_id']
    cards = db_session.scalars(
        select(ProductTemplate).where(ProductTemplate.barcode == barcode)
    ).all()
    assert len(cards) == 1
