"""An attachment is deleted only through the asset it is filed under.

The delete route named an asset in its path but looked the attachment up by
its own id and the organization alone. Any asset id — another asset's, or one
that does not exist — deleted the attachment and its stored file, so a caller
that paired an attachment with the wrong asset removed a document from an
asset it never meant to touch.
"""

import uuid

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation


@pytest.mark.integration
def test_a_foreign_or_unknown_asset_cannot_delete_the_attachment(
    client: TestClient,
    db_session: Session,
    eq_auth_headers: dict[str, str],
    eq_item: Item,
    eq_org: Organization,
    eq_storage_location: StorageLocation,
    eq_category: Category,
) -> None:
    other_asset = Item(
        name='Dell Latitude',
        organization_id=eq_org.id,
        storage_location_id=eq_storage_location.id,
        category_id=eq_category.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    db_session.add(other_asset)
    db_session.commit()

    upload = client.post(
        f'/api/v1/equipment/{eq_item.id}/attachments',
        headers=eq_auth_headers,
        files={'file': ('invoice.pdf', b'%PDF-1.4 test', 'application/pdf')},
        data={'file_type': 'INVOICE'},
    )
    assert upload.status_code == status.HTTP_201_CREATED, upload.text
    attachment = upload.json()

    for wrong_asset_id in (other_asset.id, uuid.uuid4()):
        refused = client.delete(
            f'/api/v1/equipment/{wrong_asset_id}/attachments/{attachment["id"]}',
            headers=eq_auth_headers,
        )
        assert refused.status_code == status.HTTP_404_NOT_FOUND, refused.text

    # The list leaves out a row whose stored file is gone, so the attachment
    # still listed under its asset means both the row and the file survived.
    listed = client.get(
        f'/api/v1/equipment/{eq_item.id}/attachments', headers=eq_auth_headers
    )
    assert [a['id'] for a in listed.json()['items']] == [attachment['id']]

    deleted = client.delete(
        f'/api/v1/equipment/{eq_item.id}/attachments/{attachment["id"]}',
        headers=eq_auth_headers,
    )
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    listed = client.get(
        f'/api/v1/equipment/{eq_item.id}/attachments', headers=eq_auth_headers
    )
    assert listed.json()['items'] == []
