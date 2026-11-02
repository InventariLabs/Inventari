"""This module is the template; its defects are copied, not contained.

``cli/module_generator.py`` copies this module when somebody scaffolds a new
one, so whatever it does becomes what the next module does. That makes an
ordinary oversight here a different kind of thing: pagination bounds nobody
declared, a docstring describing a pattern the file does not follow.

The tests below pin the parts a copy would inherit.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

_LIST = '/api/v1/example-widgets'


class TestPaginationSaysItsOwnBounds:
    @pytest.mark.parametrize('query', ['offset=-1', 'limit=-5', 'limit=0'])
    def test_a_nonsense_page_is_refused_by_the_schema(
        self, client: TestClient, widget_auth: dict[str, str], query: str
    ) -> None:
        """Unbounded, a negative offset reached Postgres and came back a 500."""
        response = client.get(f'{_LIST}?{query}', headers=widget_auth)
        assert response.status_code == 422, response.text

    def test_an_ordinary_page_still_works(
        self, client: TestClient, widget_auth: dict[str, str]
    ) -> None:
        response = client.get(f'{_LIST}?limit=10&offset=0', headers=widget_auth)
        assert response.status_code == 200, response.text

    def test_a_page_larger_than_the_ceiling_is_refused(
        self, client: TestClient, widget_auth: dict[str, str]
    ) -> None:
        """A copy inherits the ceiling too, which is the point of having one."""
        response = client.get(f'{_LIST}?limit=100000', headers=widget_auth)
        assert response.status_code == 422, response.text


class TestTheListAnswersWithTheEnvelope:
    """A bare JSON array cannot be paged, and the list-envelope lint refuses
    one — so a copy of a bare-list route failed its author's first commit."""

    def test_a_page_says_how_many_there_are_and_whether_more_follow(
        self, client: TestClient, widget_auth: dict[str, str]
    ) -> None:
        for name in ('First', 'Second', 'Third'):
            created = client.post(_LIST, json={'name': name}, headers=widget_auth)
            assert created.status_code == 201, created.text

        first = client.get(f'{_LIST}?limit=2&offset=0', headers=widget_auth)
        assert first.status_code == 200, first.text
        page = first.json()
        assert len(page['items']) == 2
        assert (page['total'], page['limit'], page['offset']) == (3, 2, 0)
        assert page['has_more'] is True

        last = client.get(f'{_LIST}?limit=2&offset=2', headers=widget_auth).json()
        assert len(last['items']) == 1
        assert last['total'] == 3
        assert last['has_more'] is False
