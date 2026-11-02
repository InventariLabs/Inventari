"""An edit cannot leave a record without a unit, and its answer is the saved row.

Both create doors answer "a quantity of what" for the caller — the matched
template's unit, else pieces — so a record without a unit is a state create
no longer produces. The edit door reproduced it with one field:
``{"uom_id": null}`` came back 200 and the column was empty. A record whose
unit was taken away is not "no unit", it is a quantity nobody can read, so
the edit refuses it with a sentence instead. A record that already has no
unit (older data) is not refused for saying so again: nothing is removed.

The same response also described the row before the write: the embedded
``uom`` object was the relationship loaded with the record, and a changed
``uom_id`` did not reload it, so the mutation answered ``uom_id: kg`` beside
``uom: {symbol: "pcs"}``. A client that trusts the mutation's answer — React
Query's cache does — showed a unit the record no longer had.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation


def _item(
    db_session: Session,
    org: Organization,
    location: StorageLocation,
    *,
    quantity: str,
    uom_id,
) -> Item:
    item = Item(
        name='Something countable',
        organization_id=org.id,
        storage_location_id=location.id,
        quantity=Decimal(quantity),
        uom_id=uom_id,
    )
    db_session.add(item)
    db_session.commit()
    return item


@pytest.mark.integration
class TestAnEditCannotTakeTheUnitAway:
    def test_clearing_the_unit_is_refused_with_a_sentence(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        pcs = ModuleTestHelper(db_session).get_uom('pcs')
        item = _item(
            db_session,
            test_household,
            test_storage_location,
            quantity='0',
            uom_id=pcs.id,
        )

        resp = client.put(
            f'/api/v1/items/{item.id}', headers=auth_headers, json={'uom_id': None}
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'pcs' in resp.text
        db_session.expire_all()
        db_session.refresh(item)
        assert item.uom_id == pcs.id

    def test_the_batch_refuses_it_too(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        pcs = ModuleTestHelper(db_session).get_uom('pcs')
        item = _item(
            db_session,
            test_household,
            test_storage_location,
            quantity='0',
            uom_id=pcs.id,
        )

        resp = client.patch(
            '/api/v1/items/bulk',
            headers=auth_headers,
            json={'item_ids': [str(item.id)], 'update_data': {'uom_id': None}},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        db_session.expire_all()
        db_session.refresh(item)
        assert item.uom_id == pcs.id

    def test_a_record_without_a_unit_can_still_be_edited(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        """A GET body sent back as the PUT names ``uom_id: null`` again.

        Nothing is taken away there, so the rest of the edit goes through.
        """
        item = _item(
            db_session, test_household, test_storage_location, quantity='0', uom_id=None
        )

        resp = client.put(
            f'/api/v1/items/{item.id}',
            headers=auth_headers,
            json={'name': 'Renamed', 'uom_id': None},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['name'] == 'Renamed'


@pytest.mark.integration
class TestTheEditAnswersWithTheSavedRow:
    def test_a_changed_unit_is_the_unit_in_the_answer(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        h = ModuleTestHelper(db_session)
        pcs, kg = h.get_uom('pcs'), h.get_uom('kg')
        item = _item(
            db_session,
            test_household,
            test_storage_location,
            quantity='0',
            uom_id=pcs.id,
        )

        resp = client.put(
            f'/api/v1/items/{item.id}',
            headers=auth_headers,
            json={'uom_id': str(kg.id)},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert body['uom_id'] == str(kg.id)
        assert body['uom']['id'] == str(kg.id)
        assert body['uom']['symbol'] == 'kg'
        fetched = client.get(f'/api/v1/items/{item.id}', headers=auth_headers).json()
        assert fetched['uom'] == body['uom']
