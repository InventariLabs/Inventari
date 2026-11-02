"""The shopping-list reads answer with the documented page envelope."""

import pytest
from fastapi import status
from starlette.testclient import TestClient


def _create_list(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post(
        '/api/v1/shopping-lists', headers=headers, json={'name': name}
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return str(response.json()['id'])


@pytest.mark.integration
class TestShoppingListsAnswerWithAPage:
    def test_the_lists_page_counts_every_list_not_only_the_page(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        for name in ('A', 'B', 'C'):
            _create_list(client, auth_headers, name)

        first = client.get(
            '/api/v1/shopping-lists',
            headers=auth_headers,
            params={'limit': 2, 'offset': 0},
        ).json()
        second = client.get(
            '/api/v1/shopping-lists',
            headers=auth_headers,
            params={'limit': 2, 'offset': 2},
        ).json()

        assert (len(first['items']), first['total'], first['has_more']) == (2, 3, True)
        assert (len(second['items']), second['total'], second['has_more']) == (
            1,
            3,
            False,
        )
        assert not {i['id'] for i in first['items']} & {
            i['id'] for i in second['items']
        }

    def test_the_items_page_slices_the_list_it_reads(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        list_id = _create_list(client, auth_headers, 'Items')
        for name in ('Milk', 'Eggs', 'Rice'):
            added = client.post(
                f'/api/v1/shopping-lists/{list_id}/items',
                headers=auth_headers,
                json={'name': name, 'quantity': '1'},
            )
            assert added.status_code == status.HTTP_201_CREATED, added.text

        page = client.get(
            f'/api/v1/shopping-lists/{list_id}/items',
            headers=auth_headers,
            params={'limit': 2},
        ).json()

        assert (len(page['items']), page['total'], page['has_more']) == (2, 3, True)
