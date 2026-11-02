"""Item attachments live where every other upload lives: in file storage.

The writer used to open an upload directory of its own while ``/uploads/``
served through ``FileStorageService``. On the local backend the two happen to
be one directory in the container, so nothing showed; on S3 the upload
reported success, the object never reached the bucket, and the download was a
404. The provider below stands in for any non-local backend: it keeps objects
in memory, behind the same ``StorageProvider`` interface S3 implements, so a
write that bypasses the abstraction cannot reach it.
"""

from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import status

from app.core.file_storage.providers.base import FileInfo, StorageProvider
from app.core.file_storage.service import FileStorageService


class InMemoryStorage(StorageProvider):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def save(self, file_path, file_content, content_type='') -> FileInfo:
        data = file_content.getvalue()
        self.objects[file_path] = data
        return FileInfo(
            path=file_path,
            size=len(data),
            created_at=datetime.now(UTC),
            content_type=content_type,
        )

    async def get(self, file_path) -> BytesIO:
        if file_path not in self.objects:
            raise FileNotFoundError(file_path)
        return BytesIO(self.objects[file_path])

    async def delete(self, file_path) -> None:
        if file_path not in self.objects:
            raise FileNotFoundError(file_path)
        del self.objects[file_path]

    async def exists(self, file_path) -> bool:
        return file_path in self.objects

    async def get_url(self, file_path, expires_in_seconds=None) -> str:
        return f'mem://{file_path}'


@pytest.fixture
def bucket():
    service = FileStorageService()
    previous = service._provider
    memory = InMemoryStorage()
    service._provider = memory
    yield memory
    service._provider = previous


_PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


def _upload(client, item_id, headers):
    return client.post(
        f'/api/v1/items/{item_id}/attachments',
        files={'file': ('manual.pdf', _PDF, 'application/pdf')},
        headers=headers,
    )


@pytest.mark.integration
class TestAttachmentsGoThroughStorage:
    def test_the_upload_lands_in_storage_under_the_organization_and_is_served(
        self, client, auth_headers, test_item, test_user, bucket
    ):
        response = _upload(client, test_item.id, auth_headers)

        assert response.status_code == status.HTTP_201_CREATED, response.text
        path = response.json()['file_path']
        assert path.startswith(f'{test_user.organization_id}/attachments/')
        assert bucket.objects[path] == _PDF

        served = client.get(f'/uploads/{path}', headers=auth_headers)
        assert served.status_code == status.HTTP_200_OK
        assert served.content == _PDF

        listed = client.get(
            f'/api/v1/items/{test_item.id}/attachments', headers=auth_headers
        )
        assert listed.status_code == status.HTTP_200_OK
        assert [a['file_path'] for a in listed.json()['items']] == [path]

    def test_deleting_the_attachment_removes_the_stored_object(
        self, client, auth_headers, test_item, bucket
    ):
        created = _upload(client, test_item.id, auth_headers).json()
        path = created['file_path']
        assert path in bucket.objects

        deleted = client.delete(
            f'/api/v1/attachments/{created["id"]}', headers=auth_headers
        )

        assert deleted.status_code == status.HTTP_200_OK
        assert path not in bucket.objects
        listed = client.get(
            f'/api/v1/items/{test_item.id}/attachments', headers=auth_headers
        ).json()['items']
        assert listed == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheResolverReadsTheOrganizationSegment:
    async def test_a_path_under_another_organization_is_not_resolved(self, monkeypatch):
        """The row lookup is org-filtered too; the prefix is refused first,
        so a row that somehow matched could still not be served across."""
        from app.core.public_api import core_api
        from app.core.uploads.resolvers import AttachmentResolver

        mine, theirs, item = uuid4(), uuid4(), uuid4()
        looked_up: list[str] = []

        async def find(db, file_path, organization_id=None):
            looked_up.append(file_path)

            class Row:
                file_type = 'application/pdf'
                file_name = 'manual.pdf'

            return Row()

        monkeypatch.setattr(core_api.attachments, 'find_by_file_path_async', find)
        resolver = AttachmentResolver()

        assert (
            await resolver.resolve(None, f'{theirs}/attachments/{item}/a.pdf', mine)
            is None
        )
        # The shape written before storage scoping carries no organization.
        assert await resolver.resolve(None, f'attachments/{item}/a.pdf', mine) is None
        assert looked_up == []

        own = await resolver.resolve(None, f'{mine}/attachments/{item}/a.pdf', mine)
        assert own is not None
        assert own.display_name == 'manual.pdf'
