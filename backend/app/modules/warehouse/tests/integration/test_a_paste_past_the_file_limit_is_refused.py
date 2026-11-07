"""Pasted import text stops where an imported file stops.

A file is refused past ``MAX_IMPORT_SIZE`` before pandas reads a byte of it.
The three doors that take the same rows as pasted text declared no limit at
all: only the body cap in front of every request bounded them, and the
schema promised a client that any length would do.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.upload_validation import MAX_IMPORT_SIZE


def _paste_doors() -> list[Any]:
    return [
        pytest.param('/api/v1/warehouse/import/parse-paste', {}, id='parse-paste'),
        pytest.param(
            '/api/v1/warehouse/import/lines/paste', {'type': 'IN'}, id='lines-paste'
        ),
        pytest.param(
            f'/api/v1/warehouse/documents/{uuid4()}/import-paste',
            {},
            id='document-import-paste',
        ),
    ]


@pytest.mark.integration
@pytest.mark.parametrize(('path', 'rest'), _paste_doors())
def test_text_past_the_file_limit_is_refused_before_it_is_read(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    path: str,
    rest: dict[str, Any],
) -> None:
    # One character past the limit, small enough for the body cap to let the
    # request through: what answers is the schema, not the cap.
    text = 'x' * (MAX_IMPORT_SIZE + 1)

    response = client.post(path, headers=doc_auth_headers, json={'text': text, **rest})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    errors = response.json()['detail']
    assert [(e['loc'], e['type']) for e in errors] == [
        (['body', 'text'], 'string_too_long')
    ]
