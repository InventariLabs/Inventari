"""On a public demo a request for access is refused, and nothing is stored.

A request lands where only an instance superuser can read it, and a demo has
no superuser by design: the visitor was told the request had been submitted
and waited for an answer that could not come, while the instance kept a
stranger's name and address until the nightly reset. Password reset is
refused on a demo for the same kind of reason; requests for access were not.
Outside a demo the flow stays exactly as it was.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import RegistrationRequest

pytestmark = pytest.mark.integration

_REQUEST = '/api/v1/auth/registration-request'

# Pinned as text rather than looked up through the same catalogue the
# endpoint reads: the point is that a Polish visitor reads this sentence.
_PL_REFUSAL = (
    'To publiczne demo, a odwiedzający nie potrzebują tu konta. Opcja '
    '„Poproś o dostęp” nie jest tu dostępna — skorzystaj z „Wypróbuj demo”.'
)


def _declare_demo(monkeypatch: pytest.MonkeyPatch, *, demo: bool) -> None:
    monkeypatch.setattr('app.api.auth._registration.settings.INVENTARI_DEMO', demo)


def _request(client: TestClient, email: str, *, lang: str = 'pl'):
    return client.post(
        _REQUEST,
        json={'email': email, 'full_name': 'Visitor', 'preferred_language': lang},
        headers={'Accept-Language': lang},
    )


def _stored(db: Session, email: str) -> list[RegistrationRequest]:
    return list(
        db.scalars(
            select(RegistrationRequest).where(RegistrationRequest.email == email)
        ).all()
    )


def test_the_demo_refuses_the_request_and_stores_nothing(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _declare_demo(monkeypatch, demo=True)
    email = f'demo-visitor-{uuid4()}@example.com'

    response = _request(client, email)

    assert response.status_code == 400
    assert response.json()['detail']['message'] == _PL_REFUSAL
    assert _stored(db_session, email) == []


def test_outside_a_demo_the_request_is_accepted_and_stored(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _declare_demo(monkeypatch, demo=False)
    email = f'visitor-{uuid4()}@example.com'

    response = _request(client, email)

    assert response.status_code == 201
    assert response.json()['message'] == 'Request submitted successfully'
    assert len(_stored(db_session, email)) == 1
