"""A file added to a product or taken off it is an act the journal records.

The upload and the delete wrote a row and a stored object and left the
organization's journal without a line. The entry rides the attachment's own
commit, so it is there exactly when the file is.
"""

import pytest
from fastapi import status

from app.models.audit_log import AuditLog

_PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'

pytestmark = pytest.mark.integration


def _entries(db_session, test_user, test_item) -> list[AuditLog]:
    return (
        db_session.query(AuditLog)
        .filter(
            AuditLog.organization_id == test_user.organization_id,
            AuditLog.target_type == 'item',
            AuditLog.target_id == test_item.id,
            AuditLog.action == 'UPDATE',
        )
        .order_by(AuditLog.created_at)
        .all()
    )


def _upload(client, item_id, headers):
    return client.post(
        f'/api/v1/items/{item_id}/attachments',
        files={'file': ('manual.pdf', _PDF, 'application/pdf')},
        headers=headers,
    )


def test_an_upload_names_the_file_and_who_added_it(
    client, auth_headers, db_session, test_user, test_item
):
    response = _upload(client, test_item.id, auth_headers)
    assert response.status_code == status.HTTP_201_CREATED, response.text

    (entry,) = _entries(db_session, test_user, test_item)
    assert entry.user_id == test_user.id
    assert entry.snapshot['name'] == test_item.name
    assert entry.snapshot['before'] == {'attachment': None}
    assert entry.snapshot['after'] == {'attachment': 'manual.pdf'}


def test_a_delete_names_the_file_that_went(
    client, auth_headers, db_session, test_user, test_item
):
    created = _upload(client, test_item.id, auth_headers).json()

    response = client.delete(
        f'/api/v1/attachments/{created["id"]}', headers=auth_headers
    )
    assert response.status_code == status.HTTP_200_OK, response.text

    removal = _entries(db_session, test_user, test_item)[-1]
    assert removal.user_id == test_user.id
    assert removal.snapshot['before'] == {'attachment': 'manual.pdf'}
    assert removal.snapshot['after'] == {'attachment': None}
