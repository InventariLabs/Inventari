"""The profile lets an organization name every type the module handles.

The numbering prefix and the printed title read ``type_labels``; scrap
documents are raised and numbered like the rest, yet the validator listed
six keys and refused ``SCRAP``, so a preset that ships a label for it
(``PL Magazyn``: ``ZL``) could not be saved back after an edit.
"""

import pytest
from pydantic import ValidationError

from app.modules.warehouse.document_profile_service import PRESETS
from app.modules.warehouse.models import DocumentType
from app.modules.warehouse.schemas import DocumentProfileUpdate


@pytest.mark.unit
class TestTheProfileNamesEveryDocumentType:
    def test_scrap_can_be_named(self) -> None:
        """Fails without the fix: ``type_labels keys must be IN, OUT, ...``."""
        profile = DocumentProfileUpdate(type_labels={'SCRAP': 'ZL'})

        assert profile.type_labels == {'SCRAP': 'ZL'}

    def test_a_preset_label_is_accepted_back(self) -> None:
        for preset in PRESETS.values():
            if preset.get('type_labels'):
                DocumentProfileUpdate(type_labels=preset['type_labels'])

    def test_every_document_type_is_accepted(self) -> None:
        labels = {doc_type.value: 'X' for doc_type in DocumentType}

        assert DocumentProfileUpdate(type_labels=labels).type_labels == labels

    def test_a_name_that_is_no_type_is_still_refused(self) -> None:
        with pytest.raises(ValidationError, match='type_labels keys must be'):
            DocumentProfileUpdate(type_labels={'BOGUS': 'X'})
