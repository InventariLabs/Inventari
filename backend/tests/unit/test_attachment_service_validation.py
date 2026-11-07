"""Upload validation lives in the service, not only in the router.

Every test here calls ``AttachmentService.create_attachment`` directly with
``db=None``: a rejected upload must be refused before the database or file
storage is touched, so a caller that is not the router cannot slip past the checks.
"""

from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.upload_validation import FileTooLargeError, FileTypeNotAllowedError
from app.services.attachment_service import MAX_UPLOAD_SIZE, AttachmentService

PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
PDF_BYTES = b'%PDF-1.7\n' + b'\x00' * 32
EXE_BYTES = b'MZ\x90\x00' + b'\x00' * 32

pytestmark = pytest.mark.asyncio


def _upload(content: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({'content-type': content_type}),
    )


class TestCreateAttachmentRejects:
    async def test_executable_disguised_as_png(self):
        """The whole point of magic bytes: name and header both claim PNG."""
        upload = _upload(EXE_BYTES, 'payload.png', 'image/png')

        with pytest.raises(FileTypeNotAllowedError):
            await AttachmentService.create_attachment(
                None, uuid4(), uuid4(), upload, user_id=uuid4()
            )

    async def test_pdf_bytes_declared_as_png(self):
        upload = _upload(PDF_BYTES, 'report.png', 'image/png')

        with pytest.raises(FileTypeNotAllowedError):
            await AttachmentService.create_attachment(
                None, uuid4(), uuid4(), upload, user_id=uuid4()
            )

    async def test_disallowed_extension(self):
        upload = _upload(EXE_BYTES, 'payload.exe', 'image/png')

        with pytest.raises(FileTypeNotAllowedError):
            await AttachmentService.create_attachment(
                None, uuid4(), uuid4(), upload, user_id=uuid4()
            )

    async def test_disallowed_content_type(self):
        """Extension is fine, declared type is not on the allow-list."""
        upload = _upload(PNG_BYTES, 'image.png', 'application/x-msdownload')

        with pytest.raises(FileTypeNotAllowedError):
            await AttachmentService.create_attachment(
                None, uuid4(), uuid4(), upload, user_id=uuid4()
            )

    async def test_empty_file(self):
        upload = _upload(b'', 'empty.png', 'image/png')

        with pytest.raises(FileTypeNotAllowedError):
            await AttachmentService.create_attachment(
                None, uuid4(), uuid4(), upload, user_id=uuid4()
            )

    async def test_oversized_file_is_refused_without_being_read(self):
        """Size is checked by seeking, so a huge upload never reaches memory."""
        upload = _upload(PNG_BYTES + b'\x00' * MAX_UPLOAD_SIZE, 'big.png', 'image/png')

        with pytest.raises(FileTooLargeError):
            await AttachmentService.create_attachment(
                None, uuid4(), uuid4(), upload, user_id=uuid4()
            )

        # Still at the start: nothing consumed the stream.
        assert upload.file.tell() == 0


class TestLegacyOfficeFormats:
    """No attachment takes .doc; .docx is the Word format to use."""

    async def test_doc_is_refused_with_a_type_error(self):
        upload = _upload(
            b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 32,
            'report.doc',
            'application/msword',
        )

        with pytest.raises(FileTypeNotAllowedError):
            await AttachmentService.create_attachment(
                None, uuid4(), uuid4(), upload, user_id=uuid4()
            )

    async def test_docx_still_works(self):
        """The OOXML replacement must keep passing validation."""
        docx = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        upload = _upload(b'PK\x03\x04' + b'\x00' * 32, 'report.docx', docx)

        # Gets past validation and fails later, on the None session.
        with pytest.raises((AttributeError, TypeError)):
            await AttachmentService.create_attachment(
                None, uuid4(), uuid4(), upload, user_id=uuid4()
            )
