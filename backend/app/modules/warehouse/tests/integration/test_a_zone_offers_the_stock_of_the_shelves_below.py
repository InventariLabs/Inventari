"""A location named as a document's source is offered with the shelves below it.

A zone or a warehouse is a location with locations under it. The product
search used to read a location as exact, so a dispatch naming the warehouse
was offered nothing, and an order spread over three shelves could not be one
document. Now a zone searches the subtree and every hit names the shelf it
stands on; a shelf stays exact, because its own records are all it holds.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User


def _shelf(
    db_session: Session,
    org: Organization,
    user: User,
    parent: StorageLocation,
    name: str,
) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=org.id,
        name=name,
        parent_id=parent.id,
        storage_type_id=parent.storage_type_id,
        created_by=user.id,
    )
    db_session.add(shelf)
    db_session.flush()
    return shelf


@pytest.mark.integration
class TestAZoneOffersTheStockOfTheShelvesBelow:
    def test_a_zone_offers_the_stock_of_every_shelf_below_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_source_location: StorageLocation,
    ) -> None:
        """Each hit names its own shelf, so the reader can tell the rows apart."""
        first = _shelf(db_session, doc_org, doc_user, doc_source_location, 'Bin A1')
        second = _shelf(db_session, doc_org, doc_user, doc_source_location, 'Bin B2')
        here = Item(
            name='Washer pack',
            organization_id=doc_org.id,
            storage_location_id=first.id,
            quantity=Decimal('12'),
        )
        there = Item(
            name='Washer pack',
            organization_id=doc_org.id,
            storage_location_id=second.id,
            quantity=Decimal('5'),
        )
        db_session.add_all([here, there])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'washer', 'location_id': str(doc_source_location.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert {row['item_id'] for row in data} == {str(here.id), str(there.id)}
        assert {row['location_name'] for row in data} == {'Bin A1', 'Bin B2'}

    def test_a_shelf_offers_only_its_own_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_source_location: StorageLocation,
    ) -> None:
        """A leaf is exact: the stock of a sibling shelf is not on it."""
        first = _shelf(db_session, doc_org, doc_user, doc_source_location, 'Bin A1')
        second = _shelf(db_session, doc_org, doc_user, doc_source_location, 'Bin B2')
        here = Item(
            name='Washer pack',
            organization_id=doc_org.id,
            storage_location_id=first.id,
            quantity=Decimal('12'),
        )
        there = Item(
            name='Washer pack',
            organization_id=doc_org.id,
            storage_location_id=second.id,
            quantity=Decimal('5'),
        )
        db_session.add_all([here, there])
        db_session.commit()

        response = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': 'washer', 'location_id': str(first.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        assert [row['item_id'] for row in response.json()] == [str(here.id)]
