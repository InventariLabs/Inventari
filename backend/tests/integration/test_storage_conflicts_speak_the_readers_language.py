"""The two conflicts of the storage tree answer in the reader's language.

A short code taken by another location, and a move of a location under its
own descendant, used to carry an English sentence under a ``lang`` stamp. They
come from the error catalogue now; the 409 and the machine code a client
branches on (``STORAGE_SHORT_CODE_CONFLICT``, ``STORAGE_CYCLE``) are unchanged.

A label that cannot be rendered is a 500 nobody supplied: it is answered by the
global handler with the catalogue's sentence, not an English literal.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

STORAGES = '/api/v1/locations/'
PL = {'Accept-Language': 'pl'}


def _create(client, headers, name: str, **extra):
    response = client.post(STORAGES, headers=headers, json={'name': name, **extra})
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()


@pytest.mark.integration
class TestStorageConflictsSpeakTheReadersLanguage:
    def test_a_taken_short_code_is_refused_in_polish(
        self, client, auth_headers
    ) -> None:
        _create(client, auth_headers, 'First', short_code='LOC-9')

        response = client.post(
            STORAGES,
            headers={**auth_headers, **PL},
            json={'name': 'Second', 'short_code': 'LOC-9'},
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'STORAGE_SHORT_CODE_CONFLICT'
        assert detail['message'] == (
            'Krótki kod „LOC-9” jest już używany przez inne miejsce.'
        )

    def test_a_move_under_a_descendant_is_refused_in_polish(
        self, client, auth_headers
    ) -> None:
        site = _create(client, auth_headers, 'Site')
        zone = _create(client, auth_headers, 'Zone', parent_id=site['id'])

        response = client.put(
            f'{STORAGES}{site["id"]}',
            headers={**auth_headers, **PL},
            json={'parent_id': zone['id']},
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'STORAGE_CYCLE'
        assert detail['message'] == (
            'Miejsca nie można przenieść pod jego własne miejsce podrzędne — '
            'powstałby cykl w hierarchii miejsc.'
        )

    def test_a_label_that_cannot_be_rendered_is_a_polish_500(
        self, client, auth_headers, monkeypatch
    ) -> None:
        from app.core import label_rendering

        def broken(*args, **kwargs):
            raise OSError('font missing')

        monkeypatch.setattr(label_rendering, 'render_label_png', broken)
        site = _create(client, auth_headers, 'Site')
        # The global handler answers the 500; the test client would otherwise
        # re-raise the error instead of showing what the client receives.
        quiet = TestClient(client.app, raise_server_exceptions=False)

        response = quiet.get(
            f'{STORAGES}{site["id"]}/print', headers={**auth_headers, **PL}
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()['detail'] == {
            'code': 'INTERNAL_ERROR',
            'message': 'Wystąpił błąd wewnętrzny',
        }
