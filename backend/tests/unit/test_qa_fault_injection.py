"""The error state has to be reachable on purpose, and unreachable by accident.

Two halves, and the second matters more: a middleware that can turn any request
into a failure is a switch, and a switch that a cookie alone can flip is an
outage anybody can cause. It is registered only when QA_FAULT_INJECTION and
DEBUG are both on; these cases pin what it does once it is, and what it leaves
alone.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.qa_fault_injection import FaultInjectionMiddleware


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.get('/api/v1/items')
    def items():
        return {'items': []}

    @app.get('/api/v1/locations')
    def storages():
        return {'storages': []}

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    app.add_middleware(FaultInjectionMiddleware)
    return TestClient(app)


@pytest.mark.unit
class TestTheCookieFails:
    def test_a_status_code_comes_back_as_asked(self, client):
        client.cookies.set('qa_fail', '500')

        response = client.get('/api/v1/items')

        assert response.status_code == 500
        assert response.headers['x-qa-fault-injection'] == '1'
        assert response.json()['error'] == 'qa_fault_injection'

    def test_the_body_says_how_to_stop_it(self, client):
        # A screenshot of an injected 500 must be tellable from a real one.
        client.cookies.set('qa_fail', '503')

        detail = client.get('/api/v1/items').json()['detail']

        assert 'qa_fail' in detail
        assert 'Clear it' in detail

    def test_one_endpoint_can_be_singled_out(self, client):
        # Failing everything answers "the app is down", not "this screen
        # handles a failure".
        client.cookies.set('qa_fail', '500')
        client.cookies.set('qa_fail_path', '/api/v1/items')

        assert client.get('/api/v1/items').status_code == 500
        assert client.get('/api/v1/locations').status_code == 200


@pytest.mark.unit
class TestItLeavesEverythingElseAlone:
    def test_without_the_cookie_nothing_changes(self, client):
        response = client.get('/api/v1/items')

        assert response.status_code == 200
        assert 'x-qa-fault-injection' not in response.headers

    def test_a_status_outside_the_error_range_is_ignored(self, client):
        # Otherwise the cookie could forge a 200 or a redirect, which is a
        # different and much worse tool than the one being built.
        client.cookies.set('qa_fail', '200')

        assert client.get('/api/v1/items').status_code == 200

    def test_nonsense_is_ignored(self, client):
        client.cookies.set('qa_fail', 'yes')

        assert client.get('/api/v1/items').status_code == 200

    def test_the_document_request_is_never_failed(self, client):
        # Failing it would replace the screen under test with the browser's
        # own error page.
        client.cookies.set('qa_fail', '500')

        assert client.get('/health').status_code == 200
