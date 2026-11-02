"""Refusals of the catalogue that used to carry an English literal.

A request with no organization, a failure while storing an attachment, and a
core-API write whose organization contradicts its user's were each answered
with a hard-coded English sentence. The first two now come from the error
catalogue in the request language; the third is a caller's mistake, so it is a
``ContractViolationError`` (a logged 500), never a sentence for a reader.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.contracts import ItemCreateDTO, UserContextDTO
from app.core.deps import get_current_user_context
from app.core.exceptions import ContractViolationError
from app.core.public_api import core_api

PL = {'Accept-Language': 'pl'}


class TestCatalogueRefusalsSpeakTheReadersLanguage:
    def test_a_request_without_an_organization_is_refused_in_polish(
        self, client, auth_headers
    ) -> None:
        orgless = UserContextDTO(id=uuid4(), organization_id=None, role='admin')
        client.app.dependency_overrides[get_current_user_context] = lambda: orgless
        try:
            response = client.get(
                f'/api/v1/categories/{uuid4()}', headers={**auth_headers, **PL}
            )
        finally:
            client.app.dependency_overrides.pop(get_current_user_context, None)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.text
        assert response.json()['detail']['message'] == 'Organizacja jest wymagana'

    def test_an_attachment_that_cannot_be_stored_is_a_polish_500(
        self, client, auth_headers, test_item, monkeypatch
    ) -> None:
        from app.services.attachment_service import AttachmentService

        async def broken(*args, **kwargs):
            raise RuntimeError('disk full')

        monkeypatch.setattr(AttachmentService, 'create_attachment', broken)
        # The global handler answers the 500; the test client would otherwise
        # re-raise the error instead of showing what the client receives.
        quiet = TestClient(client.app, raise_server_exceptions=False)

        response = quiet.post(
            f'/api/v1/items/{test_item.id}/attachments',
            headers={**auth_headers, **PL},
            files={'file': ('a.txt', b'hello', 'text/plain')},
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()['detail'] == {
            'code': 'INTERNAL_ERROR',
            'message': 'Wystąpił błąd wewnętrzny',
        }


@pytest.mark.asyncio
async def test_a_core_api_write_for_another_organization_is_a_contract_breach() -> None:
    user = UserContextDTO(id=uuid4(), organization_id=uuid4())

    with pytest.raises(ContractViolationError, match='does not match'):
        await core_api.items.create_async(
            MagicMock(), uuid4(), MagicMock(spec=ItemCreateDTO), user
        )
