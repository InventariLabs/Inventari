"""An assignment hands the asset to a person **or** deploys it to a place.

The checkout form has offered both modes since it shipped — "to a person"
and "to a location" — but ``AssignmentCreate.assigned_to_name`` carried
``min_length=1``, so the second mode posted a body the schema refused. The
refusal named ``assigned_to_name``, a field the reader was never shown in
that mode. Measured on dev before the fix: zero of the stored assignments
carried a ``checkout_location_id``, so the path had never produced a record.

These tests pin the requirement itself — one of the two, not both, not the
name unconditionally. Measured against the reverted fix (``min_length=1``
back on the schema field, the service check removed): five of the six
fail. ``location_only`` gets a 422 where it wants a 201;
``whitespace_is_not_a_name`` gets a 422 whose body is Pydantic's, because a
length cap counts a space as a character; ``neither_person_nor_location``
and ``the_refusal_is_translated`` get Pydantic's 422, naming a field the
location mode never shows, where they want this rule's own 400 in the
reader's language; ``both_person_and_location`` is not refused at all.

Only ``person_only`` passes either way, deliberately: it guards the mode
that already worked.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation

_URL = '/api/v1/equipment/assignments'


@pytest.mark.integration
class TestAssignmentNeedsAPersonOrAPlace:
    def test_both_person_and_location_are_refused(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
    ) -> None:
        resp = client.post(
            _URL,
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Anna Nowak',
                'checkout_location_id': str(eq_storage_location.id),
            },
        )
        assert resp.status_code == 400, resp.text
        assert 'not both' in resp.json()['detail']['message']

    def test_location_only_checkout_creates_the_assignment(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
    ) -> None:
        resp = client.post(
            _URL,
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'checkout_location_id': str(eq_storage_location.id),
            },
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body['checkout_location_id'] == str(eq_storage_location.id)
        assert body['checkout_location_name'] == eq_storage_location.name
        # No person took it, so the field that names one stays empty rather
        # than borrowing the location's name: "who has it" and "where it
        # stands" are two different questions and only one has an answer.
        assert body['assigned_to_name'] == ''
        # The display surfaces read the holder instead, which does have an
        # answer for a deployment — the place, marked as one.
        assert body['holder_name'] == eq_storage_location.name
        assert body['holder_kind'] == 'location'

    def test_person_only_checkout_still_works(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        resp = client.post(
            _URL,
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Anna Nowak'},
        )

        assert resp.status_code == 201, resp.text
        assert resp.json()['assigned_to_name'] == 'Anna Nowak'
        assert resp.json()['holder_name'] == 'Anna Nowak'
        assert resp.json()['holder_kind'] == 'person'

    def test_neither_person_nor_location_is_refused(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        resp = client.post(
            _URL, headers=eq_auth_headers, json={'item_id': str(eq_item.id)}
        )

        # A business rule, so a keyed rejection the envelope can translate
        # (``test_service_rejection_messages_i18n`` gates the shape) rather
        # than a schema error naming a field the location mode never shows.
        assert resp.status_code == 400, resp.text
        assert 'assigned_to_name' not in resp.text

    def test_the_refusal_is_translated(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        # The reason the rule sits in the service and not in a Pydantic
        # validator: a keyed rejection is translated with the request
        # language, a schema error is not. This path is not reachable from
        # the application's own form, which offers one mode or the other --
        # it guards the API and whatever calls it next.
        resp = client.post(
            _URL,
            headers=dict(eq_auth_headers, **{'Accept-Language': 'pl'}),
            json={'item_id': str(eq_item.id)},
        )

        assert resp.status_code == 400, resp.text
        assert 'Podaj osobę' in resp.text, resp.text

    def test_whitespace_is_not_a_name(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        # ``min_length`` counted characters, so a single space passed it and
        # stored a holder whose name renders as nothing on every screen that
        # shows it — and on the handover protocol's signature line.
        resp = client.post(
            _URL,
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': '   '},
        )

        assert resp.status_code == 400, resp.text
