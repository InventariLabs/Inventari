"""The pre-save connection test learns refusals for the organization that ran it.

A draft has no row id, so the refusal memory keys it by its route — and the
organization is part of that route. The organization reaches the draft only
because ``test_connection`` passes the caller's to ``build_transient``; a test
of the constructor alone stays green while that call site hands over nothing,
or somebody else's identity.

So these drive the endpoint itself, with a provider that refuses one optional
key, and read what the next request carried: the same organization asking
again must not pay for the refusal twice, and another organization asking the
same route must not inherit it.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.llm.openai_client import OpenAiCompatibleClient

pytestmark = pytest.mark.integration

_URL = '/api/v1/ai-connections/test'
_REFUSED_KEY = 'response_format'
_GOOD_ANSWER = (
    '{"name": "Oat Drink", "brand": "Barista Edition", '
    '"weight": "1 L", "expiry_date": "2027-01-31"}'
)
_DRAFT = {
    'provider': 'openrouter',
    'api_key': 'sk-or-fake',
    'api_base_url': 'https://openrouter.ai/api/v1',
    'model_name': 'some/model',
    'capabilities': ['vision', 'text'],
}


@pytest.fixture(autouse=True)
def _clean_memory():
    from app.core.llm import _optional_payload

    _optional_payload._refused_since.clear()
    yield
    _optional_payload._refused_since.clear()


@pytest.fixture
def provider_calls():
    """Every chat request the provider received, in order, as a JSON body.

    The provider refuses the optional key whenever it is sent, and answers
    the request without it.
    """
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if _REFUSED_KEY in body:
            return httpx.Response(
                400, json={'error': {'message': f'Unknown parameter: {_REFUSED_KEY}'}}
            )
        return httpx.Response(
            200,
            json={'choices': [{'message': {'content': _GOOD_ANSWER}}], 'usage': {}},
        )

    def client_for(connection):
        return OpenAiCompatibleClient(
            connection, _transport=httpx.MockTransport(handler)
        )

    with (
        patch('app.core.llm.factory.get_client', side_effect=client_for),
        patch.object(
            OpenAiCompatibleClient,
            'list_models',
            new=AsyncMock(return_value=['some/model']),
        ),
    ):
        yield calls


@pytest.fixture
def other_org_headers(db_session, test_household) -> dict:
    from app.models.organization import Organization
    from app.models.user import User
    from app.services.token_service import create_access_token, get_password_hash

    other = Organization(
        name='Other Org', enabled_modules=list(test_household.enabled_modules or [])
    )
    db_session.add(other)
    db_session.flush()
    admin = User(
        email='other-admin@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='Other Admin',
        organization_id=other.id,
        role='admin',
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    token = create_access_token(data={'sub': str(admin.id)})
    return {'Authorization': f'Bearer {token}'}


def _first_request_of_the_next_test(client, headers, calls: list[dict]) -> dict:
    before = len(calls)
    response = client.post(_URL, json=_DRAFT, headers=headers)
    assert response.status_code == 200, response.text
    assert len(calls) > before, 'the probe never reached the provider'
    return calls[before]


class TestADraftTestLearnsForItsOwnOrganization:
    def test_the_same_organization_does_not_pay_for_the_refusal_twice(
        self, client, auth_headers, provider_calls
    ):
        first = _first_request_of_the_next_test(client, auth_headers, provider_calls)
        # The instrument can see a refusal at all: the probe sent the key and
        # the provider turned it down, so there is something to remember.
        assert _REFUSED_KEY in first
        assert _REFUSED_KEY not in provider_calls[-1]

        again = _first_request_of_the_next_test(client, auth_headers, provider_calls)

        assert _REFUSED_KEY not in again

    def test_another_organization_asks_the_same_route_on_its_own_merits(
        self, client, auth_headers, other_org_headers, provider_calls
    ):
        first = _first_request_of_the_next_test(client, auth_headers, provider_calls)
        assert _REFUSED_KEY in first

        stranger = _first_request_of_the_next_test(
            client, other_org_headers, provider_calls
        )

        assert _REFUSED_KEY in stranger
