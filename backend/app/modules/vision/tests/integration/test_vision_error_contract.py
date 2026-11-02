"""Integration tests: what the client sees when the model lets us down.

Two failures used to arrive as the same HTTP 500 carrying a Python parser
message in English — ``Error during data extraction: Expecting value: line 1
column 1 (char 0)``. They are not the same failure, and neither string was
ever meant for the person holding the phone.
"""

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.modules.vision.tests.integration._llm_double import (
    answering,
    answering_without_connection,
    jpeg_bytes,
    never_reached,
    patch_client,
    ran_out_of_time,
    refused,
    unreachable,
)

_JPEG_BYTES = jpeg_bytes()

_PROSE = (
    'I can see a carton of milk, but the label text is too blurry for me '
    'to make out any of the details reliably.'
)


@pytest.mark.integration
class TestExtractContractFailure:
    def test_prose_instead_of_json_is_422(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(answering(_PROSE, _PROSE)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_the_parser_message_does_not_reach_the_client(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(answering(_PROSE, _PROSE)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        detail = response.json()['detail']['message']
        assert 'Expecting value' not in detail
        assert 'JSONDecodeError' not in detail
        assert 'blurry' not in detail

    def test_the_message_is_translated(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(answering(_PROSE, _PROSE)):
            response = client.post(
                '/api/v1/vision/extract',
                headers={**auth_headers, 'Accept-Language': 'pl'},
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert 'etykiety' in response.json()['detail']['message']

    def test_a_retry_that_lands_still_returns_200(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The second attempt is what the user gets — no error at all."""
        with patch_client(answering(_PROSE, '{"name": "Milk 2%"}')):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['name'] == 'Milk 2%'


@pytest.mark.integration
class TestNutritionContractFailure:
    def test_prose_instead_of_json_is_422(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(answering(_PROSE, _PROSE)):
            response = client.post(
                '/api/v1/vision/extract-nutrition',
                headers=auth_headers,
                files={'file': ('table.jpg', _JPEG_BYTES, 'image/jpeg')},
            )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'Expecting value' not in response.json()['detail']['message']

    def test_values_that_do_not_fit_the_schema_are_422(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        answer = '{"nova_group": "probably 3", "energy_kcal": "a lot"}'
        with patch_client(answering(answer, answer)):
            response = client.post(
                '/api/v1/vision/extract-nutrition',
                headers=auth_headers,
                files={'file': ('table.jpg', _JPEG_BYTES, 'image/jpeg')},
            )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'nova_group' not in response.json()['detail']['message']


@pytest.mark.integration
class TestContractFailureNamesTheConnection:
    """The 422 answer says *which* connection and model failed, never secrets."""

    def test_label_422_names_connection_and_model(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(answering(_PROSE, _PROSE)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert response.json()['detail']['code'] == 'VISION_LABEL_NOT_UNDERSTOOD'
        detail = response.json()['detail']['message']
        assert 'Label Reader' in detail
        assert 'gpt-4o-mini' in detail

    def test_nutrition_422_names_connection_and_model(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(answering(_PROSE, _PROSE)):
            response = client.post(
                '/api/v1/vision/extract-nutrition',
                headers=auth_headers,
                files={'file': ('table.jpg', _JPEG_BYTES, 'image/jpeg')},
            )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()['detail']['message']
        assert 'Label Reader' in detail
        assert 'gpt-4o-mini' in detail

    def test_422_does_not_leak_connection_secrets(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        fake = answering(_PROSE, _PROSE)
        fake.api_key_enc = 'sekret-key-do-not-leak'
        fake.api_base_url = 'https://secret.example.com'
        with patch_client(fake):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        detail = response.json()['detail']['message']
        assert 'sekret-key-do-not-leak' not in detail
        assert 'https://secret.example.com' not in detail

    def test_fallback_without_connection_has_no_placeholders(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(answering_without_connection(_PROSE, _PROSE)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()['detail']['message']
        assert '{name}' not in detail
        assert '{model}' not in detail
        assert 'Label Reader' not in detail
        # The placeholder-free twin is another wording, not another reason.
        assert response.json()['detail']['code'] == 'VISION_LABEL_NOT_UNDERSTOOD'


@pytest.mark.integration
class TestAFailureWithNoAnswerBehindIt:
    """A provider that never answered is not a model that answered badly."""

    def test_an_unexpected_failure_is_still_a_server_error(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Something we did not foresee stays a 500, and says nothing about
        its own internals."""
        with patch_client(unreachable(OSError('connection reset'))):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert 'connection reset' not in response.json()['detail']['message']

    def test_a_provider_that_could_not_be_reached_is_503(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """This is the 500 that took 1.3 seconds and said nothing: the call
        never got out, and the answer sent the photographer back to the
        camera for a problem the camera cannot fix."""
        with patch_client(never_reached()):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_it_names_the_connection_rather_than_the_photo(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(never_reached()):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        detail = response.json()['detail']['message']
        assert 'Label Reader' in detail
        assert 'ConnectError' not in detail

    def test_it_is_translated(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(never_reached()):
            response = client.post(
                '/api/v1/vision/extract',
                headers={**auth_headers, 'Accept-Language': 'pl'},
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert 'Nie udało się połączyć' in response.json()['detail']['message']


@pytest.mark.integration
class TestAModelThatRanOutOfTime:
    """Reached, and still thinking — the answer must not say otherwise.

    A local model is the answer to "I do not want my pantry photos leaving
    the house", and the person who chose it has slower hardware and a bigger
    context window than a data centre. Both push past a minute, and both used
    to be reported as a provider nobody could reach.
    """

    def test_it_does_not_tell_the_reader_the_provider_was_unreachable(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(ran_out_of_time()):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()['detail']['code'] == 'LLM_PROVIDER_TIMEOUT'
        detail = response.json()['detail']['message']
        assert 'Could not reach' not in detail
        assert 'did not answer in time' in detail
        assert 'Label Reader' in detail

    def test_it_says_what_to_change(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(ran_out_of_time()):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )

        assert (
            'LLM_LOCAL_REQUEST_TIMEOUT_SECONDS' in response.json()['detail']['message']
        )

    def test_it_is_translated(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(ran_out_of_time()):
            response = client.post(
                '/api/v1/vision/extract',
                headers={**auth_headers, 'Accept-Language': 'pl'},
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )

        assert 'nie odpowiedziało na czas' in response.json()['detail']['message']


@pytest.mark.integration
class TestTheModelAnsweredWithNothing:
    """An empty answer is not an unreadable label.

    The reader was told the AI could not read the photograph, twice twenty
    seconds apart, while the model had returned nothing at all — its whole
    token budget spent on reasoning it never got to finish.
    """

    def test_the_provider_is_asked_once(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        double = answering('', '{"name": "Milk"}')
        with patch_client(double):
            client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert double.complete.await_count == 1

    def test_the_answer_points_at_the_model_not_at_the_photo(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(answering('', '')):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()['detail']['message']
        assert 'no content' in detail
        assert 'clearer photo' not in detail


@pytest.mark.integration
class TestTheProviderRefusalNamesTheKey:
    """The most common first-setup state is a key the provider refuses.

    It used to reach the screen as HTTP 500 "An internal error occurred"
    while the log knew it was 401 — the administrator who had just pasted
    the key was pointed at the application instead of at the key. The
    provider saying no about the request is a configuration answer, and it
    arrives as one.
    """

    def test_a_rejected_key_is_named(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(refused(401)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        detail = response.json()['detail']['message']
        assert 'key' in detail.lower()
        assert 'internal error' not in detail.lower()
        # Which connection to look at, and no provider body in the answer.
        assert 'Label Reader' in detail
        assert 'invalid api key' not in detail

    def test_the_condition_is_translated(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(refused(401)):
            response = client.post(
                '/api/v1/vision/extract',
                headers={**auth_headers, 'Accept-Language': 'pl'},
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert 'klucz' in response.json()['detail']['message'].lower()

    def test_a_spent_limit_gets_its_own_sentence(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(refused(429)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        detail = response.json()['detail']['message']
        assert 'limit' in detail.lower()
        assert 'key' not in detail.lower()

    def test_an_unknown_model_gets_its_own_sentence(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(refused(404)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        detail = response.json()['detail']['message']
        assert 'model' in detail.lower()
        assert 'key' not in detail.lower()

    def test_a_provider_fault_stays_an_internal_error(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A 500 from the provider is an outage with nothing to configure —
        it must not borrow the named sentences or leak the provider body."""
        with patch_client(refused(500)):
            response = client.post(
                '/api/v1/vision/extract',
                headers=auth_headers,
                files={'images': ('label.jpg', _JPEG_BYTES, 'image/jpeg')},
                data={'location_type': 'PANTRY'},
            )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()['detail']['code'] == 'INTERNAL_ERROR'
        assert response.json()['detail']['message'] == 'An internal error occurred'

    def test_the_nutrition_path_answers_the_same_way(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        with patch_client(refused(401)):
            response = client.post(
                '/api/v1/vision/extract-nutrition',
                headers=auth_headers,
                files={'file': ('table.jpg', _JPEG_BYTES, 'image/jpeg')},
            )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert 'key' in response.json()['detail']['message'].lower()
