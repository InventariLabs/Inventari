"""A module's own screen asks for its own locations.

The equipment locations screen is called "Equipment Locations" and used to
list every location the organization has, with Edit and Delete on each row —
so an IT manager was offered the deletion of a walk-in cooler from the
equipment screen.

Filtering on ``context_tag`` alone is not the answer: an asset can stand in
an untagged location, and a filter that drops those drops the places where
equipment actually is. So the scope is the union — locations tagged for the
module, plus locations holding its records.
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


def _names(response) -> set[str]:
    return {row['name'] for row in response.json()['items']}


def _shelf_of(client, auth_headers) -> dict:
    response = client.get(
        '/api/v1/locations', headers=auth_headers, params={'search': 'Shelf'}
    )
    assert response.status_code == status.HTTP_200_OK
    for row in response.json()['items']:
        if row['name'] == 'Shelf':
            return row
    raise AssertionError('Shelf not found')


@pytest.mark.integration
class TestStorageModuleScope:
    """``module_scope`` on GET /locations."""

    def test_scope_keeps_the_tagged_locations(self, client, auth_headers):
        _location(client, auth_headers, 'Server Room', context_tag='equipment')
        _location(client, auth_headers, 'Walk-in Cooler')

        response = client.get(
            '/api/v1/locations?module_scope=equipment', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        names = _names(response)
        assert 'Server Room' in names
        assert 'Walk-in Cooler' not in names

    def test_scope_keeps_an_untagged_location_holding_the_module_s_records(
        self, client, auth_headers
    ):
        # The case a context_tag filter alone would lose: the asset is real
        # and it is standing here.
        desk = _location(client, auth_headers, 'Desk 14')
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'ThinkPad T14',
                'quantity': 1,
                'location_id': desk['id'],
                'metadata': {'equipment': {'asset_tag': 'IT-0042'}},
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        response = client.get(
            '/api/v1/locations?module_scope=equipment', headers=auth_headers
        )

        assert 'Desk 14' in _names(response)

    def test_a_location_holding_someone_else_s_records_stays_out(
        self, client, auth_headers
    ):
        shelf = _location(client, auth_headers, 'Beverage Rack 2')
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Sparkling water',
                'quantity': 24,
                'location_id': shelf['id'],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        response = client.get(
            '/api/v1/locations?module_scope=equipment', headers=auth_headers
        )

        assert 'Beverage Rack 2' not in _names(response)

    def test_without_the_parameter_nothing_narrows(self, client, auth_headers):
        _location(client, auth_headers, 'Server Room', context_tag='equipment')
        _location(client, auth_headers, 'Walk-in Cooler')

        response = client.get('/api/v1/locations', headers=auth_headers)

        names = _names(response)
        assert {'Server Room', 'Walk-in Cooler'} <= names

    def test_an_unknown_module_narrows_to_nothing_rather_than_everything(
        self, client, auth_headers
    ):
        # A typo in the parameter must not quietly hand back the whole
        # organization — that is the failure this screen started from.
        _location(client, auth_headers, 'Server Room', context_tag='equipment')

        response = client.get(
            '/api/v1/locations?module_scope=nosuchmodule', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert _names(response) == set()


@pytest.mark.integration
class TestContextTagInheritance:
    """A location filed under a module's location carries the module's tag.

    An empty tag is filled from the parent at write time; a tag the node
    already carries is never rewritten by a move. Without the rule the child
    stayed on the general lists its parent dropped out of — a card with no
    path and an edit sheet claiming "No parent storage".
    """

    def test_create_under_a_tagged_parent_inherits_the_tag(self, client, auth_headers):
        room = _location(client, auth_headers, 'Server Room', context_tag='equipment')

        shelf = _location(client, auth_headers, 'Shelf A', parent_id=room['id'])

        assert shelf['context_tag'] == 'equipment'

    def test_an_explicit_tag_on_the_child_wins(self, client, auth_headers):
        room = _location(client, auth_headers, 'Server Room', context_tag='equipment')

        shelf = _location(
            client,
            auth_headers,
            'Reading Nook',
            parent_id=room['id'],
            context_tag='library',
        )

        assert shelf['context_tag'] == 'library'

    def test_a_move_into_a_module_subtree_inherits_the_tag(self, client, auth_headers):
        room = _location(client, auth_headers, 'Server Room', context_tag='equipment')
        shelf = _location(client, auth_headers, 'Spare Shelf')

        moved = client.put(
            f'/api/v1/locations/{shelf["id"]}',
            headers=auth_headers,
            json={'parent_id': room['id']},
        )

        assert moved.status_code == status.HTTP_200_OK, moved.text
        assert moved.json()['context_tag'] == 'equipment'

    def test_a_move_never_rewrites_a_tag_the_node_carries(self, client, auth_headers):
        room = _location(client, auth_headers, 'Server Room', context_tag='equipment')
        nook = _location(client, auth_headers, 'Reading Nook', context_tag='library')

        moved = client.put(
            f'/api/v1/locations/{nook["id"]}',
            headers=auth_headers,
            json={'parent_id': room['id']},
        )

        assert moved.status_code == status.HTTP_200_OK, moved.text
        assert moved.json()['context_tag'] == 'library'

    def test_a_move_out_to_the_root_keeps_the_tag(self, client, auth_headers):
        room = _location(client, auth_headers, 'Server Room', context_tag='equipment')
        shelf = _location(client, auth_headers, 'Shelf A', parent_id=room['id'])
        assert shelf['context_tag'] == 'equipment'

        moved = client.put(
            f'/api/v1/locations/{shelf["id"]}',
            headers=auth_headers,
            json={'parent_id': None},
        )

        assert moved.status_code == status.HTTP_200_OK, moved.text
        assert moved.json()['context_tag'] == 'equipment'

    def test_a_child_without_the_tag_says_where_it_lives(
        self, client, auth_headers, db_session, test_user
    ):
        """Pre-rule data: an untagged child of a tagged parent still gets its
        true path — naming is not offering, so the scoped list backfills the
        filtered-out ancestor into the name chain, never into the result set.
        """
        from app.models.storage_location import StorageLocation

        room = _location(client, auth_headers, 'Server Room', context_tag='equipment')
        orphan = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='QA Shelf B8',
            parent_id=room['id'],
            usage='internal',
        )
        db_session.add(orphan)
        db_session.commit()

        scoped = client.get(
            '/api/v1/locations?exclude_module_contexts=true', headers=auth_headers
        ).json()['items']

        rows = {row['name']: row for row in scoped}
        assert 'Server Room' not in rows
        assert rows['QA Shelf B8']['full_path'] == 'Server Room › QA Shelf B8'


@pytest.mark.integration
class TestTheCountsOnAScopedListing:
    """The number under a location's name answers for what the screen lists.

    ``module_scope`` already narrowed which locations appear, but the counts
    under each name kept counting every module's records — an IT manager
    reading "81 records" under "Office Building" was reading the
    organization's groceries. The scoped counts speak for the module; the
    deletion guard answers for records standing directly in the location
    regardless of owner, so that number travels alongside as
    ``total_items_count``.
    """

    def _stock(self, client, auth_headers):
        building = _location(client, auth_headers, 'Office Building')
        rack = _location(
            client, auth_headers, 'Server Rack A', parent_id=building['id']
        )
        self._building_id = building['id']
        records = [
            ('ThinkPad T14', building, True),
            ('Meeting-room monitor', building, True),
            ('Sparkling water', building, False),
            ('Spare laptop', rack, True),
            ('Flour', rack, False),
            ('Rice', rack, False),
        ]
        for name, place, is_equipment in records:
            payload = {
                'name': name,
                'quantity': 1,
                'location_id': place['id'],
            }
            if is_equipment:
                payload['metadata'] = {'equipment': {'asset_tag': name}}
            created = client.post('/api/v1/items', headers=auth_headers, json=payload)
            assert created.status_code == status.HTTP_201_CREATED, created.text
        return building, rack

    def _rows(self, client, auth_headers, query: str) -> dict:
        response = client.get(f'/api/v1/locations{query}', headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK, response.text
        return {row['name']: row for row in response.json()['items']}

    def test_the_counts_speak_for_the_module(self, client, auth_headers):
        self._stock(client, auth_headers)

        rows = self._rows(client, auth_headers, '?module_scope=equipment')

        assert rows['Office Building']['items_count'] == 2
        assert rows['Office Building']['subtree_items_count'] == 3
        assert rows['Server Rack A']['items_count'] == 1
        assert rows['Server Rack A']['subtree_items_count'] == 1

    def test_the_total_counts_every_module_s_record_standing_here(
        self, client, auth_headers
    ):
        self._stock(client, auth_headers)

        rows = self._rows(client, auth_headers, '?module_scope=equipment')

        # The server refuses to delete a location while any module's record
        # stands directly in it — so the number the delete button answers to
        # counts every one of them, here: two records of no module in the
        # building, two in the rack.
        assert rows['Office Building']['total_items_count'] == 3
        assert rows['Server Rack A']['total_items_count'] == 3

    def test_the_delete_confirmation_names_the_whole_subtree(
        self, client, auth_headers
    ):
        """A delete with a subtree is a tree rebuild: the children change
        parents and every record standing in the subtree — across modules —
        moves with them. The scoped listing carries that number beside the
        narrowed ones, folded from the full organization tree, because the
        locations the module filter drops are exactly the ones a client-side
        fold would miss."""
        self._stock(client, auth_headers)

        rows = self._rows(client, auth_headers, '?module_scope=equipment')

        # Building subtree: ThinkPad + monitor (equipment) + sparkling water
        # + the rack's spare laptop + flour + rice = 6 records of every
        # module; the rack holds 3 of them.
        assert rows['Office Building']['total_subtree_items_count'] == 6
        assert rows['Server Rack A']['total_subtree_items_count'] == 3

    def test_the_children_it_names_are_all_of_them_and_exactly_the_children(
        self, client, auth_headers
    ):
        """The sentence promises the CHILDREN move up a level, so the number
        is the children — the ones the module filter keeps and the ones it
        drops, and not the grandchildren below them. Counted on the server
        from the full organization tree, beside the record count: a fold
        over this module-filtered listing loses the filtered-out child, and
        a subtree walk inflates the same sentence by every level below."""
        depot = _location(client, auth_headers, 'Depot')
        workshop = _location(client, auth_headers, 'Workshop', parent_id=depot['id'])
        pantry = _location(
            client,
            auth_headers,
            'Pantry',
            parent_id=depot['id'],
            context_tag='food',
        )
        _location(client, auth_headers, 'Shelf', parent_id=pantry['id'])

        def _item(name: str, place: dict, equipment: bool) -> None:
            payload = {
                'name': name,
                'quantity': 1,
                'location_id': place['id'],
            }
            if equipment:
                payload['metadata'] = {'equipment': {'asset_tag': name}}
            created = client.post('/api/v1/items', headers=auth_headers, json=payload)
            assert created.status_code == status.HTTP_201_CREATED, created.text

        _item('Depot scanner', depot, True)
        _item('Workshop drill', workshop, True)
        _item('Flour', pantry, False)
        _item('Rice', _shelf_of(client, auth_headers), False)

        rows = self._rows(client, auth_headers, '?module_scope=equipment')

        assert rows['Depot']['direct_children_count'] == 2
        assert rows['Depot']['total_subtree_items_count'] == 4

    def test_a_record_below_a_location_is_not_its_to_answer_for(
        self, client, auth_headers
    ):
        """A food-only child the equipment listing drops changes nothing
        about what the parent's row owes: the refusal it explains counts
        records standing HERE, and the server reparents children on delete
        rather than asking them first. The fold over the module-filtered
        listing could not say that honestly."""
        self._stock(client, auth_headers)
        cellar = _location(
            client,
            auth_headers,
            'Wine Cellar',
            parent_id=self._building_id,
        )
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Sparkling water case',
                'quantity': 2,
                'location_id': cellar['id'],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        rows = self._rows(client, auth_headers, '?module_scope=equipment')

        assert rows['Office Building']['total_items_count'] == 3
        assert 'Wine Cellar' not in rows

    def test_an_unscoped_listing_keeps_its_counts_whole(self, client, auth_headers):
        self._stock(client, auth_headers)

        rows = self._rows(client, auth_headers, '')

        assert rows['Office Building']['items_count'] == 3
        assert rows['Office Building']['subtree_items_count'] == 6
        # Without a module scope the counts already are the whole truth, so
        # the scoped listing's extra field stays at its zero default rather
        # than repeating them.
        assert rows['Office Building']['total_items_count'] == 0

    def test_the_delete_numbers_ride_the_unscoped_listing_too(
        self, client, auth_headers
    ):
        """The spaces sheet opens on the same rows without a module scope —
        and with the module-data policy off, the default, its listing drops
        every location a module claimed. The delete question there still
        names the consequence the equipment screen names, and both numbers
        answer for the full tree: the child the policy filtered off the rows
        is still a child the delete reparents, and the records standing in
        it still move. ``total_subtree_items_count`` is not a narrowed twin
        on this listing — it is the only number that survives the filtering.
        """
        depot = _location(client, auth_headers, 'Depot')
        workshop = _location(client, auth_headers, 'Workshop', parent_id=depot['id'])
        _location(
            client, auth_headers, 'Pantry', parent_id=depot['id'], context_tag='food'
        )
        rack = _location(
            client,
            auth_headers,
            'Rack',
            parent_id=depot['id'],
            context_tag='equipment',
        )
        lower_shelf = _location(
            client, auth_headers, 'Lower shelf', parent_id=workshop['id']
        )

        for payload in (
            {
                'name': 'Depot scanner',
                'quantity': 1,
                'location_id': rack['id'],
                'metadata': {'equipment': {'asset_tag': 'IT-DEPOT'}},
            },
            {
                'name': 'Shelf box',
                'quantity': 1,
                'location_id': lower_shelf['id'],
            },
        ):
            created = client.post('/api/v1/items', headers=auth_headers, json=payload)
            assert created.status_code == status.HTTP_201_CREATED, created.text

        rows = self._rows(client, auth_headers, '')

        assert rows['Depot']['direct_children_count'] == 3
        assert rows['Workshop']['direct_children_count'] == 1
        assert rows['Lower shelf']['direct_children_count'] == 0
        # Two records change place with a Depot delete: the scanner behind
        # the Rack and the box on the lower shelf. With every row shown both
        # folds agree.
        assert rows['Depot']['subtree_items_count'] == 2
        assert rows['Depot']['total_subtree_items_count'] == 2
        # The scoped listing's all-modules direct twin keeps its zero default
        # here: without a module scope it would only repeat the count beside
        # it.
        assert rows['Depot']['total_items_count'] == 0

        # The default spaces sheet: the module-data policy is off, so the
        # Rack is filtered off the rows — and a fold over those rows counts
        # one record where two change place. The full-tree total still says
        # two, and two is the number the delete question must name.
        filtered = self._rows(client, auth_headers, '?exclude_module_contexts=true')

        assert 'Rack' not in filtered
        assert filtered['Depot']['direct_children_count'] == 3
        assert filtered['Depot']['subtree_items_count'] == 1
        assert filtered['Depot']['total_subtree_items_count'] == 2


@pytest.mark.integration
class TestTheTwoCountersAgree:
    """The listing and the tree draw one counter, so a location says one number.

    Both ask ``item_counts_by_location_async``; the module-scoped listing
    narrows it to the module's records, the tree and the general listing to the
    records ``GET /items`` shows under ``exclude_module_contexts``.
    """

    _stock = TestTheCountsOnAScopedListing._stock
    _rows = TestTheCountsOnAScopedListing._rows

    def test_tree_and_general_listing_count_alike(self, client, auth_headers):
        self._stock(client, auth_headers)

        listed = self._rows(client, auth_headers, '?exclude_module_contexts=true')
        tree = client.get(
            '/api/v1/locations/tree?exclude_module_contexts=true',
            headers=auth_headers,
        )
        assert tree.status_code == status.HTTP_200_OK, tree.text

        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node['children'])

        counted = {n['name']: n['items_count'] for n in walk(tree.json())}
        assert counted['Office Building'] == listed['Office Building']['items_count']
        assert counted['Server Rack A'] == listed['Server Rack A']['items_count']
        # Equipment records stand outside what a general screen lists.
        assert listed['Office Building']['items_count'] == 1
        assert listed['Server Rack A']['items_count'] == 2

    def test_module_scope_counts_what_the_module_lists(self, client, auth_headers):
        self._stock(client, auth_headers)

        general = self._rows(client, auth_headers, '?exclude_module_contexts=true')
        scoped = self._rows(client, auth_headers, '?module_scope=equipment')

        for name in ('Office Building', 'Server Rack A'):
            assert (
                scoped[name]['items_count'] + general[name]['items_count']
                == scoped[name]['total_items_count']
            )
