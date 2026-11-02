"""One mechanism, two policies that stay different on purpose.

Item attachments and equipment attachments answer "may this file be
uploaded" with the same steps — extension, declared type, size, signature —
and different answers. The limits and the allowlists are product calls; the
steps were copied. This checks that consolidating the steps did not
quietly consolidate the calls.
"""

from __future__ import annotations

import pytest

from app.core.upload_validation import (
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

    def test_a_doc_is_accepted_by_one_and_refused_by_the_other(self) -> None:
        """No signature tells a .doc from an .xls, so item attachments
        refuse the type rather than promise what the validator would
        reject; a supplier's warranty arrives as whatever they sent."""
        assert (
            EQUIPMENT.check(
                OLE2, declared_type='application/msword', messages=MESSAGES
            ).extension
            == 'doc'
        )
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
