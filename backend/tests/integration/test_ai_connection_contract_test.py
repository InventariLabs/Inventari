"""Integration tests: the connection test checks the model, not just the key.

Listing models proves the credentials work. It says nothing about whether the
model can answer in the shape the app needs — which is exactly what breaks
after switching provider, and it breaks in the field rather than in Settings.
These tests pin the three verdicts the endpoint now distinguishes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.llm.base import LlmResponse
from app.core.llm.errors import LlmTimeoutError, LlmTransportError

pytestmark = pytest.mark.usefixtures('stub_dns')

_URL = '/api/v1/ai-connections/test'

_GOOD_ANSWER = (
    '{"name": "Oat Drink", "brand": "Barista Edition", '
    '"weight": "1 L", "expiry_date": "2027-01-31"}'
)
_PROSE = 'The image shows a carton, but I cannot make out the printed text.'

#: The shape is right and every value is from the ceiling. This is the answer
#: the test used to pass without comment.
_WELL_FORMED_GUESS = (
    '{"name": "Milk", "brand": null, "weight": null, "expiry_date": null}'
)


def _draft(**overrides: object) -> dict:
    body = {
        'provider': 'openrouter',
        'api_key': 'sk-or-fake',
        'api_base_url': 'https://openrouter.ai/api/v1',
        'model_name': 'some/model',
        'capabilities': ['vision', 'text'],
    }
    body.update(overrides)
    return body


def _answering(*contents: str):
    return patch(
        'app.core.llm.openai_client.OpenAiCompatibleClient.complete',
        new=AsyncMock(side_effect=[LlmResponse(content=c, usage={}) for c in contents]),
    )


def _models(*names: str):
    return patch(
        'app.core.llm.openai_client.OpenAiCompatibleClient.list_models',
        new=AsyncMock(return_value=list(names)),
    )


@pytest.mark.integration
class TestWhatTheModelRead:
    """A green verdict says the shape was right. It never said more."""

    def test_a_reading_travels_with_the_verdict(
        self, db_session, test_household, client, auth_headers
    ):
        with _models('some/model'), _answering(_GOOD_ANSWER):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        reading = response.json()['contract']['reading']
        # Three scored fields — the label establishes no maker, so the
        # brand in the answer is nobody's to miss.
        assert reading['matched'] == reading['of'] == 3
        assert reading['fields']['name']['expected'] == 'OAT DRINK'
        assert reading['fields']['name']['read'] == 'Oat Drink'

    def test_a_guess_in_the_right_shape_is_not_the_same_result_as_a_reading(
        self, db_session, test_household, client, auth_headers
    ):
        """The whole point: two green verdicts, two different readings.

        The model answered in the agreed shape, so the contract holds and the
        verdict stays ``ok`` — a date read as "31 January 2027" would be right
        in a way no equality test approves of, and failing on that would teach
        people to ignore the check. What separates this answer from a reading
        is the reading itself.
        """
        with _models('some/model'), _answering(_WELL_FORMED_GUESS):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        body = response.json()
        assert body['verdict'] == 'ok'
        assert body['contract']['ok'] is True

        reading = body['contract']['reading']
        assert reading['matched'] == 0
        assert reading['fields']['name']['read'] == 'Milk'
        assert reading['fields']['expiry_date']['read'] is None

    def test_an_off_contract_answer_carries_no_reading(
        self, db_session, test_household, client, auth_headers
    ):
        """Nothing parsed, so there is nothing to compare — and no pretence."""
        with _models('some/model'), _answering(_PROSE, _PROSE):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        contract = response.json()['contract']
        assert contract['ok'] is False
        assert 'reading' not in contract


@pytest.mark.integration
class TestVerdictOk:
    def test_a_model_that_delivers_gets_a_green_verdict(
        self, db_session, test_household, client, auth_headers
    ):
        with _models('some/model'), _answering(_GOOD_ANSWER):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['verdict'] == 'ok'
        assert body['contract']['ok'] is True
        assert body['contract']['purpose'] == 'vision.extract'
        assert body['contract']['attempts'] == 1

    def test_the_verdict_reports_that_the_shape_was_asked_for(
        self, db_session, test_household, client, auth_headers
    ):
        """Whether the request carried a schema is part of the verdict.

        It reports what the probe put on the wire, and the probe puts on the
        wire exactly what production does — so the answer moved from False to
        True when the extraction request started carrying the schema rendered
        from the caller\'s Pydantic model. Saying which it was is the
        difference between "this works" and "this worked once".
        """
        with _models('some/model'), _answering(_GOOD_ANSWER):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.json()['contract']['schema_enforced'] is True


@pytest.mark.integration
class TestVerdictContractFailed:
    def test_prose_instead_of_json_is_not_a_pass(
        self, db_session, test_household, client, auth_headers
    ):
        with _models('some/model'), _answering(_PROSE, _PROSE):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['verdict'] == 'contract_failed'
        assert body['contract']['ok'] is False
        assert body['contract']['attempts'] == 2

    def test_what_the_model_actually_returned_is_shown(
        self, db_session, test_household, client, auth_headers
    ):
        """The only part of the failure the user can do anything about."""
        with _models('some/model'), _answering(_PROSE, _PROSE):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert 'cannot make out' in response.json()['contract']['answer_preview']

    def test_a_rambling_answer_is_truncated(
        self, db_session, test_household, client, auth_headers
    ):
        rant = 'I am unable to comply with this request. ' * 100
        with _models('some/model'), _answering(rant, rant):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert len(response.json()['contract']['answer_preview']) < 500

    def test_a_retry_that_lands_still_passes(
        self, db_session, test_household, client, auth_headers
    ):
        with _models('some/model'), _answering(_PROSE, _GOOD_ANSWER):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        body = response.json()
        assert body['verdict'] == 'ok'
        assert body['contract']['attempts'] == 2


@pytest.mark.integration
class TestUsageAccounting:
    """The test is a real call. It is billed like one."""

    def test_the_probe_call_is_logged(
        self, db_session, test_household, client, auth_headers
    ):
        with (
            _models('some/model'),
            _answering(_GOOD_ANSWER),
            patch(
                'app.services.ai_usage_service.log_llm_usage_async',
                new_callable=AsyncMock,
            ) as logged,
        ):
            client.post(_URL, json=_draft(), headers=auth_headers)

        assert logged.await_count == 1
        assert logged.await_args.kwargs['action_type'] == 'connection_test'

    def test_a_retried_probe_is_logged_twice(
        self, db_session, test_household, client, auth_headers
    ):
        with (
            _models('some/model'),
            _answering(_PROSE, _GOOD_ANSWER),
            patch(
                'app.services.ai_usage_service.log_llm_usage_async',
                new_callable=AsyncMock,
            ) as logged,
        ):
            client.post(_URL, json=_draft(), headers=auth_headers)

        assert logged.await_count == 2


#: What the ingredient parser accepts: the agreed array, one object a line.
_GOOD_INGREDIENTS = (
    '{"ingredients": ['
    '{"name": "wheat flour", "group_name": "flour", "quantity": 200, '
    '"unit_text": "g", "unit_display": "g", "metric_quantity": 200, '
    '"metric_unit": "g", "original": "200 g wheat flour"}, '
    '{"name": "egg", "group_name": "egg", "quantity": 2, "unit_text": null, '
    '"unit_display": null, "metric_quantity": 2, "metric_unit": "pcs", '
    '"original": "2 eggs"}]}'
)


@pytest.mark.integration
class TestTextConnection:
    """A text connection is asked to parse ingredient lines, the job the
    recipe import gives it, and judged by the parser the import uses."""

    def test_a_model_that_parses_the_lines_passes_under_its_purpose(
        self, db_session, test_household, client, auth_headers
    ):
        with _models('some/model'), _answering(_GOOD_INGREDIENTS):
            response = client.post(
                _URL, json=_draft(capabilities=['text']), headers=auth_headers
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['verdict'] == 'ok'
        assert body['contract']['checked'] is True
        assert body['contract']['purpose'] == 'recipes.text_parse'
        assert body['contract']['schema_enforced'] is True

    @pytest.mark.parametrize(
        'answer',
        [
            'Here are your ingredients: flour, eggs and milk.',
            '{"ingredients": []}',
            '[{"quantity": 200, "metric_unit": "g"}]',
        ],
        ids=['prose', 'nothing-parsed', 'no-names'],
    )
    def test_an_answer_outside_the_agreed_shape_fails_the_contract(
        self, answer: str, db_session, test_household, client, auth_headers
    ):
        """The import would fall back to the basic parser on each of these;
        the test reports it instead of a pass."""
        with _models('some/model'), _answering(answer, answer):
            response = client.post(
                _URL, json=_draft(capabilities=['text']), headers=auth_headers
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['verdict'] == 'contract_failed'
        assert body['contract']['purpose'] == 'recipes.text_parse'
        assert body['contract']['attempts'] == 2


@pytest.mark.integration
class TestVerdictUnchecked:
    def test_no_declared_capabilities_means_no_probe(
        self, db_session, test_household, client, auth_headers
    ):
        with _models('some/model'):
            response = client.post(
                _URL, json=_draft(capabilities=[]), headers=auth_headers
            )

        assert response.json()['verdict'] == 'unchecked'


@pytest.mark.integration
class TestCredentialsVerdictStays400:
    def test_a_provider_that_never_answers_is_400(
        self, db_session, test_household, client, auth_headers
    ):
        with patch(
            'app.core.llm.openai_client.OpenAiCompatibleClient.list_models',
            new=AsyncMock(side_effect=RuntimeError('401 Unauthorized')),
        ):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.status_code == 400
        # The catalogue speaks the failure; the raw provider text is a log
        # line, not a form field (English on every screen, actionable in
        # none).
        assert 'could not be completed' in response.json()['detail']['message']
        assert '401' not in response.text

    def test_the_probe_never_runs_when_credentials_fail(
        self, db_session, test_household, client, auth_headers
    ):
        complete = AsyncMock()
        with (
            patch(
                'app.core.llm.openai_client.OpenAiCompatibleClient.list_models',
                new=AsyncMock(side_effect=RuntimeError('401 Unauthorized')),
            ),
            patch(
                'app.core.llm.openai_client.OpenAiCompatibleClient.complete',
                new=complete,
            ),
        ):
            client.post(_URL, json=_draft(), headers=auth_headers)

        complete.assert_not_awaited()


@pytest.mark.integration
class TestTheProbeThatRanOutOfTime:
    """A model that was still thinking is not a provider nobody could reach.

    A local runtime loads the model's weights on the first call after the
    model name changes, and that load happens inside the request the probe
    waits on. The first test of a working model used to come back as "the
    connection test could not be completed — check the address": an errand to
    an address that answered. The two failures are different errands, so they
    get different sentences.
    """

    def test_a_timed_out_probe_says_the_model_was_reached(
        self, db_session, test_household, client, auth_headers
    ):
        with (
            _models('some/model'),
            patch(
                'app.core.llm.openai_client.OpenAiCompatibleClient.complete',
                new=AsyncMock(
                    side_effect=LlmTimeoutError(
                        'The model did not answer within the time allowed '
                        '(ReadTimeout): timed out'
                    )
                ),
            ),
        ):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.status_code == 400, response.text
        assert response.json()['detail']['code'] == 'LLM_PROVIDER_TIMEOUT'
        detail = response.json()['detail']['message']
        assert 'did not answer in time' in detail
        assert 'was reached' in detail
        assert 'could not be completed' not in detail

    def test_a_connection_that_was_never_made_is_not_a_timeout(
        self, db_session, test_household, client, auth_headers
    ):
        """The other errand, pinned: an address, not a limit."""
        with patch(
            'app.core.llm.openai_client.OpenAiCompatibleClient.list_models',
            new=AsyncMock(
                side_effect=LlmTransportError(
                    'Could not reach the model provider (ConnectError): refused'
                )
            ),
        ):
            response = client.post(_URL, json=_draft(), headers=auth_headers)

        assert response.status_code == 400, response.text
        assert response.json()['detail']['code'] == 'LLM_PROVIDER_UNREACHABLE'
        detail = response.json()['detail']['message']
        assert 'Could not reach the AI provider' in detail
        assert 'did not answer in time' not in detail

    def test_a_stored_connection_is_named_in_the_sentence(
        self, db_session, test_household, client, auth_headers
    ):
        """Who to look at, not just what happened: the row knows both names."""
        created = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Shelf reader',
                'provider': 'openrouter',
                'api_key': 'sk-or-fake',
                'api_base_url': 'https://openrouter.ai/api/v1',
                'model_name': 'some/model',
                'capabilities': ['vision'],
            },
            headers=auth_headers,
        )
        assert created.status_code == 200, created.text

        with (
            _models('some/model'),
            patch(
                'app.core.llm.openai_client.OpenAiCompatibleClient.complete',
                new=AsyncMock(
                    side_effect=LlmTimeoutError(
                        'The model did not answer within the time allowed '
                        '(ReadTimeout): timed out',
                        # The client attaches both names in transport_failure;
                        # the router is what has to put them in the sentence.
                        connection_name='Shelf reader',
                        model_name='some/model',
                    )
                ),
            ),
        ):
            response = client.post(
                _URL,
                json={'connection_id': created.json()['id']},
                headers=auth_headers,
            )

        assert response.status_code == 400, response.text
        assert response.json()['detail']['code'] == 'LLM_PROVIDER_TIMEOUT'
        detail = response.json()['detail']['message']
        assert 'Shelf reader' in detail
        assert 'some/model' in detail
        assert 'did not answer in time' in detail


@pytest.mark.integration
class TestStoredConnection:
    def test_the_stored_row_decides_which_probe_runs(
        self, db_session, test_household, client, auth_headers
    ):
        created = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Probe target',
                'provider': 'openrouter',
                'api_key': 'sk-or-fake',
                'api_base_url': 'https://openrouter.ai/api/v1',
                'model_name': 'some/model',
                'capabilities': ['vision'],
            },
            headers=auth_headers,
        )
        assert created.status_code == 200, created.text

        with _models('some/model'), _answering(_GOOD_ANSWER):
            response = client.post(
                _URL,
                json={'connection_id': created.json()['id']},
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        assert response.json()['contract']['purpose'] == 'vision.extract'


@pytest.mark.integration
class TestTheVerdictLandsOnTheConnection:
    """A probe whose answer nobody keeps is a probe that was not run.

    The test asked the model to do the job, judged the reply, and told the
    toast. The card went on showing VISION as a fact, and the purpose picker
    went on offering the connection for reading photographs.
    """

    def _create(self, client, auth_headers, capabilities=('vision',)) -> str:
        created = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Probe target',
                'provider': 'openrouter',
                'api_key': 'sk-or-fake',
                'api_base_url': 'https://openrouter.ai/api/v1',
                'model_name': 'some/model',
                'capabilities': list(capabilities),
            },
            headers=auth_headers,
        )
        assert created.status_code == 200, created.text
        return created.json()['id']

    def _checks(self, client, auth_headers, conn_id: str) -> dict:
        listed = client.get('/api/v1/ai-connections', headers=auth_headers)
        assert listed.status_code == 200, listed.text
        row = next(c for c in listed.json()['items'] if c['id'] == conn_id)
        return row['capability_checks']

    def test_a_passed_probe_is_recorded_against_its_capability(
        self, db_session, test_household, client, auth_headers
    ):
        conn_id = self._create(client, auth_headers)

        with _models('some/model'), _answering(_GOOD_ANSWER):
            client.post(_URL, json={'connection_id': conn_id}, headers=auth_headers)

        checks = self._checks(client, auth_headers, conn_id)
        assert checks['vision']['ok'] is True
        assert checks['vision']['purpose'] == 'vision.extract'
        assert checks['vision']['at']

    def test_a_failed_probe_is_recorded_too(
        self, db_session, test_household, client, auth_headers
    ):
        """Otherwise the failure leaves no trace and the badge stays."""
        conn_id = self._create(client, auth_headers)

        with _models('some/model'), _answering(_PROSE, _PROSE):
            client.post(_URL, json={'connection_id': conn_id}, headers=auth_headers)

        checks = self._checks(client, auth_headers, conn_id)
        assert checks['vision']['ok'] is False

    def test_an_untested_connection_records_nothing(
        self, db_session, test_household, client, auth_headers
    ):
        """Never asked is its own state, and not the same as asked and failed."""
        conn_id = self._create(client, auth_headers)
        assert self._checks(client, auth_headers, conn_id) == {}

    def test_a_draft_has_no_row_to_write_to(
        self, db_session, test_household, client, auth_headers
    ):
        with _models('some/model'), _answering(_GOOD_ANSWER):
            response = client.post(_URL, json=_draft(), headers=auth_headers)
        assert response.status_code == 200, response.text


def _reader_page(status: int = 200, text: str = 'Example Domain'):
    """One answer from the reader service, fetched the way the import
    pipeline fetches: a status and a body, no models, no contract."""
    from unittest.mock import MagicMock

    response = MagicMock()
    response.status_code = status
    response.text = text
    http = AsyncMock()
    http.get = AsyncMock(return_value=response)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=http)
    session.__aexit__ = AsyncMock(return_value=False)
    return patch('httpx.AsyncClient', return_value=session)


@pytest.mark.integration
class TestAReaderConnection:
    """A reader credential is not a model: its test reads one page with the
    connection's key, the same call an import makes — so a key that passes
    here is a key an import can use, and one that does not fails in the
    registry instead of on the first recipe."""

    def test_one_page_read_records_the_capability(
        self, db_session, test_household, client, auth_headers
    ):
        created = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Jina Reader',
                'provider': 'jina',
                'api_key': 'jina-reader-key',
                'capabilities': ['url_fetch'],
            },
            headers=auth_headers,
        )
        assert created.status_code == 200, created.text
        conn_id = created.json()['id']

        with _reader_page():
            response = client.post(
                _URL, json={'connection_id': conn_id}, headers=auth_headers
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['verdict'] == 'ok'
        assert body['contract']['purpose'] == 'recipes.url_fetch'
        listed = client.get('/api/v1/ai-connections', headers=auth_headers)
        row = next(c for c in listed.json()['items'] if c['id'] == conn_id)
        assert row['capability_checks']['url_fetch']['ok'] is True
        assert row['capability_checks']['url_fetch']['purpose'] == 'recipes.url_fetch'

    def test_a_key_the_reader_refuses_is_a_400(
        self, db_session, test_household, client, auth_headers
    ):
        created = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Jina Reader',
                'provider': 'jina',
                'api_key': 'rotated-away',
                'capabilities': ['url_fetch'],
            },
            headers=auth_headers,
        )
        assert created.status_code == 200, created.text

        with _reader_page(status=401, text=''):
            response = client.post(
                _URL,
                json={'connection_id': created.json()['id']},
                headers=auth_headers,
            )

        assert response.status_code == 400, response.text
        # The specific sentence goes to the log, like every stage-one
        # credentials failure — the reader sees the same refusal shape.
        assert 'could not be completed' in response.text.lower()

    def test_a_keyless_connection_is_the_free_tier_and_says_so(
        self, db_session, test_household, client, auth_headers
    ):
        """No key is a legal state with nothing to test: the answer names
        it instead of spending a request against the shared rate limit."""
        created = client.post(
            '/api/v1/ai-connections',
            json={
                'name': 'Jina Reader',
                'provider': 'jina',
                'capabilities': ['url_fetch'],
            },
            headers=auth_headers,
        )
        assert created.status_code == 200, created.text

        with _reader_page():
            response = client.post(
                _URL,
                json={'connection_id': created.json()['id']},
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['verdict'] == 'unchecked'
        assert body['contract']['reason'] == 'no_key_free_tier'
