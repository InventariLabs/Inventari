"""The tree and the flat list describe the same locations.

``context_tag`` is not decoration: the schema documents it as module scoping,
where ``NULL`` means universal. So a tree that leaves it at the default says
of every location that it belongs to no module -- and says it about the
locations that do. A consumer trusting the tree filters the wrong set; the
storage screen only escapes it by asking the server to filter instead, and
the comment above that request records what happened the last time the two
sides disagreed.
"""

import pytest
from fastapi import status


def _location(client, auth_headers, name: str, **extra):
    response = client.post(
        '/api/v1/locations',
        headers=auth_headers,
        json={'name': name, **extra},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()


def _flatten(nodes: list[dict]) -> list[dict]:
    return [
        node for row in nodes for node in [row, *_flatten(row.get('children') or [])]
    ]


def _tags_by_name(rows: list[dict]) -> dict[str, str | None]:
    return {row['name']: row.get('context_tag') for row in rows}


@pytest.mark.integration
class TestTheTreeCarriesTheModuleTag:
    """GET /locations/tree against GET /locations."""

    def test_a_tagged_location_is_tagged_in_the_tree_too(self, client, auth_headers):
        _location(client, auth_headers, 'Server Room', context_tag='equipment')

        tree = client.get('/api/v1/locations/tree', headers=auth_headers)

        assert tree.status_code == status.HTTP_200_OK
        assert _tags_by_name(_flatten(tree.json()))['Server Room'] == 'equipment'

    def test_both_endpoints_agree_on_every_location(self, client, auth_headers):
        # Three shapes at once: a tagged root, an untagged root, and a tagged
        # child -- the last one because the tree builds children on a
        # different pass than roots.
        _location(client, auth_headers, 'Server Room', context_tag='equipment')
        cooler = _location(client, auth_headers, 'Walk-in Cooler')
        _location(
            client,
            auth_headers,
            'Rack 3',
            parent_id=cooler['id'],
            context_tag='equipment',
        )

        flat = client.get('/api/v1/locations', headers=auth_headers)
        tree = client.get('/api/v1/locations/tree', headers=auth_headers)

        assert flat.status_code == status.HTTP_200_OK
        assert tree.status_code == status.HTTP_200_OK
        from_tree = _tags_by_name(_flatten(tree.json()))
        from_list = _tags_by_name(flat.json()['items'])
        assert from_tree == from_list
        # The assertion above passes on two empty dicts, and it passes if both
        # sides go null together; neither is the thing under test.
        assert from_tree['Server Room'] == 'equipment'
        assert from_tree['Rack 3'] == 'equipment'
        assert from_tree['Walk-in Cooler'] is None
