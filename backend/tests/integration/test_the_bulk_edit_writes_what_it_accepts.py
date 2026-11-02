"""A batch edit writes every field it accepts, the way the single edit does.

``PATCH /items/bulk`` takes the whole of ``ItemUpdate`` and wrote it with
``setattr`` wherever ``hasattr`` said yes. Four fields of that schema are not
columns of the record, and the single edit routes each of them by name: the
low-stock threshold and the unit weight go to the product's card, a freeze
date into ``meta_data``, and the unit confirmation is spent on the unit
guard. The batch knew none of it. ``min_quantity`` is a read-only property,
so ``hasattr`` let it through to a setter that is not there and the request
ended in a 500; a freeze date was dropped at 200 while the history said it
had been set; a confirmed unit was refused, the flag lost on the way.

And the trace was built from the payload, not from what the record took: a
batch that changed nothing still wrote a history row and a journal row
whose two sides said the same thing.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditAction, AuditLog
from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.schemas._common import keyed_by_column
from app.schemas.item import _UNIT_CONFIRMATION_FIELD, ItemUpdate
from app.services.items._bulk_update import _AUDITED_LEGACY_DATES
from app.services.items._date_meta import LEGACY_DATE_FIELDS
from app.services.items._update import _AUDITED_TEMPLATE_FIELDS
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration

BULK_URL = '/api/v1/items/bulk'


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f"'{symbol}' is not in the seeded catalogue"
    return uom


def _carded_record(
    db: Session, org_id, location: StorageLocation, name: str, uom_id=None
) -> Item:
    """A record on a card of its own organization, holding nothing yet."""
    card = ProductTemplate(organization_id=org_id, name=name, uom_id=uom_id)
    db.add(card)
    db.flush()
    item = Item(
        name=name,
        organization_id=org_id,
        storage_location_id=location.id,
        template_id=card.id,
        quantity=Decimal('0'),
        uom_id=uom_id,
    )
    db.add(item)
    anchor_pending_records(db)
    db.commit()
    db.refresh(item)
    return item


def _bulk(client: TestClient, headers: dict[str, str], items: list[Item], update):
    return client.patch(
        BULK_URL,
        headers=headers,
        json={'item_ids': [str(i.id) for i in items], 'update_data': update},
    )


def _history(db: Session, item: Item) -> list[dict]:
    db.expire_all()
    rows = db.scalars(
        select(ItemHistory)
        .where(
            ItemHistory.item_id == item.id,
            ItemHistory.action == ItemAction.UPDATED,
        )
        .order_by(ItemHistory.created_at)
    ).all()
    return [row.changes or {} for row in rows]


def _journal(db: Session, item: Item) -> list[dict]:
    db.expire_all()
    rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.target_id == item.id,
            AuditLog.action == AuditAction.UPDATE,
        )
        .order_by(AuditLog.created_at)
    ).all()
    return [row.snapshot or {} for row in rows]


class TestTheBatchWritesWhatItAccepts:
    def test_a_threshold_and_a_unit_weight_land_on_each_records_card(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household,
        test_storage_location: StorageLocation,
    ) -> None:
        """Measured on dev: 500, ``property 'min_quantity' ... has no setter``."""
        first = _carded_record(
            db_session, test_household.id, test_storage_location, 'Rice'
        )
        second = _carded_record(
            db_session, test_household.id, test_storage_location, 'Lentils'
        )

        response = _bulk(
            client,
            auth_headers,
            [first, second],
            {'min_quantity': 3, 'weight_value': 250},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['updated'] == 2
        db_session.expire_all()
        for record in (first, second):
            card = db_session.get(ProductTemplate, record.template_id)
            assert card is not None
            assert card.min_quantity == 3
            assert card.weight_value == 250
        # And the trace says so, from the card's side, as the single edit's
        # journal does: the threshold is the product's, and it moved.
        entry = _journal(db_session, first)[-1]
        assert entry['before']['min_quantity'] == 0
        assert entry['after']['min_quantity'] == 3

    def test_a_freeze_date_is_kept_where_the_single_edit_keeps_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household,
        test_storage_location: StorageLocation,
    ) -> None:
        """Measured on dev: 200 and the record unchanged, the history saying
        it had been set."""
        frozen_on = date.today() - timedelta(days=2)
        by_batch = _carded_record(
            db_session, test_household.id, test_storage_location, 'Peas'
        )
        by_hand = _carded_record(
            db_session, test_household.id, test_storage_location, 'Beans'
        )

        batch = _bulk(
            client, auth_headers, [by_batch], {'freeze_date': frozen_on.isoformat()}
        )
        single = client.put(
            f'/api/v1/items/{by_hand.id}',
            headers=auth_headers,
            json={'freeze_date': frozen_on.isoformat()},
        )

        assert batch.status_code == status.HTTP_200_OK, batch.text
        assert single.status_code == status.HTTP_200_OK, single.text
        read = client.get(f'/api/v1/items/{by_batch.id}', headers=auth_headers)
        assert read.json()['freeze_date'] == frozen_on.isoformat()
        db_session.expire_all()
        assert (
            db_session.get(Item, by_batch.id).meta_data
            == db_session.get(Item, by_hand.id).meta_data
        )
        # Named as the reader knows the field, with the side it replaced.
        changes = _history(db_session, by_batch)[-1]
        assert changes['old'] == {'freeze_date': None}
        assert changes['new'] == {'freeze_date': frozen_on.isoformat()}
        entry = _journal(db_session, by_batch)[-1]
        assert entry['before'] == {'freeze_date': None}
        assert entry['after'] == {'freeze_date': frozen_on.isoformat()}

    def test_a_confirmed_unit_is_taken_as_the_single_edit_takes_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household,
        test_storage_location: StorageLocation,
    ) -> None:
        """Measured on dev: 400 — the confirmation never reached the guard.

        Taken, the choice is how the quantity was typed: the record keeps its
        card's kilograms, and the history names the grams that were chosen.
        """
        kg = _uom(db_session, 'kg')
        grams = _uom(db_session, 'g')
        record = _carded_record(
            db_session, test_household.id, test_storage_location, 'Rye flour', kg.id
        )

        refused = _bulk(client, auth_headers, [record], {'uom_id': str(grams.id)})
        confirmed = _bulk(
            client,
            auth_headers,
            [record],
            {'uom_id': str(grams.id), _UNIT_CONFIRMATION_FIELD: True},
        )

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        db_session.expire_all()
        assert db_session.get(Item, record.id).uom_id == kg.id
        choices = [row for row in _history(db_session, record) if 'template_uom' in row]
        assert [(row['template_uom'], row['chosen_uom']) for row in choices] == [
            ('kg', 'g')
        ]


class TestTheTraceNamesWhatTheRecordTook:
    def test_a_batch_that_changes_nothing_leaves_no_row(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household,
        test_storage_location: StorageLocation,
    ) -> None:
        """Measured on dev: one history row and one journal row, each side
        of which said ``Rice``."""
        record = _carded_record(
            db_session, test_household.id, test_storage_location, 'Rice'
        )

        response = _bulk(client, auth_headers, [record], {'name': 'Rice'})

        assert response.status_code == status.HTTP_200_OK, response.text
        assert _history(db_session, record) == []
        assert _journal(db_session, record) == []

    def test_only_the_field_that_moved_is_named(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household,
        test_storage_location: StorageLocation,
    ) -> None:
        """The same name posted beside a new brand is not a change of name."""
        record = _carded_record(
            db_session, test_household.id, test_storage_location, 'Rice'
        )

        response = _bulk(
            client, auth_headers, [record], {'name': 'Rice', 'brand': 'Acme'}
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        [changes] = _history(db_session, record)
        assert changes['old'] == {'brand': None}
        assert changes['new'] == {'brand': 'Acme'}
        assert changes['bulk'] is True
        [entry] = _journal(db_session, record)
        assert entry['before'] == {'brand': None}
        assert entry['after'] == {'brand': 'Acme'}


def test_every_field_the_batch_accepts_has_a_way_onto_the_record() -> None:
    """The class, not the three places: a field added to ``ItemUpdate`` is
    either a column the record takes or one the update routes by name.

    A field that is neither is the shape found here three times — the schema
    says the batch accepts it, and nothing in the batch can write it.
    """
    columns = set(Item.__table__.columns.keys())
    routed = (
        set(_AUDITED_TEMPLATE_FIELDS)
        | set(LEGACY_DATE_FIELDS)
        | {_UNIT_CONFIRMATION_FIELD, 'metadata'}
    )

    # A field is written under its column's name (``keyed_by_column``):
    # ``location_id`` lands on ``storage_location_id``.
    accepted = set(keyed_by_column(dict.fromkeys(ItemUpdate.model_fields)))
    stranded = sorted(accepted - columns - routed)

    assert stranded == []


def test_the_journal_declares_every_date_it_names() -> None:
    """The batch names a date it keeps in ``meta_data`` by its API word, and
    the snapshot-key exporter learns that word from a literal tuple — so the
    tuple has to keep up with the dates there are, or the journal shows a
    raw key no catalogue was asked to translate."""
    assert set(_AUDITED_LEGACY_DATES) == set(LEGACY_DATE_FIELDS)
