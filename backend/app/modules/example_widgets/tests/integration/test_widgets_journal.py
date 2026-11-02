"""The reference module writes its acts into the organization's journal.

A module made by ``make new-module`` is a copy of this one, and the
architecture gate refuses a module whose writes leave no journal entry. The
reference module used to pass that gate on baseline entries of its own, which
a copy does not inherit — so every new module failed its first commit. What
this module does is what every copy will do; so it journals, and this test
says what the journal holds afterwards.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.user import User

pytestmark = pytest.mark.integration


def _journal(
    client: TestClient, auth: dict[str, str], widget_id: str
) -> list[dict[str, Any]]:
    resp = client.get(
        '/api/v1/audit-log',
        params={'target_type': 'example_widgets', 'target_id': widget_id},
        headers=auth,
    )
    assert resp.status_code == 200
    entries: list[dict[str, Any]] = resp.json()['items']
    return entries


class TestEveryWriteIsJournaled:
    def test_create_update_and_delete_each_leave_an_entry_with_their_author(
        self, client: TestClient, widget_auth: dict[str, str], widget_user: User
    ) -> None:
        created = client.post(
            '/api/v1/example-widgets',
            json={'name': 'Journaled', 'quantity': 1},
            headers=widget_auth,
        )
        assert created.status_code == 201
        widget_id = created.json()['id']
        assert (
            client.patch(
                f'/api/v1/example-widgets/{widget_id}',
                json={'quantity': 4},
                headers=widget_auth,
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f'/api/v1/example-widgets/{widget_id}', headers=widget_auth
            ).status_code
            == 204
        )

        entries = _journal(client, widget_auth, widget_id)

        assert sorted(e['action'] for e in entries) == [
            'CREATE',
            'SOFT_DELETE',
            'UPDATE',
        ]
        assert {e['user_id'] for e in entries} == {str(widget_user.id)}
        update = next(e for e in entries if e['action'] == 'UPDATE')
        assert update['snapshot']['quantity'] == 4
