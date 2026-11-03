"""A page of locations costs what the page holds.

The list used to read every location of the organization, count the records
in every one of them and slice the answer, so each request paid for the whole
warehouse and a screen that wanted twenty places downloaded them all, page by
page. These are the asks that replace it: search, naming a set of ids, one
level of the tree, and a count that is skipped when nobody prints it.
"""

from uuid import uuid4

import pytest
from fastapi import status

from app.models.item import Item
from app.models.storage_location import StorageLocation


@pytest.fixture
def warehouse(db_session, test_user):
    """One warehouse, two zones, three shelves; two records on the first shelf."""

    def place(name, parent=None, **extra):
        row = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name=name,
            parent_id=parent.id if parent else None,
            **extra,
        )
        db_session.add(row)
        db_session.flush()
        return row

    root = place('Main warehouse')
    zone_a = place('Zone A', root)
    zone_b = place('Zone B', root)
    shelf_1 = place('Shelf 1', zone_a, sequence=2)
    shelf_2 = place('Shelf 2', zone_a, sequence=1)
    shelf_3 = place('Shelf 3', zone_b)
    for index in range(2):
        db_session.add(
            Item(
                organization_id=test_user.organization_id,
                storage_location_id=shelf_1.id,
                name=f'Milk {index}',
                quantity=1,
            )
        )
    db_session.commit()
    return {
        'root': root,
        'zone_a': zone_a,
        'zone_b': zone_b,
        'shelf_1': shelf_1,
        'shelf_2': shelf_2,
        'shelf_3': shelf_3,
    }


def _names(response) -> list[str]:
    assert response.status_code == status.HTTP_200_OK, response.text
    return [row['name'] for row in response.json()['items']]


@pytest.mark.integration
class TestTheListIsPagedInTheDatabase:
    def test_a_page_says_how_many_match_in_all(self, client, auth_headers, warehouse):
        response = client.get(
            '/api/v1/locations?limit=2&offset=0', headers=auth_headers
        )

        body = response.json()
        assert len(body['items']) == 2
        assert body['total'] == 6
        assert body['has_more'] is True

    def test_the_pages_walk_the_list_once_in_walk_order(
        self, client, auth_headers, warehouse
    ):
        names = []
        for offset in range(0, 6, 2):
            names += _names(
                client.get(
                    f'/api/v1/locations?limit=2&offset={offset}', headers=auth_headers
                )
            )

        # The walk order each place records comes first, the name after it:
        # Shelf 2 (1) and Shelf 1 (2) lead; the rest follow by name.
        assert names == [
            'Shelf 2',
            'Shelf 1',
            'Main warehouse',
            'Shelf 3',
            'Zone A',
            'Zone B',
        ]

    def test_a_search_finds_a_place_by_name_or_by_where_it_stands(
        self, client, auth_headers, warehouse
    ):
        by_name = client.get('/api/v1/locations?q=shelf 3', headers=auth_headers)
        by_path = client.get('/api/v1/locations?q=zone a', headers=auth_headers)

        assert _names(by_name) == ['Shelf 3']
        # The zone itself and what stands inside it: a path is part of the name.
        assert sorted(_names(by_path)) == ['Shelf 1', 'Shelf 2', 'Zone A']

    def test_a_place_typed_in_full_comes_before_what_matches_through_its_path(
        self, client, auth_headers, warehouse
    ):
        # Every place of the warehouse matches its name through the path, and
        # the shelves with a sequence walk ahead of it: a page of one must
        # still be the warehouse, or a picker with a page of thirty never
        # offers a warehouse whose name is typed out.
        page = client.get(
            '/api/v1/locations?q=main warehouse&limit=1', headers=auth_headers
        )

        assert _names(page) == ['Main warehouse']
        assert page.json()['total'] == 6

    def test_ids_name_exactly_those_places(self, client, auth_headers, warehouse):
        wanted = [warehouse['shelf_3'].id, warehouse['zone_b'].id]
        query = '&'.join(f'ids={i}' for i in wanted)

        response = client.get(f'/api/v1/locations?{query}', headers=auth_headers)

        assert sorted(_names(response)) == ['Shelf 3', 'Zone B']
        shelf = next(r for r in response.json()['items'] if r['name'] == 'Shelf 3')
        assert shelf['full_path'] == 'Main warehouse › Zone B › Shelf 3'

    def test_the_children_of_one_place_and_the_top_of_the_tree(
        self, client, auth_headers, warehouse
    ):
        children = client.get(
            f'/api/v1/locations?parent_id={warehouse["zone_a"].id}',
            headers=auth_headers,
        )
        top = client.get('/api/v1/locations?top_level=true', headers=auth_headers)

        assert sorted(_names(children)) == ['Shelf 1', 'Shelf 2']
        assert _names(top) == ['Main warehouse']

    def test_under_keeps_only_what_lies_inside_a_zone_at_any_depth(
        self, client, auth_headers, warehouse
    ):
        wanted = [
            warehouse['shelf_1'].id,
            warehouse['shelf_3'].id,
            warehouse['zone_a'].id,
        ]
        query = '&'.join(f'ids={i}' for i in wanted)

        response = client.get(
            f'/api/v1/locations?under={warehouse["zone_a"].id}&{query}',
            headers=auth_headers,
        )
        from_root = client.get(
            f'/api/v1/locations?under={warehouse["root"].id}&limit=200',
            headers=auth_headers,
        )

        # The zone is not inside itself, and Shelf 3 stands in the other zone.
        assert _names(response) == ['Shelf 1']
        assert len(_names(from_root)) == 5

    def test_a_place_of_another_organization_is_never_named(
        self, client, auth_headers, warehouse, db_session, test_user
    ):
        from app.models.organization import Organization

        stranger = Organization(name='Somebody else')
        db_session.add(stranger)
        db_session.flush()
        foreign = StorageLocation(
            organization_id=stranger.id, created_by=test_user.id, name='Foreign shelf'
        )
        db_session.add(foreign)
        db_session.commit()

        response = client.get(
            f'/api/v1/locations?ids={foreign.id}', headers=auth_headers
        )

        assert _names(response) == []


@pytest.mark.integration
class TestTheCountsFollowThePage:
    def test_a_page_counts_its_own_rows_and_what_stands_below_them(
        self, client, auth_headers, warehouse
    ):
        response = client.get(
            f'/api/v1/locations?ids={warehouse["zone_a"].id}&ids={warehouse["shelf_1"].id}',
            headers=auth_headers,
        )

        rows = {r['name']: r for r in response.json()['items']}
        assert rows['Shelf 1']['items_count'] == 2
        assert rows['Zone A']['items_count'] == 0
        assert rows['Zone A']['subtree_items_count'] == 2
        assert rows['Zone A']['total_subtree_items_count'] == 2
        assert rows['Zone A']['direct_children_count'] == 2
        assert rows['Zone A']['listed_children_count'] == 2

    def test_a_child_the_list_hides_still_moves_and_is_told_apart(
        self, client, auth_headers, warehouse, db_session
    ):
        # A delete lifts the archived child as well, so it stays in the
        # number of children that move; the listing says how many of them
        # it shows, so the question can tell the reader the rest are hidden.
        warehouse['shelf_2'].settings = {'archived': True}
        db_session.commit()

        response = client.get(
            f'/api/v1/locations?ids={warehouse["zone_a"].id}', headers=auth_headers
        )

        row = response.json()['items'][0]
        assert row['direct_children_count'] == 2
        assert row['listed_children_count'] == 1

    def test_a_picker_that_prints_no_number_skips_the_counting(
        self, client, auth_headers, warehouse
    ):
        response = client.get(
            '/api/v1/locations?counts=false&ids=' + str(warehouse['shelf_1'].id),
            headers=auth_headers,
        )

        row = response.json()['items'][0]
        assert row['items_count'] == 0
        assert row['subtree_items_count'] == 0
        # What is not a count is still there: the place knows its path.
        assert row['full_path'] == 'Main warehouse › Zone A › Shelf 1'
        assert row['is_leaf'] is True


@pytest.mark.integration
class TestTheTreeAnswersOneLevel:
    def test_the_roots_alone(self, client, auth_headers, warehouse):
        response = client.get('/api/v1/locations/tree?depth=1', headers=auth_headers)

        nodes = response.json()
        assert [n['name'] for n in nodes] == ['Main warehouse']
        assert nodes[0]['children'] == []
        assert nodes[0]['children_count'] == 2
        assert nodes[0]['subtree_items_count'] == 2

    def test_the_levels_below_a_place(self, client, auth_headers, warehouse):
        response = client.get(
            f'/api/v1/locations/tree?parent_id={warehouse["root"].id}',
            headers=auth_headers,
        )

        nodes = {n['name']: n for n in response.json()}
        assert sorted(nodes) == ['Zone A', 'Zone B']
        assert nodes['Zone A']['children'] == []
        assert nodes['Zone A']['children_count'] == 2
        assert nodes['Zone A']['subtree_items_count'] == 2

    def test_a_deeper_ask_keeps_the_levels_it_names(
        self, client, auth_headers, warehouse
    ):
        response = client.get(
            f'/api/v1/locations/tree?parent_id={warehouse["root"].id}&depth=2',
            headers=auth_headers,
        )

        zone_a = next(n for n in response.json() if n['name'] == 'Zone A')
        assert sorted(c['name'] for c in zone_a['children']) == ['Shelf 1', 'Shelf 2']
        assert zone_a['children'][0]['children'] == []

    def test_a_level_without_counts_reads_zero(self, client, auth_headers, warehouse):
        response = client.get(
            '/api/v1/locations/tree?depth=1&counts=false', headers=auth_headers
        )

        assert response.json()[0]['subtree_items_count'] == 0

    def test_without_depth_the_whole_tree_still_comes_back(
        self, client, auth_headers, warehouse
    ):
        response = client.get('/api/v1/locations/tree', headers=auth_headers)

        root = response.json()[0]
        assert sorted(c['name'] for c in root['children']) == ['Zone A', 'Zone B']


@pytest.mark.integration
class TestTheListNarrowsByType:
    def test_only_the_places_of_the_asked_types(
        self, client, auth_headers, warehouse, db_session, test_storage_type
    ):
        warehouse['shelf_3'].storage_type_id = test_storage_type.id
        db_session.commit()

        typed = client.get(
            f'/api/v1/locations?type_ids={test_storage_type.id}&counts=false',
            headers=auth_headers,
        )
        none_of_them = client.get(
            f'/api/v1/locations?type_ids={uuid4()}&counts=false',
            headers=auth_headers,
        )

        assert _names(typed) == ['Shelf 3']
        assert _names(none_of_them) == []


@pytest.mark.integration
class TestTheListNarrowsToPlacesWithFields:
    def test_only_the_places_that_set_fields_of_their_own(
        self, client, auth_headers, warehouse, db_session
    ):
        warehouse['zone_a'].field_definitions = [
            {'key': 'aisle', 'type': 'text', 'required': False}
        ]
        db_session.commit()

        response = client.get(
            '/api/v1/locations?with_fields=true&counts=false', headers=auth_headers
        )

        assert _names(response) == ['Zone A']
