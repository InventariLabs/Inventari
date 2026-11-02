"""The refusals of the core guards come back in the reader's language.

An upload with the wrong bytes, a sheet over the row cap, a file of a kind
the importer does not read, a pagination cursor that does not decode: each
was an English sentence written at the raise site, while the envelope stamped
the response with the session's language. The sentences now come from the
error catalogue.

Every assertion is an equality against the Polish catalogue entry, not a
status code: with a guard reverted to its English literal the response still
answers 400 and only the sentence tells the two builds apart.
"""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import is_reader_facing_value_error, refusal_text
from app.core.llm.errors import LlmContractError
from app.core.upload_validation import MAX_IMPORT_ROWS
from app.i18n.service import get_error_message
from app.models.item import Item

pytestmark = pytest.mark.integration

POLISH = {'Accept-Language': 'pl'}


def _pl(key: str, **kwargs: object) -> str:
    return get_error_message(key, 'pl', **kwargs)


def _message(response) -> str:
    detail = response.json()['detail']
    return detail if isinstance(detail, str) else detail['message']


class TestAnUploadWithTheWrongBytes:
    def test_the_signature_mismatch_is_said_in_polish(
        self, client: TestClient, auth_headers: dict, test_item: Item
    ) -> None:
        response = client.post(
            f'/api/v1/items/{test_item.id}/image',
            files={'image': ('cover.png', io.BytesIO(b'MZ\x90\x00' * 8), 'image/png')},
            headers={**auth_headers, **POLISH},
        )

        assert response.status_code == 400
        assert _message(response) == _pl('file_signature_mismatch')
        assert 'Sygnatura pliku' in _message(response)

    def test_an_empty_file_is_said_in_polish(
        self, client: TestClient, auth_headers: dict, test_item: Item
    ) -> None:
        response = client.post(
            f'/api/v1/items/{test_item.id}/image',
            files={'image': ('cover.png', io.BytesIO(b''), 'image/png')},
            headers={**auth_headers, **POLISH},
        )

        assert response.status_code == 400
        assert _message(response) == _pl('file_empty')


class TestAnImportFileTheImporterRefuses:
    def test_a_file_of_another_kind_names_what_is_allowed(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        response = client.post(
            '/api/v1/items/import',
            files={'file': ('stock.txt', b'name\nA\n', 'text/plain')},
            data={'mapping_json': json.dumps({'name': 'name'})},
            headers={**auth_headers, **POLISH},
        )

        assert response.status_code == 400
        assert _message(response) == _pl(
            'file_type_not_allowed_list', allowed='.csv, .xls, .xlsx'
        )

    def test_a_sheet_over_the_row_cap_names_the_count_and_the_limit(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        rows = '\n'.join(f'Row {n},1' for n in range(MAX_IMPORT_ROWS + 1))
        response = client.post(
            '/api/v1/items/import',
            files={
                'file': ('big.csv', f'Name,Quantity\n{rows}\n'.encode(), 'text/csv')
            },
            data={'mapping_json': json.dumps({'name': 'Name', 'quantity': 'Quantity'})},
            headers={**auth_headers, **POLISH},
        )

        assert response.status_code == 400
        detail = response.json()['detail']
        assert detail['message'] == _pl(
            'import_too_many_rows', count=MAX_IMPORT_ROWS + 1, limit=MAX_IMPORT_ROWS
        )


class TestAPaginationCursorThatDoesNotDecode:
    def test_the_keyset_cursor_is_refused_in_polish(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        response = client.get(
            '/api/v1/stock-moves?cursor=not-a-cursor',
            headers={**auth_headers, **POLISH},
        )

        assert response.status_code in (400, 422)
        assert _message(response) == _pl('pagination_cursor_invalid')

    def test_the_item_cursor_is_refused_in_polish(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        response = client.get(
            '/api/v1/items/history?cursor=not-a-cursor',
            headers={**auth_headers, **POLISH},
        )

        assert response.status_code == 400
        assert _message(response) == _pl('pagination_cursor_invalid')


class TestWhatAModelSentIsNeverTheReadersSentence:
    """``LlmContractError`` quotes the model's answer; it is written for the log."""

    def test_a_leaked_contract_error_is_not_handed_on_as_a_refusal(self) -> None:
        error = LlmContractError('LLM did not return JSON. Answer began: "Sure!"')

        assert not is_reader_facing_value_error(error)
        with pytest.raises(LlmContractError):
            refusal_text(error)

    def test_a_plain_refusal_still_is(self) -> None:
        assert is_reader_facing_value_error(ValueError('x'))
