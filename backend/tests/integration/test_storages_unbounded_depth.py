"""Integration tests for a location tree without a depth ceiling (ADR-018).

Structure is described by ``parent_id`` alone. What a write still refuses is
about parents — a foreign organization, a cycle, a duplicate name among
siblings — never about how deep the node sits.
"""

import pytest
from fastapi import status


def _make(client, auth_headers, name, parent_id=None):
    """Create through the API, so the write path is the one under test.

    Building rows straight in the session would take the column default for
    any structural field and quietly miss whatever the service enforces.
    """
    payload = {'name': name}
    if parent_id is not None:
        payload['parent_id'] = str(parent_id)
    response = client.post('/api/v1/locations', headers=auth_headers, json=payload)
    assert response.status_code == status.HTTP_201_CREATED, (
        f'{name}: {response.status_code} {response.text}'
    )
    return response.json()['id']


def _chain(client, auth_headers, *names):
    """Create a parent chain and return every id, outermost first."""
    ids = []
    parent_id = None
    for name in names:
        parent_id = _make(client, auth_headers, name, parent_id)
        ids.append(parent_id)
    return ids


@pytest.mark.integration
class TestUnboundedDepth:
    """Depth is not a reason to refuse a write."""

    def test_create_under_a_node_that_already_has_children_succeeds(
        self, client, auth_headers
    ):
        """The old third level was the ceiling; there is no ceiling now."""
        _, _, shelf = _chain(client, auth_headers, 'Warehouse', 'Aisle 3', 'Rack B')

        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={'name': 'Shelf 2', 'parent_id': shelf},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['parent_id'] == shelf

    def test_chain_of_six_is_created_and_every_node_is_reachable(
        self, client, auth_headers
    ):
        parent_id = None
        created = []
        for name in ('Site', 'Building', 'Floor', 'Aisle', 'Rack', 'Shelf'):
            response = client.post(
                '/api/v1/locations',
                headers=auth_headers,
                json=(
                    {'name': name}
                    if parent_id is None
                    else {'name': name, 'parent_id': parent_id}
                ),
            )
            assert response.status_code == status.HTTP_201_CREATED, name
            parent_id = response.json()['id']
            created.append(parent_id)

        for storage_id in created:
            detail = client.get(f'/api/v1/locations/{storage_id}', headers=auth_headers)
            assert detail.status_code == status.HTTP_200_OK

    def test_response_no_longer_carries_a_declared_level(self, client, auth_headers):
        response = client.post(
            '/api/v1/locations', headers=auth_headers, json={'name': 'Receiving'}
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert 'level' not in response.json()

    def test_move_a_subtree_under_a_deep_node_succeeds(self, client, auth_headers):
        """The move that used to be refused for pushing descendants too deep."""
        _, _, rack = _chain(client, auth_headers, 'Warehouse', 'Aisle 3', 'Rack B')
        spare_root, spare_child = _chain(client, auth_headers, 'Overflow', 'Bin 1')

        response = client.put(
            f'/api/v1/locations/{spare_root}',
            headers=auth_headers,
            json={'parent_id': rack},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['parent_id'] == rack
        # The descendant travelled with it and is still reachable.
        child = client.get(f'/api/v1/locations/{spare_child}', headers=auth_headers)
        assert child.status_code == status.HTTP_200_OK
        assert child.json()['parent_id'] == spare_root

    def test_a_node_holding_items_may_also_hold_sublocations(
        self, client, auth_headers, test_item
    ):
        """Items are not restricted to leaves — freezing existing behaviour."""
        parent = _make(client, auth_headers, 'Cold Storage')

        moved = client.put(
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={'location_id': parent},
        )
        assert moved.status_code == status.HTTP_200_OK

        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={'name': 'Shelf A', 'parent_id': parent},
        )

        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.integration
class TestParentRulesSurvive:
    """Removing the ceiling removes nothing about parent integrity."""

    def test_move_under_own_descendant_returns_409(self, client, auth_headers):
        root, _, deep = _chain(client, auth_headers, 'Warehouse', 'Aisle 3', 'Rack B')

        response = client.put(
            f'/api/v1/locations/{root}',
            headers=auth_headers,
            json={'parent_id': deep},
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_move_under_itself_returns_400(self, client, auth_headers):
        node = _make(client, auth_headers, 'Receiving')

        response = client.put(
            f'/api/v1/locations/{node}',
            headers=auth_headers,
            json={'parent_id': node},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_duplicate_name_among_siblings_returns_409(self, client, auth_headers):
        parent = _make(client, auth_headers, 'Aisle 3')
        _make(client, auth_headers, 'Rack B', parent_id=parent)

        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={'name': 'Rack B', 'parent_id': parent},
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_same_name_under_different_parents_is_allowed(self, client, auth_headers):
        """ "Shelf 1" repeating in every rack is the normal case now."""
        rack_a = _make(client, auth_headers, 'Rack A')
        rack_b = _make(client, auth_headers, 'Rack B')
        _make(client, auth_headers, 'Shelf 1', parent_id=rack_a)

        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={'name': 'Shelf 1', 'parent_id': rack_b},
        )

        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.integration
class TestSubtreeCounts:
    """What is directly here, and what is anywhere below (ADR-018)."""

    def test_a_count_of_the_subtree_reaches_every_ancestor(
        self, client, auth_headers, test_item
    ):
        site, _aisle, _rack, shelf = _chain(
            client, auth_headers, 'Warehouse', 'Aisle 3', 'Rack B', 'Shelf 2'
        )
        moved = client.put(
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={'location_id': shelf},
        )
        assert moved.status_code == status.HTTP_200_OK

        listed = client.get('/api/v1/locations', headers=auth_headers).json()['items']
        by_id = {row['id']: row for row in listed}

        # Directly here: only the shelf holds it.
        assert by_id[shelf]['items_count'] == 1
        assert by_id[site]['items_count'] == 0
        # Below: every ancestor counts it, four levels up included.
        assert by_id[shelf]['subtree_items_count'] == 1
        assert by_id[site]['subtree_items_count'] == 1

    def test_the_tree_carries_the_same_two_numbers(
        self, client, auth_headers, test_item
    ):
        site, _aisle, shelf = _chain(
            client, auth_headers, 'Warehouse', 'Aisle 3', 'Rack B'
        )
        client.put(
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={'location_id': shelf},
        )

        tree = client.get('/api/v1/locations/tree', headers=auth_headers).json()
        root = next(node for node in tree if node['id'] == site)

        assert root['items_count'] == 0
        assert root['subtree_items_count'] == 1
