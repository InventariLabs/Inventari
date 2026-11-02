"""Changing a record's unit does not silently relabel its quantity.

``uom_id`` was applied like any other field: "5 pcs" became "5 kg" with no
conversion, no refusal and no trace — the history logged a pair of UUIDs
with no symbols beside them, so after the fact nobody could see what had
happened. Odoo refuses the same edit whenever the product has stock or
movements, for the same reason: the number on the shelf did not change, so
the unit under it must not either.

The precision check had a second hole. It only ran when the same request
also carried a quantity, so a unit whose rounding forbids fractions could be
set under a fractional quantity as long as the two arrived separately.

And a third: the rule was written into the single update and the batch went
past it. Fifty records selected on the list reached the same ``setattr``
with no refusal at all, so the edit the app blocks one at a time it accepted
fifty at a time. The tests below run the same three requests down the batch
route and expect the same three answers.
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
from app.models.user import User


@pytest.mark.integration
class TestAUnitCannotBeSwappedUnderTheStock:
    def test_changing_the_unit_of_stocked_goods_is_refused(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        h = ModuleTestHelper(db_session)
        pcs = h.get_uom('pcs')
        kg = h.get_uom('kg')
        item = Item(
            name='Five of something',
            organization_id=test_household.id,
            storage_location_id=test_storage_location.id,
            quantity=Decimal('5'),
            uom_id=pcs.id,
        )
        db_session.add(item)
        db_session.commit()

        resp = client.put(
            f'/api/v1/items/{item.id}',
            headers=auth_headers,
            json={'uom_id': str(kg.id)},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'pcs' in resp.text and 'kg' in resp.text

        db_session.expire_all()
        db_session.refresh(item)
        assert item.uom_id == pcs.id

    def test_an_empty_record_can_still_change_its_unit(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        """Nothing on the shelf, nothing to relabel."""
        h = ModuleTestHelper(db_session)
        pcs = h.get_uom('pcs')
        kg = h.get_uom('kg')
        item = Item(
            name='Nothing yet',
            organization_id=test_household.id,
            storage_location_id=test_storage_location.id,
            quantity=Decimal('0'),
            uom_id=pcs.id,
        )
        db_session.add(item)
        db_session.commit()

        resp = client.put(
            f'/api/v1/items/{item.id}',
            headers=auth_headers,
            json={'uom_id': str(kg.id)},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.expire_all()
        db_session.refresh(item)
        assert item.uom_id == kg.id

    def test_precision_is_checked_against_the_new_unit_alone(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        """A whole-number unit under a fractional quantity must be refused.

        The record holds 2.5, and the request names only the unit — which is
        precisely the request the old check sat out.
        """
        h = ModuleTestHelper(db_session)
        kg = h.get_uom('kg')
        pcs = h.get_uom('pcs')
        item = Item(
            name='Two and a half',
            organization_id=test_household.id,
            storage_location_id=test_storage_location.id,
            quantity=Decimal('2.5'),
            uom_id=kg.id,
        )
        db_session.add(item)
        db_session.commit()

        resp = client.put(
            f'/api/v1/items/{item.id}',
            headers=auth_headers,
            json={'uom_id': str(pcs.id)},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

        db_session.expire_all()
        db_session.refresh(item)
        assert item.uom_id == kg.id


@pytest.mark.integration
class TestTheBatchAnswersLikeTheSingleEdit:
    """`PATCH /items/bulk` reaches the same fields, so it obeys the same rules."""

    def _bulk(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        item_ids: list[str],
        update: dict[str, object],
    ):
        return client.patch(
            '/api/v1/items/bulk',
            headers=auth_headers,
            json={'item_ids': item_ids, 'update_data': update},
        )

    def _item(
        self,
        db_session: Session,
        org: Organization,
        location: StorageLocation,
        *,
        name: str,
        quantity: str,
        uom_id,
    ) -> Item:
        item = Item(
            name=name,
            organization_id=org.id,
            storage_location_id=location.id,
            quantity=Decimal(quantity),
            uom_id=uom_id,
        )
        db_session.add(item)
        db_session.commit()
        return item

    def test_changing_the_unit_of_stocked_goods_is_refused(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        h = ModuleTestHelper(db_session)
        pcs, kg = h.get_uom('pcs'), h.get_uom('kg')
        item = self._item(
            db_session,
            test_household,
            test_storage_location,
            name='Five of something',
            quantity='5',
            uom_id=pcs.id,
        )

        resp = self._bulk(client, auth_headers, [str(item.id)], {'uom_id': str(kg.id)})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'pcs' in resp.text and 'kg' in resp.text
        db_session.expire_all()
        db_session.refresh(item)
        assert item.uom_id == pcs.id

    def test_an_empty_record_can_still_change_its_unit(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        h = ModuleTestHelper(db_session)
        pcs, kg = h.get_uom('pcs'), h.get_uom('kg')
        item = self._item(
            db_session,
            test_household,
            test_storage_location,
            name='Nothing yet',
            quantity='0',
            uom_id=pcs.id,
        )

        resp = self._bulk(client, auth_headers, [str(item.id)], {'uom_id': str(kg.id)})

        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.expire_all()
        db_session.refresh(item)
        assert item.uom_id == kg.id

    def test_precision_is_checked_against_the_new_unit_alone(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        h = ModuleTestHelper(db_session)
        kg, pcs = h.get_uom('kg'), h.get_uom('pcs')
        item = self._item(
            db_session,
            test_household,
            test_storage_location,
            name='Two and a half',
            quantity='2.5',
            uom_id=kg.id,
        )

        resp = self._bulk(client, auth_headers, [str(item.id)], {'uom_id': str(pcs.id)})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        db_session.expire_all()
        db_session.refresh(item)
        assert item.uom_id == kg.id

    def test_one_stocked_record_refuses_the_whole_batch(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        """The unit is one value for every record the request names.

        Either it suits all of them or the request is incoherent, so the
        refusal comes before anything is written — an empty record selected
        beside a stocked one is left as it was rather than half-relabelled.
        """
        h = ModuleTestHelper(db_session)
        pcs, kg = h.get_uom('pcs'), h.get_uom('kg')
        empty = self._item(
            db_session,
            test_household,
            test_storage_location,
            name='Empty',
            quantity='0',
            uom_id=pcs.id,
        )
        stocked = self._item(
            db_session,
            test_household,
            test_storage_location,
            name='Stocked',
            quantity='3',
            uom_id=pcs.id,
        )

        resp = self._bulk(
            client,
            auth_headers,
            [str(empty.id), str(stocked.id)],
            {'uom_id': str(kg.id)},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        db_session.expire_all()
        db_session.refresh(empty)
        db_session.refresh(stocked)
        assert empty.uom_id == pcs.id
        assert stocked.uom_id == pcs.id
