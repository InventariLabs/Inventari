"""
Unit tests for attachment_service — validation logic.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundException
from app.modules.equipment import attachment_service
from app.modules.equipment.attachment_service import (
    ATTACHMENT_POLICY,
    MAX_FILE_SIZE,
    VALID_FILE_TYPES,
    delete_attachment,
    discard_stored_file,
    list_attachments,
    upload_attachment,
)

from ._mocked_asset_read import asset_read_through


@pytest.fixture(autouse=True)
def _asset_read_through_the_mock() -> Iterator[None]:
    with asset_read_through(attachment_service, lambda: attachment_service.core_api):
        yield


@pytest.fixture(autouse=True)
def journal() -> Any:
    """The journal entry has its own integration tests; here core_api is a mock."""
    with patch(
        'app.modules.equipment.attachment_service._journal_attachment',
        new_callable=AsyncMock,
    ) as mocked:
        yield mocked


def _attachment_row(file_path: str) -> MagicMock:
    """A stored row with every field the response schema validates."""
    row = MagicMock()
    row.id = uuid4()
    row.item_id = uuid4()
    row.file_path = file_path
    row.original_name = 'warranty.pdf'
    row.file_type = 'WARRANTY'
    row.content_type = 'application/pdf'
    row.size_bytes = 12
    row.uploaded_by = uuid4()
    row.created_at = datetime.now(UTC)
    return row


@pytest.mark.unit
class TestAttachmentConstants:
    def test_allowed_content_types_includes_pdf(self) -> None:
        assert 'application/pdf' in ATTACHMENT_POLICY.content_types

    def test_allowed_content_types_includes_images(self) -> None:
        assert 'image/jpeg' in ATTACHMENT_POLICY.content_types
        assert 'image/png' in ATTACHMENT_POLICY.content_types

    def test_max_file_size_is_20mb(self) -> None:
        assert MAX_FILE_SIZE == 20 * 1024 * 1024

    def test_valid_file_types(self) -> None:
        assert 'INVOICE' in VALID_FILE_TYPES
        assert 'WARRANTY' in VALID_FILE_TYPES
        assert 'PHOTO' in VALID_FILE_TYPES
        assert 'MANUAL' in VALID_FILE_TYPES
        assert 'OTHER' in VALID_FILE_TYPES


@pytest.mark.unit
class TestUploadAttachment:
    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_upload_item_not_found(self, mock_core: Any) -> None:
        mock_core.items.get_async = AsyncMock(return_value=None)
        db = AsyncMock()
        with pytest.raises(NotFoundException):
            await upload_attachment(
                db,
                uuid4(),
                uuid4(),
                uuid4(),
                b'content',
                'test.pdf',
                'application/pdf',
                'PHOTO',
            )

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_upload_invalid_content_type(self, mock_core: Any) -> None:
        mock_core.items.get_async = AsyncMock(return_value=MagicMock())
        db = AsyncMock()
        with pytest.raises(ValueError, match='Unsupported file type'):
            await upload_attachment(
                db,
                uuid4(),
                uuid4(),
                uuid4(),
                b'content',
                'test.exe',
                'application/x-msdownload',
                'PHOTO',
            )

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_upload_file_too_large(self, mock_core: Any) -> None:
        mock_core.items.get_async = AsyncMock(return_value=MagicMock())
        db = AsyncMock()
        big_content = b'x' * (MAX_FILE_SIZE + 1)
        with pytest.raises(ValueError, match='File too large'):
            await upload_attachment(
                db,
                uuid4(),
                uuid4(),
                uuid4(),
                big_content,
                'big.pdf',
                'application/pdf',
                'INVOICE',
            )

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_upload_invalid_file_type(self, mock_core: Any) -> None:
        mock_core.items.get_async = AsyncMock(return_value=MagicMock())
        db = AsyncMock()
        with pytest.raises(ValueError, match='Invalid file type'):
            await upload_attachment(
                db,
                uuid4(),
                uuid4(),
                uuid4(),
                b'content',
                'test.pdf',
                'application/pdf',
                'INVALID_TYPE',
            )

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_upload_success(self, mock_core: Any) -> None:
        mock_core.items.get_async = AsyncMock(return_value=MagicMock())
        mock_core.file_storage.save_for_org_async = AsyncMock()
        db = AsyncMock()
        db.add = MagicMock()  # Session.add() is synchronous
        now = datetime.now(UTC)

        def _refresh(obj: Any) -> None:
            obj.id = uuid4()
            obj.created_at = now

        db.refresh = AsyncMock(side_effect=_refresh)
        result = await upload_attachment(
            db,
            uuid4(),
            uuid4(),
            uuid4(),
            # Magic bytes are validated, so the fixture must look like a PDF.
            b'%PDF-1.4 fake body',
            'test.pdf',
            'application/pdf',
            'INVOICE',
        )
        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert result.original_name == 'test.pdf'


@pytest.mark.unit
class TestListAttachments:
    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_list_item_not_found(self, mock_core: Any) -> None:
        mock_core.items.get_any_async = AsyncMock(return_value=None)
        db = AsyncMock()
        with pytest.raises(NotFoundException):
            await list_attachments(db, uuid4(), uuid4())

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_list_success_empty(self, mock_core: Any) -> None:
        mock_core.items.get_any_async = AsyncMock(return_value=MagicMock())
        mock_core.file_storage.exists_for_org_async = AsyncMock(return_value=True)
        db = AsyncMock()
        db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        result = await list_attachments(db, uuid4(), uuid4())
        assert result == []

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_list_skips_a_row_storage_cannot_resolve(
        self, mock_core: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One legacy row must not turn the whole list into a 500.

        A row written before the org-scoped move carries
        ``equipment/<item_id>/<file>``, which the scoped read resolves under
        an ``<org>/equipment/`` prefix that never existed — for this reader
        the file is gone. The endpoint answers the rows it can serve and
        names the skipped one in the log; review measured the alternative as
        a 500 for every attachment on the item.
        """
        mock_core.items.get_any_async = AsyncMock(return_value=MagicMock())
        orphan_path = f'equipment/{uuid4()}/{uuid4().hex}.pdf'
        orphan = _attachment_row(orphan_path)
        healthy = _attachment_row(f'{uuid4()}/{uuid4().hex}.pdf')
        mock_core.file_storage.exists_for_org_async = AsyncMock(
            side_effect=[False, True]
        )
        db = AsyncMock()
        db.scalars = AsyncMock(
            return_value=MagicMock(all=MagicMock(return_value=[orphan, healthy]))
        )

        with caplog.at_level(logging.WARNING):
            result = await list_attachments(db, uuid4(), uuid4())

        assert [r.id for r in result] == [healthy.id]
        assert any(orphan_path in record.getMessage() for record in caplog.records)


@pytest.mark.unit
class TestTheAddressIsTheAppsOwnRoute:
    """An attachment is linked through ``/uploads/<key>``, never the backend.

    On S3 the backend's address is a bare bucket URL: it skips the ownership
    check of the upload route and goes stale when the files move. The storage
    facade is asked to save and to say whether a file is there, never for an
    address.
    """

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_an_upload_answers_the_upload_route(self, mock_core: Any) -> None:
        mock_core.items.get_async = AsyncMock(return_value=MagicMock())
        mock_core.file_storage.save_for_org_async = AsyncMock()
        mock_core.file_storage.get_url_for_org_async = AsyncMock(
            return_value='https://bucket.s3.eu-west-1.amazonaws.com/x'
        )
        db = AsyncMock()
        db.add = MagicMock()

        def _refresh(obj: Any) -> None:
            obj.id = uuid4()
            obj.created_at = datetime.now(UTC)

        db.refresh = AsyncMock(side_effect=_refresh)
        org_id, item_id = uuid4(), uuid4()

        result = await upload_attachment(
            db,
            org_id,
            item_id,
            uuid4(),
            b'%PDF-1.4 fake body',
            'test.pdf',
            'application/pdf',
            'INVOICE',
        )

        stored = mock_core.file_storage.save_for_org_async.call_args.args[2]
        assert result.url == f'/uploads/{org_id}/equipment/{stored}'
        assert stored.startswith(f'{item_id}/')
        mock_core.file_storage.get_url_for_org_async.assert_not_called()

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_a_listed_attachment_answers_the_upload_route(
        self, mock_core: Any
    ) -> None:
        mock_core.items.get_any_async = AsyncMock(return_value=MagicMock())
        mock_core.file_storage.exists_for_org_async = AsyncMock(return_value=True)
        mock_core.file_storage.get_url_for_org_async = AsyncMock(
            return_value='https://bucket.s3.eu-west-1.amazonaws.com/x'
        )
        row = _attachment_row(f'{uuid4()}/{uuid4().hex}.pdf')
        db = AsyncMock()
        db.scalars = AsyncMock(
            return_value=MagicMock(all=MagicMock(return_value=[row]))
        )
        org_id = uuid4()

        result = await list_attachments(db, org_id, uuid4())

        assert [r.url for r in result] == [
            f'/uploads/{org_id}/equipment/{row.file_path}'
        ]
        mock_core.file_storage.get_url_for_org_async.assert_not_called()


@pytest.mark.unit
class TestDeleteAttachment:
    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_delete_not_found(self, mock_core: Any) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        with pytest.raises(NotFoundException):
            await delete_attachment(db, uuid4(), uuid4(), uuid4(), uuid4())

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_delete_drops_the_row_and_leaves_the_file_to_the_caller(
        self, mock_core: Any, journal: AsyncMock
    ) -> None:
        item_id = uuid4()
        attachment = MagicMock()
        attachment.file_path = 'a/b.pdf'
        attachment.item_id = item_id
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=attachment)
            )
        )
        mock_core.file_storage.delete_for_org_async = AsyncMock()
        mock_core.items.get_any_async = AsyncMock(return_value=None)
        path = await delete_attachment(db, uuid4(), item_id, uuid4(), uuid4())
        assert path == 'a/b.pdf'
        journal.assert_awaited_once()
        db.delete.assert_awaited_once_with(attachment)
        db.flush.assert_awaited_once()
        mock_core.file_storage.delete_for_org_async.assert_not_awaited()

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_discard_storage_failure_graceful(self, mock_core: Any) -> None:
        mock_core.file_storage.delete_for_org_async = AsyncMock(
            side_effect=OSError('disk error')
        )
        await discard_stored_file(uuid4(), 'a/b.pdf')
        mock_core.file_storage.delete_for_org_async.assert_awaited_once()


@pytest.mark.asyncio
class TestUploadSignatureValidation:
    """Content_type is client-supplied, so the bytes decide."""

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_upload_rejects_content_that_is_not_the_declared_type(
        self, mock_core: Any
    ) -> None:
        from app.core.upload_validation import FileSignatureMismatchError

        mock_core.items.get_async = AsyncMock(return_value=MagicMock())
        mock_core.file_storage.save_for_org_async = AsyncMock()
        db = AsyncMock()

        # A rejected upload, not a transport concern: the shared policy
        # raises a ValueError subclass, which `map_service_errors` turns
        # into the same 400 the router answered before.
        with pytest.raises(FileSignatureMismatchError):
            await upload_attachment(
                db,
                uuid4(),
                uuid4(),
                uuid4(),
                b'MZ\x90\x00 this is a PE binary',
                'invoice.pdf',
                'application/pdf',
                'INVOICE',
            )

        mock_core.file_storage.save_for_org_async.assert_not_awaited()

    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_stored_extension_ignores_the_uploaded_filename(
        self, mock_core: Any
    ) -> None:
        mock_core.items.get_async = AsyncMock(return_value=MagicMock())
        mock_core.file_storage.save_for_org_async = AsyncMock()
        db = AsyncMock()
        db.add = MagicMock()

        def _refresh(obj: Any) -> None:
            obj.id = uuid4()
            obj.created_at = datetime.now(UTC)

        db.refresh = AsyncMock(side_effect=_refresh)

        await upload_attachment(
            db,
            uuid4(),
            uuid4(),
            uuid4(),
            b'%PDF-1.4 body',
            '../../evil.sh',
            'application/pdf',
            'INVOICE',
        )

        stored_path = mock_core.file_storage.save_for_org_async.await_args[0][2]
        assert stored_path.endswith('.pdf')
        assert '..' not in stored_path


#: A genuine sample per allowed content type. The point of the table is that
#: the test below walks the policy's own type list, so adding a type to the
#: allowlist without a matching signature fails here instead of in production.
_SAMPLE_BYTES = {
    'application/pdf': b'%PDF-1.4 body',
    'image/jpeg': b'\xff\xd8\xff\xe0 body',
    'image/png': b'\x89PNG\r\n\x1a\n body',
    'image/gif': b'GIF89a body',
    'image/webp': b'RIFF\x00\x00\x00\x00WEBP body',
    'application/vnd.ms-excel': b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 body',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': (
        b'PK\x03\x04 body'
    ),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': (
        b'PK\x03\x04 body'
    ),
    'text/plain': b'just text',
    'application/zip': b'PK\x03\x04 body',
    'application/x-zip-compressed': b'PK\x03\x04 body',
}


@pytest.mark.asyncio
class TestEveryAllowedTypeUploads:
    """The allowlist and the signature table must agree.

    They did not — application/msword was allowed but had no signature entry,
    so validate_signature rejected every .doc as "unsupported file type" and
    the allowlist promised something the validator refused.
    """

    @pytest.mark.parametrize('content_type', sorted(ATTACHMENT_POLICY.content_types))
    @patch('app.modules.equipment.attachment_service.core_api')
    async def test_a_genuine_file_of_each_allowed_type_is_accepted(
        self, mock_core: Any, content_type: str
    ) -> None:
        assert content_type in _SAMPLE_BYTES, (
            f'{content_type} was added to the allowlist without a sample'
        )
        mock_core.items.get_async = AsyncMock(return_value=MagicMock())
        mock_core.file_storage.save_for_org_async = AsyncMock()
        db = AsyncMock()
        db.add = MagicMock()

        def _refresh(obj: Any) -> None:
            obj.id = uuid4()
            obj.created_at = datetime.now(UTC)

        db.refresh = AsyncMock(side_effect=_refresh)

        await upload_attachment(
            db,
            uuid4(),
            uuid4(),
            uuid4(),
            _SAMPLE_BYTES[content_type],
            'attachment.bin',
            content_type,
            'INVOICE',
        )

        mock_core.file_storage.save_for_org_async.assert_awaited_once()
