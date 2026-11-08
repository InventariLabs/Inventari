"""The connection test spends the organization's AI budget, so the budget gates it.

The probe is a real call: the provider charges for it and the ledger books it
against the monthly ceiling, so pressing "Test" in Settings costs money the
same way reading a label does. What that left open is the obvious half —
nothing asked the ceiling before spending it. An administrator could drain the
month's budget one test at a time, and the refusal, when it finally arrived
from somewhere else, said only that the quota was exceeded: no numbers, no
ceiling, no period.

These tests pin both sides of the gate: over the limit the provider is never
reached, under it the test still runs, and the refusal carries what the counter
had in hand.
"""

from __future__ import annotations

from calendar import monthrange
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.core.llm.base import LlmResponse
from app.models import Organization
from app.models.ai_usage_log import AIUsageLog

_URL = '/api/v1/ai-connections/test'

_GOOD_ANSWER = (
    '{"name": "Oat Drink", "brand": "Barista Edition", '
    '"weight": "1 L", "expiry_date": "2027-01-31"}'
)


def _draft() -> dict:
    return {
        'provider': 'openrouter',
        'api_key': 'sk-or-fake',
        'api_base_url': 'https://openrouter.ai/api/v1',
        'model_name': 'some/model',
        'capabilities': ['vision', 'text'],
    }


def _cap_requests(db: Session, org: Organization, monthly_requests: int) -> None:
    org.settings = {'limits': {'ai_requests_monthly': monthly_requests}}
    db.commit()


def _spend(db: Session, org: Organization, calls: int) -> None:
    """Book *calls* billable AI rows for the org, as the ledger would."""
    for _ in range(calls):
        db.add(
            AIUsageLog(
                organization_id=org.id,
                model_name='some/model',
                provider='openrouter',
                action_type='connection_test',
            )
        )
    db.commit()


def _this_month() -> tuple[str, str]:
    """The period the counter counts over, in the shape the refusal reports it."""
    now = datetime.now(UTC)
    _, last_day = monthrange(now.year, now.month)
    return (
        f'{now.year:04d}-{now.month:02d}-01',
        f'{now.year:04d}-{now.month:02d}-{last_day:02d}',
    )


@contextmanager
def _provider(list_models: AsyncMock, complete: AsyncMock):
    """Both halves of the provider, replaced so a test can watch them."""
    with (
        patch(
            'app.core.llm.openai_client.OpenAiCompatibleClient.list_models',
            new=list_models,
        ),
        patch(
            'app.core.llm.openai_client.OpenAiCompatibleClient.complete',
            new=complete,
        ),
    ):
        yield


def _provider_mocks() -> tuple[AsyncMock, AsyncMock]:
    return (
        AsyncMock(return_value=['some/model']),
        AsyncMock(return_value=LlmResponse(content=_GOOD_ANSWER, usage={})),
    )


@pytest.mark.integration
class TestOverTheLimit:
    """The one call that must not happen: the one there is no budget for."""

    def test_the_polish_refusal_names_its_language(
        self, db_session, test_household, client, auth_headers
    ):
        _cap_requests(db_session, test_household, 1)
        _spend(db_session, test_household, 1)
        list_models, complete = _provider_mocks()
        with _provider(list_models, complete):
            response = client.post(
                _URL, json=_draft(), headers={**auth_headers, 'Accept-Language': 'pl'}
            )
        assert response.status_code == 429
        detail = response.json()['detail']
        assert detail['lang'] == 'pl'
        assert 'Organizacja wykorzystała 1 z 1 zapytań AI' in detail['message']

    def test_the_provider_is_never_asked(
        self, db_session, test_household, client, auth_headers
    ):
        _cap_requests(db_session, test_household, 2)
        _spend(db_session, test_household, 2)
        list_models, complete = _provider_mocks()

        with _provider(list_models, complete):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.status_code == 429, response.text
        list_models.assert_not_awaited()
        complete.assert_not_awaited()

    def test_the_refusal_carries_the_numbers_and_the_period(
        self, db_session, test_household, client, auth_headers
    ):
        """``AI usage quota exceeded`` was true, and told the reader nothing."""
        _cap_requests(db_session, test_household, 2)
        _spend(db_session, test_household, 3)
        list_models, complete = _provider_mocks()

        with _provider(list_models, complete):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.status_code == 429, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'AI_USAGE_LIMIT_EXCEEDED'
        assert detail['limit_key'] == 'ai_requests_monthly'
        assert detail['used'] == 3
        assert detail['limit'] == 2

        period_start, period_end = _this_month()
        assert detail['period_start'] == period_start
        assert detail['period_end'] == period_end

        # The sentence a toast shows is the catalogue's, and the numbers are in
        # it too — a reader who never opens a network tab learns which budget
        # ran out, how much of it, and for which period.
        assert '3' in detail['message']
        assert '2' in detail['message']
        assert period_start in detail['message']


@pytest.mark.integration
class TestUnderTheLimit:
    def test_the_test_still_runs(
        self, db_session, test_household, client, auth_headers
    ):
        _cap_requests(db_session, test_household, 5)
        _spend(db_session, test_household, 4)
        list_models, complete = _provider_mocks()

        with _provider(list_models, complete):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.status_code == 200, response.text
        assert response.json()['verdict'] == 'ok'
        list_models.assert_awaited_once()
        complete.assert_awaited_once()


@pytest.mark.integration
class TestACounterOutageIsNotAnAnswer:
    """A counter that cannot be read refuses nothing.

    The gate is best-effort by design: an organization whose usage counter is
    down must still be able to test a connection, or a bookkeeping outage
    becomes a configuration screen nobody can use.
    """

    def test_the_test_runs_when_the_counter_is_down(
        self, db_session, test_household, client, auth_headers
    ):
        list_models, complete = _provider_mocks()

        with (
            patch(
                'app.services.ai_usage_service.check_ai_limit_async',
                new=AsyncMock(side_effect=RuntimeError('counter is down')),
            ),
            _provider(list_models, complete),
        ):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.status_code == 200, response.text
        assert response.json()['verdict'] == 'ok'
        list_models.assert_awaited_once()


@pytest.mark.integration
class TestAnUnreachableProviderBooksNothing:
    """A provider that was never reached delivered nothing and charged
    nothing, so the ledger must stay exactly as it was. The connection
    test books its rows through a per-answer callback of its own — a
    separate arrangement from the vision endpoint's, and until now pinned
    by nothing: a refactor that wrote a row for the attempt itself would
    have shipped green."""

    def test_an_unreachable_provider_leaves_the_ledger_unchanged(
        self, db_session, test_household, client, auth_headers
    ):
        _cap_requests(db_session, test_household, 5)
        before = (
            db_session.query(AIUsageLog)
            .filter_by(organization_id=test_household.id)
            .count()
        )

        # The provider half replaced wholesale: the adapter translates a
        # refused connection into the one error the router maps to 400,
        # and the probe stage is never reached to book anything.
        list_models = AsyncMock(
            side_effect=RuntimeError(
                'Could not reach the model provider (ConnectError): refused'
            )
        )
        complete = AsyncMock()

        with _provider(list_models, complete):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.status_code == 400, response.text
        db_session.expire_all()
        after = (
            db_session.query(AIUsageLog)
            .filter_by(organization_id=test_household.id)
            .count()
        )
        assert after == before
        complete.assert_not_awaited()
