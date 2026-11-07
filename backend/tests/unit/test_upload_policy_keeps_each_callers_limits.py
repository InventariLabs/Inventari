"""One mechanism and one type list, two policies that differ on purpose.

Item attachments and equipment attachments answer "may this file be
uploaded" with the same steps — extension, declared type, size, signature.
They accept the same types: one list, kept in the core, so a type is
admitted or refused for both in one place. What stays different is a
product call — the size limit, and whether the filename is gated. This
checks that sharing the steps and the list did not quietly share those.
"""

from __future__ import annotations

import pytest

from app.core.upload_validation import (
    ATTACHMENT_CONTENT_TYPES,
    FileTooLargeError,
    FileTypeNotAllowedError,
    UploadMessages,
)
from app.modules.equipment.attachment_service import ATTACHMENT_POLICY as EQUIPMENT
from app.services.attachment_service import ITEM_ATTACHMENT_POLICY as ITEM

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
PDF = b'%PDF-1.7\n' + b'\x00' * 32
OLE2 = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 32
EXE = b'MZ\x90\x00' + b'\x00' * 32

MESSAGES = UploadMessages(
    type_not_allowed='not allowed',
    too_large='too large',
    signature_mismatch='mismatch',
)


@pytest.mark.unit
class TestUploadPolicyKeepsEachCallersLimits:
    def test_fifteen_megabytes_is_a_warranty_scan_but_not_a_product_photo(
        self,
    ) -> None:
        big = PDF + b'\x00' * (15 * 1024 * 1024)

        assert (
            EQUIPMENT.check(
                big, declared_type='application/pdf', messages=MESSAGES
            ).stored_type
            == 'application/pdf'
        )
        with pytest.raises(FileTooLargeError):
            ITEM.check(
                big,
                declared_type='application/pdf',
                filename='photo.pdf',
                messages=MESSAGES,
            )

    def test_both_accept_the_one_list_of_types(self) -> None:
        """Two copies of the list drifted apart once: equipment took .doc
        while item attachments refused it, each with a reason of its own."""
        assert ITEM.content_types == ATTACHMENT_CONTENT_TYPES
        assert EQUIPMENT.content_types == ATTACHMENT_CONTENT_TYPES

    def test_a_doc_is_refused_by_both(self) -> None:
        """The old binary Word format stays out by decision, not for want of
        a signature: .docx is the Word format to use."""
        with pytest.raises(FileTypeNotAllowedError):
            EQUIPMENT.check(OLE2, declared_type='application/msword', messages=MESSAGES)
        with pytest.raises(FileTypeNotAllowedError):
            ITEM.check(
                OLE2,
                declared_type='application/msword',
                filename='warranty.doc',
                messages=MESSAGES,
            )

    def test_the_filename_gates_item_attachments_and_not_equipment(self) -> None:
        """The item screen promises a list of extensions; the equipment one
        takes the name as a label and derives the extension from the bytes."""
        with pytest.raises(FileTypeNotAllowedError):
            ITEM.check(
                PNG, declared_type='image/png', filename='photo.exe', messages=MESSAGES
            )

        accepted = EQUIPMENT.check(PNG, declared_type='image/png', messages=MESSAGES)
        assert accepted.extension == 'png'

    def test_the_bytes_are_checked_for_both(self) -> None:
        for policy, filename in ((ITEM, 'invoice.pdf'), (EQUIPMENT, None)):
            with pytest.raises(FileTypeNotAllowedError):
                policy.check(
                    EXE,
                    declared_type='application/pdf',
                    filename=filename,
                    messages=MESSAGES,
                )
