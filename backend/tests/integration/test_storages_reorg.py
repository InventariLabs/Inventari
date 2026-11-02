"""Integration tests for the transactional storage reorg batch endpoint.

The reorg modal used to save the new hierarchy as a sequence of individual
create/update/delete requests — a failure in the middle left the tree
half-applied with no rollback. The batch endpoint executes the whole
operation list in one transaction and validates the FINAL tree state, so:

- a batch with one illegal operation changes nothing and returns the reason,
- an intermediate cycle that disappears by the end of the batch (swapping two
  nodes' parents) is accepted,
- create/delete/move ops resolve against each other (temporary ids).
"""

import pytest
from fastapi import status


@pytest.mark.integration
class TestStorageReorg:
    """Tests for POST /locations/reorg (batch, transactional)."""

    def _make_storage(self, db_session, user, name, parent_id=None):
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=user.organization_id,
            created_by=user.id,
            name=name,
            parent_id=parent_id,
            usage='internal',
        )
        db_session.add(storage)
        db_session.commit()
        db_session.refresh(storage)
        return storage

    def _reorg(self, client, auth_headers, operations):
        return client.post(
            '/api/v1/locations/reorg',
            headers=auth_headers,
            json={'operations': operations},
        )

    def _get(self, client, auth_headers, storage_id):
        return client.get(f'/api/v1/locations/{storage_id}', headers=auth_headers)

    def test_cycle_move_rejected_and_nothing_changes(
        self, client, auth_headers, db_session, test_user
    ):
        """Moving a node under its own descendant is rejected atomically."""
        site = self._make_storage(db_session, test_user, 'Site')
        zone = self._make_storage(db_session, test_user, 'Zone', parent_id=site.id)

        response = self._reorg(
            client,
            auth_headers,
            [{'op': 'move', 'id': str(site.id), 'parent_id': str(zone.id)}],
        )

        assert response.status_code == status.HTTP_207_MULTI_STATUS
        body = response.json()
        assert body['applied'] is False
        assert len(body['rejections']) == 1
        rejection = body['rejections'][0]
        assert rejection['index'] == 0
        assert 'cycle' in rejection['reason'].lower()
        # Nothing changed in the database.
        after = self._get(client, auth_headers, site.id).json()
        assert after['parent_id'] is None

    def test_intermediate_cycle_with_legal_final_state_passes(
        self, client, auth_headers, db_session, test_user
    ):
        """Final-state validation accepts a batch whose intermediate state
        is temporarily cyclic: B under A (op 0) while A is still under B,
        then A moves under C (op 1) — final tree C -> A -> B."""
        c_root = self._make_storage(db_session, test_user, 'C')
        a_node = self._make_storage(db_session, test_user, 'A')
        b_node = self._make_storage(db_session, test_user, 'B', parent_id=a_node.id)
        # Existing state: A.parent = B? No — make the pre-state A under B.
        a_node.parent_id = b_node.id
        db_session.add(a_node)
        db_session.commit()

        response = self._reorg(
            client,
            auth_headers,
            [
                {'op': 'move', 'id': str(b_node.id), 'parent_id': str(a_node.id)},
                {'op': 'move', 'id': str(a_node.id), 'parent_id': str(c_root.id)},
            ],
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body['applied'] is True, body
        assert body['rejections'] == []
        assert self._get(client, auth_headers, a_node.id).json()['parent_id'] == str(
            c_root.id
        )
        assert self._get(client, auth_headers, b_node.id).json()['parent_id'] == str(
            a_node.id
        )

    def test_swap_parents_passes(self, client, auth_headers, db_session, test_user):
        """Two nodes swapping parents is a legal batch."""
        site_p = self._make_storage(db_session, test_user, 'Site P')
        site_q = self._make_storage(db_session, test_user, 'Site Q')
        node_a = self._make_storage(db_session, test_user, 'A', parent_id=site_p.id)
        node_b = self._make_storage(db_session, test_user, 'B', parent_id=site_q.id)

        response = self._reorg(
            client,
            auth_headers,
            [
                {'op': 'move', 'id': str(node_a.id), 'parent_id': str(site_q.id)},
                {'op': 'move', 'id': str(node_b.id), 'parent_id': str(site_p.id)},
            ],
        )

        body = response.json()
        assert body['applied'] is True, body
        assert self._get(client, auth_headers, node_a.id).json()['parent_id'] == str(
            site_q.id
        )
        assert self._get(client, auth_headers, node_b.id).json()['parent_id'] == str(
            site_p.id
        )

    def test_delete_with_items_rejected_and_nothing_changes(
        self, client, auth_headers, db_session, test_user
    ):
        """Deleting a location that holds items rejects the whole batch."""
        from app.models.item import Item

        storage = self._make_storage(db_session, test_user, 'Occupied')
        site = self._make_storage(db_session, test_user, 'Site')
        other = self._make_storage(db_session, test_user, 'Other', parent_id=site.id)
        db_session.add(
            Item(
                organization_id=test_user.organization_id,
                storage_location_id=storage.id,
                name='Widget',
                quantity=1,
            )
        )
        db_session.commit()

        response = self._reorg(
            client,
            auth_headers,
            [
                {'op': 'move', 'id': str(other.id), 'parent_id': None},
                {'op': 'delete', 'id': str(storage.id)},
            ],
        )

        body = response.json()
        assert body['applied'] is False
        assert any(
            r['op'] == 'delete' and 'item' in r['reason'].lower()
            for r in body['rejections']
        )
        # Nothing changed: the move did not land and the location still exists.
        assert self._get(client, auth_headers, other.id).json()['parent_id'] == str(
            site.id
        )
        assert self._get(client, auth_headers, storage.id).status_code == 200

    def test_duplicate_sibling_name_rejected(
        self, client, auth_headers, db_session, test_user
    ):
        """Two creates with the same name under the same parent are rejected."""
        response = self._reorg(
            client,
            auth_headers,
            [
                {
                    'op': 'create',
                    'temporary_id': 't1',
                    'name': 'Zone X',
                    'parent_id': None,
                },
                {
                    'op': 'create',
                    'temporary_id': 't2',
                    'name': 'Zone X',
                    'parent_id': None,
                },
            ],
        )

        body = response.json()
        assert body['applied'] is False
        assert any(
            r['temporary_id'] == 't2' and 'already exists' in r['reason'].lower()
            for r in body['rejections']
        )
        # Neither zone was created.
        listing = client.get('/api/v1/locations', headers=auth_headers).json()['items']
        assert not any(s['name'] == 'Zone X' for s in listing)

    def test_full_flow_creates_and_moves(
        self, client, auth_headers, db_session, test_user
    ):
        """Create site + zone via temporary ids and move a place into them."""
        place = self._make_storage(db_session, test_user, 'Place')

        response = self._reorg(
            client,
            auth_headers,
            [
                {
                    'op': 'create',
                    'temporary_id': 'site_t',
                    'name': 'New Site',
                    'parent_id': None,
                },
                {
                    'op': 'create',
                    'temporary_id': 'zone_t',
                    'name': 'New Zone',
                    'parent_id': 'site_t',
                },
                {'op': 'move', 'id': str(place.id), 'parent_id': 'zone_t'},
            ],
        )

        body = response.json()
        assert body['applied'] is True, body
        assert set(body['created'].keys()) == {'site_t', 'zone_t'}
        zone_id = body['created']['zone_t']
        assert self._get(client, auth_headers, place.id).json()['parent_id'] == zone_id

    def test_batch_inherits_the_module_tag_from_the_parent(
        self, client, auth_headers, db_session, test_user
    ):
        """The batch follows the same address rule as the single-record
        paths: filing under a module's location fills an empty tag — for a
        create, and for a move, including a move under a node the same batch
        just created.
        """
        room = self._make_storage(db_session, test_user, 'Server Room')
        room.context_tag = 'equipment'
        db_session.commit()
        place = self._make_storage(db_session, test_user, 'Spare Trolley')

        response = self._reorg(
            client,
            auth_headers,
            [
                {
                    'op': 'create',
                    'temporary_id': 'cage_t',
                    'name': 'Equipment Cage',
                    'parent_id': str(room.id),
                },
                {'op': 'move', 'id': str(place.id), 'parent_id': 'cage_t'},
            ],
        )

        body = response.json()
        assert body['applied'] is True, body
        cage_id = body['created']['cage_t']
        assert (
            self._get(client, auth_headers, cage_id).json()['context_tag']
            == 'equipment'
        )
        assert (
            self._get(client, auth_headers, place.id).json()['context_tag']
            == 'equipment'
        )

    def test_unknown_id_rejected(self, client, auth_headers, db_session, test_user):
        """Moving a nonexistent storage rejects the batch."""
        from uuid import uuid4

        response = self._reorg(
            client,
            auth_headers,
            [{'op': 'move', 'id': str(uuid4()), 'parent_id': None}],
        )

        body = response.json()
        assert body['applied'] is False
        assert len(body['rejections']) == 1
        assert body['rejections'][0]['index'] == 0

    def test_delete_with_referenced_child_rejected(
        self, client, auth_headers, db_session, test_user
    ):
        """Deleting a node whose child is still attached rejects the batch."""
        site = self._make_storage(db_session, test_user, 'Site')
        self._make_storage(db_session, test_user, 'Zone', parent_id=site.id)

        response = self._reorg(
            client,
            auth_headers,
            [{'op': 'delete', 'id': str(site.id)}],
        )

        body = response.json()
        assert body['applied'] is False
        assert any(
            r['op'] == 'delete' and 'child' in r['reason'].lower()
            for r in body['rejections']
        )
        # The site still exists.
        assert self._get(client, auth_headers, site.id).status_code == 200

    def test_delete_zone_and_parent_site_together(
        self, client, auth_headers, db_session, test_user
    ):
        """Deleting a whole branch (zone then its site) is a legal batch —
        the deleted zone must not count as an orphaned child."""
        site = self._make_storage(db_session, test_user, 'Site')
        zone = self._make_storage(db_session, test_user, 'Zone', parent_id=site.id)
        site_id = site.id
        zone_id = zone.id

        response = self._reorg(
            client,
            auth_headers,
            [
                {'op': 'delete', 'id': str(zone_id)},
                {'op': 'delete', 'id': str(site_id)},
            ],
        )

        body = response.json()
        assert body['applied'] is True, body
        assert self._get(client, auth_headers, site_id).status_code == 404
        assert self._get(client, auth_headers, zone_id).status_code == 404

    def test_delete_cyclic_pair_together(
        self, client, auth_headers, db_session, test_user
    ):
        """Deleting both members of a pre-existing cycle is a legal batch."""
        from app.models.storage_location import StorageLocation

        a_node = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Cycle A',
            usage='internal',
        )
        b_node = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Cycle B',
            usage='internal',
        )
        db_session.add_all([a_node, b_node])
        db_session.flush()
        a_node.parent_id = b_node.id
        b_node.parent_id = a_node.id
        db_session.commit()
        a_id = a_node.id
        b_id = b_node.id

        response = self._reorg(
            client,
            auth_headers,
            [
                {'op': 'delete', 'id': str(a_id)},
                {'op': 'delete', 'id': str(b_id)},
            ],
        )

        body = response.json()
        assert body['applied'] is True, body
        assert self._get(client, auth_headers, a_id).status_code == 404
        assert self._get(client, auth_headers, b_id).status_code == 404


@pytest.mark.integration
class TestStorageReorgDepth:
    """ADR-018: a batch may build a chain of any length in one transaction."""

    def _reorg(self, client, auth_headers, operations):
        return client.post(
            '/api/v1/locations/reorg',
            headers=auth_headers,
            json={'operations': operations},
        )

    def test_batch_creates_a_chain_of_five_in_one_transaction(
        self, client, auth_headers
    ):
        names = ('Warehouse', 'Aisle 3', 'Rack B', 'Shelf 2', 'Bin 7')
        operations = []
        for depth, name in enumerate(names):
            operations.append(
                {
                    'op': 'create',
                    'temporary_id': f'tmp-{depth}',
                    'name': name,
                    'parent_id': None if depth == 0 else f'tmp-{depth - 1}',
                }
            )

        response = self._reorg(client, auth_headers, operations)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['applied'] is True, body

        listed = client.get('/api/v1/locations', headers=auth_headers).json()['items']
        by_name = {row['name']: row for row in listed}
        for parent, child in zip(names, names[1:], strict=False):
            assert by_name[child]['parent_id'] == by_name[parent]['id']
        assert by_name['Bin 7']['full_path'].endswith('Bin 7')

    def test_batch_may_move_a_subtree_deeper_than_three(self, client, auth_headers):
        created = self._reorg(
            client,
            auth_headers,
            [
                {'op': 'create', 'temporary_id': 't0', 'name': 'Warehouse'},
                {
                    'op': 'create',
                    'temporary_id': 't1',
                    'name': 'Aisle 3',
                    'parent_id': 't0',
                },
                {
                    'op': 'create',
                    'temporary_id': 't2',
                    'name': 'Rack B',
                    'parent_id': 't1',
                },
                {'op': 'create', 'temporary_id': 't3', 'name': 'Overflow'},
            ],
        )
        assert created.status_code == 200, created.text

        listed = client.get('/api/v1/locations', headers=auth_headers).json()['items']
        by_name = {row['name']: row['id'] for row in listed}

        response = self._reorg(
            client,
            auth_headers,
            [
                {
                    'op': 'move',
                    'id': by_name['Overflow'],
                    'parent_id': by_name['Rack B'],
                }
            ],
        )

        assert response.status_code == 200, response.text
        assert response.json()['applied'] is True
        moved = client.get(
            f'/api/v1/locations/{by_name["Overflow"]}', headers=auth_headers
        ).json()
        assert moved['parent_id'] == by_name['Rack B']
