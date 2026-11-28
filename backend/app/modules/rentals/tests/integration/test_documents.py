"""The pick list and the hand-over sheet print in every maintained language."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.modules.rentals import _documents
from app.modules.rentals._documents import LABELS
from app.modules.rentals.tests.conftest import booking_payload

pytestmark = pytest.mark.integration

RENTALS = '/api/v1/rentals'
LANGUAGES = ('en', 'pl', 'de', 'fr', 'es', 'pt')


def test_every_language_speaks_the_same_keys() -> None:
    keys = set(LABELS['en'])
    for language in LANGUAGES:
        assert set(LABELS[language]) == keys, language
        assert all(value for value in LABELS[language].values()), language


def test_the_pick_list_prints_for_a_reserved_booking(
    client: TestClient, rental_auth: dict[str, str], projectors, screen
) -> None:
    booking = client.post(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        json={
            **booking_payload(),
            'lines': [
                {'item_id': str(screen.id)},
                {'model': 'Projektor 4K', 'quantity': 2},
            ],
        },
    )
    assert booking.status_code == 201, booking.text
    booking_id = booking.json()['id']

    for language in LANGUAGES:
        response = client.get(
            f'{RENTALS}/bookings/{booking_id}/pick-list',
            headers=rental_auth,
            params={'lang': language},
        )
        assert response.status_code == 200, (language, response.text)
        assert response.headers['content-type'] == 'application/pdf'
        assert response.content.startswith(b'%PDF')


def test_the_handover_sheet_names_what_went_out_and_until_when(
    client: TestClient, rental_auth: dict[str, str], projectors
) -> None:
    booking = client.post(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        json=booking_payload(item_id=projectors[0].id),
    ).json()
    picked = client.post(
        f'{RENTALS}/bookings/{booking["id"]}/pickup',
        headers=rental_auth,
        json={'item_ids': [str(projectors[0].id)]},
    )
    assert picked.status_code == 200, picked.text

    for language in LANGUAGES:
        response = client.get(
            f'{RENTALS}/bookings/{booking["id"]}/handover-sheet',
            headers=rental_auth,
            params={'lang': language},
        )
        assert response.status_code == 200, (language, response.text)
        assert response.content.startswith(b'%PDF')


def test_the_handover_table_is_headed_by_what_went_out() -> None:
    for language in LANGUAGES:
        labels = LABELS[language]
        assert labels['handed_lines'] != labels['lines'], language
    assert '{{L.handed_lines}}' in _documents._HANDOVER_HTML
    assert '{{L.lines}}' not in _documents._HANDOVER_HTML


def test_a_broken_stored_layout_prints_the_built_in_one_and_says_so(
    client: TestClient,
    rental_auth: dict[str, str],
    projectors,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def broken(*_args) -> str:
        return '{% for %}'

    monkeypatch.setattr(_documents, '_stored_layout', broken)
    booking = client.post(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        json=booking_payload(item_id=projectors[0].id),
    ).json()

    with caplog.at_level(logging.WARNING):
        response = client.get(
            f'{RENTALS}/bookings/{booking["id"]}/pick-list', headers=rental_auth
        )

    assert response.status_code == 200, response.text
    assert response.content.startswith(b'%PDF')
    assert 'stored PICK_LIST layout' in caplog.text
