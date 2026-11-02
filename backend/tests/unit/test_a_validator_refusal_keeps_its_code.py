"""A refusal raised inside a validator or before a request is read keeps its code.

These sites used to translate the sentence themselves and raise it as a plain
``ValueError``: the words were right, but the envelope saw no catalogue key and
answered ``VALIDATION_ERROR``, so a client could tell the reasons apart only by
reading them. Each test reads the code from the exception the site raises,
which is what the 400 handler and the 422 entry turn into ``code``.
"""

import io
from uuid import uuid4

import pytest
from fastapi import UploadFile
from pydantic import ValidationError

from app.core.contracts._core_dtos import PartnerAddressDTO, PartnerUpdateDTO
from app.core.exceptions import ServiceRejectionError
from app.core.upload_validation import validate_import_file
from app.modules.approvals.schemas import RequesterScope
from app.schemas.partner import PartnerUpdate


@pytest.mark.parametrize(
    ('build', 'code'),
    [
        pytest.param(
            lambda: PartnerAddressDTO(country='XX'),
            'INVALID_COUNTRY_CODE',
            id='contract-address-country',
        ),
        pytest.param(
            lambda: PartnerUpdateDTO(type='ALIEN'),
            'INVALID_PARTNER_TYPE',
            id='contract-partner-update-type',
        ),
        pytest.param(
            lambda: PartnerUpdate(type='ALIEN'),
            'INVALID_PARTNER_TYPE',
            id='api-partner-update-type',
        ),
        pytest.param(
            lambda: RequesterScope(everyone=True, user_ids=[uuid4()]),
            'APPROVAL_REQUESTER_SCOPE_EVERYONE_WITH_NAMES',
            id='approval-scope-everyone-with-names',
        ),
    ],
)
def test_a_validator_refusal_carries_its_catalogue_code(build, code) -> None:
    with pytest.raises(ValidationError) as exc_info:
        build()

    (error,) = exc_info.value.errors()
    refusal = error['ctx']['error']
    assert isinstance(refusal, ServiceRejectionError)
    assert refusal.code == code


def test_an_import_file_without_a_name_is_refused_with_a_code() -> None:
    with pytest.raises(ServiceRejectionError) as exc_info:
        validate_import_file(UploadFile(file=io.BytesIO(b''), filename=''))

    assert exc_info.value.code == 'FILE_TYPE_NOT_ALLOWED'
