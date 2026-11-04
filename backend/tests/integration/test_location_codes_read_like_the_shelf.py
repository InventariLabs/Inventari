"""Location codes for a business read like the shelf; a household keeps LOC-.

A warehouse is a top-level location and carries a code template. A business
profile's default follows the tree — ``{zone}-{rack:02}-{level:02}`` — so a
zone is ``A``, its second rack ``A-02`` and that rack's first level
``A-02-01``: a person reads the place off the sticker without scanning. A
household's default is a prefix, and codes stay random (``LOC-7KQ2``).

When numbering changes a code, the old one stays behind as a pool label
aimed at the location, so the sticker on the shelf keeps scanning to the
same place until it is replaced, and the location is listed as a sticker to
reprint.
"""

from __future__ import annotations

import re
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select, update

from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration

_RANDOM = re.compile(r'^LOC-[A-Z0-9]{4}$')


def _profile(db_session, user, profile_id: str) -> None:
    db_session.execute(
        update(Organization)
        .where(Organization.id == user.organization_id)
        .values(active_profile_id=profile_id)
    )
    db_session.commit()


def _add(client, headers, name: str, parent: dict | None = None, **extra) -> dict:
    response = client.post(
        '/api/v1/locations',
        json={'name': name, 'parent_id': parent['id'] if parent else None, **extra},
        headers=headers,
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()


def _code(client, headers, location: dict) -> str | None:
    return client.get(f'/api/v1/locations/{location["id"]}', headers=headers).json()[
        'short_code'
    ]


def _scan(client, headers, code: str) -> dict:
    response = client.get(f'/api/v1/labels/scan/{code}', headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


def _tree(client, headers, profile_id, db_session, user):
    """Warehouse › Zone North › Rack 1 › Level 1, and Rack 2 beside Rack 1."""
    _profile(db_session, user, profile_id)
    warehouse = _add(client, headers, 'Main Warehouse')
    zone = _add(client, headers, 'Zone North', warehouse)
    rack = _add(client, headers, 'Rack 1', zone)
    level = _add(client, headers, 'Level 1', rack)
    second = _add(client, headers, 'Rack 2', zone)
    return warehouse, zone, rack, level, second


class TestABusinessNumbersTheTree:
    def test_each_level_takes_the_next_code_under_its_parent(
        self, client, auth_headers, db_session, test_user
    ):
        _, zone, rack, level, second = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        assert zone['short_code'] == 'A'
        assert rack['short_code'] == 'A-01'
        assert level['short_code'] == 'A-01-01'
        assert second['short_code'] == 'A-02'

    def test_a_second_zone_takes_the_next_letter(
        self, client, auth_headers, db_session, test_user
    ):
        warehouse, *_ = _tree(client, auth_headers, 'clean_core', db_session, test_user)
        assert _add(client, auth_headers, 'Zone South', warehouse)['short_code'] == 'B'

    def test_renaming_a_zone_leaves_every_code_under_it(
        self, client, auth_headers, db_session, test_user
    ):
        _, zone, rack, level, _ = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        response = client.put(
            f'/api/v1/locations/{zone["id"]}',
            json={'name': 'Zone Cold'},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert [_code(client, auth_headers, row) for row in (zone, rack, level)] == [
            'A',
            'A-01',
            'A-01-01',
        ]

    def test_the_structure_editor_numbers_what_it_creates(
        self, client, auth_headers, db_session, test_user
    ):
        _, zone, *_ = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        response = client.post(
            '/api/v1/locations/reorg',
            json={
                'operations': [
                    {
                        'op': 'create',
                        'temporary_id': 'rack',
                        'name': 'Rack 3',
                        'parent_id': zone['id'],
                    },
                    {
                        'op': 'create',
                        'temporary_id': 'level',
                        'name': 'Level 1',
                        'parent_id': 'rack',
                    },
                ]
            },
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['applied'] is True
        # By the ids the batch created: the tree already holds a 'Level 1'
        # under Rack 1, and rows keyed by name came back in whatever order
        # the planner chose.
        created = response.json()['created']
        codes = {
            temporary_id: db_session.get(StorageLocation, UUID(location_id)).short_code
            for temporary_id, location_id in created.items()
        }
        # A rack made in the same batch is a numbered parent for its level.
        assert codes == {'rack': 'A-03', 'level': 'A-03-01'}

    def test_a_typed_code_stays_as_typed(
        self, client, auth_headers, db_session, test_user
    ):
        _, zone, *_ = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        typed = _add(client, auth_headers, 'Dock', zone, short_code='DOCK-1')
        assert typed['short_code'] == 'DOCK-1'

    def test_a_number_is_never_one_an_old_sticker_still_carries(
        self, client, auth_headers, db_session, test_user
    ):
        _, zone, *_ = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        db_session.add(
            LabelPool(
                short_code='A-03',
                label_type='STORAGE',
                organization_id=test_user.organization_id,
                created_by=test_user.id,
            )
        )
        db_session.commit()
        assert _add(client, auth_headers, 'Rack 3', zone)['short_code'] == 'A-04'

    def test_the_warehouse_reports_its_template(
        self, client, auth_headers, db_session, test_user
    ):
        _, _, _, level, _ = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        codes = client.get(
            f'/api/v1/locations/{level["id"]}/codes', headers=auth_headers
        ).json()
        assert codes['template'] == '{zone}-{rack:02}-{level:02}'
        assert codes['is_tree'] is True
        assert codes['stored'] is False
        assert codes['reprint'] == []


class TestAHouseholdKeepsRandomCodes:
    def test_every_level_draws_a_loc_code(
        self, client, auth_headers, db_session, test_user
    ):
        rows = _tree(client, auth_headers, 'food_home', db_session, test_user)
        assert all(_RANDOM.match(row['short_code']) for row in rows), rows

    def test_numbering_a_random_warehouse_is_refused_in_words(
        self, client, auth_headers, db_session, test_user
    ):
        warehouse, *_ = _tree(client, auth_headers, 'food_home', db_session, test_user)
        response = client.post(
            f'/api/v1/locations/{warehouse["id"]}/number',
            json={'renumber': True},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert '{zone}' in response.json()['detail']['message']


class TestAHouseholdThatBecomesABusiness:
    """The stickers on the shelves are LOC- codes and must keep scanning."""

    @pytest.fixture
    def switched(self, client, auth_headers, db_session, test_user):
        rows = _tree(client, auth_headers, 'food_home', db_session, test_user)
        old = {row['name']: row['short_code'] for row in rows}
        _profile(db_session, test_user, 'equipment_wms')
        return rows, old

    def test_nothing_is_rewritten_by_the_switch(self, client, auth_headers, switched):
        rows, old = switched
        assert {row['name']: _code(client, auth_headers, row) for row in rows} == old

    def test_a_new_rack_under_an_unnumbered_zone_keeps_drawing_loc(
        self, client, auth_headers, switched
    ):
        (_, zone, *_), _ = switched
        assert _RANDOM.match(_add(client, auth_headers, 'Rack 3', zone)['short_code'])

    def test_renumbering_gives_shelf_codes_and_old_stickers_keep_scanning(
        self, client, auth_headers, db_session, switched
    ):
        (warehouse, zone, rack, level, second), old = switched
        response = client.post(
            f'/api/v1/locations/{warehouse["id"]}/number',
            json={'renumber': True},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert {c['name']: c['new_code'] for c in body['changes']} == {
            'Zone North': 'A',
            'Rack 1': 'A-01',
            'Level 1': 'A-01-01',
            'Rack 2': 'A-02',
        }
        # The warehouse keeps its code: no template level numbers it.
        assert _code(client, auth_headers, warehouse) == old['Main Warehouse']
        for row in (zone, rack, level, second):
            scanned = _scan(client, auth_headers, old[row['name']])
            assert scanned['location']['id'] == row['id']
            # The scan of the new code names the same shelf.
            new = _code(client, auth_headers, row)
            assert _scan(client, auth_headers, new)['location']['id'] == (row['id'])
        reprint = body['codes']['reprint']
        assert {r['name']: r['old_code'] for r in reprint} == {
            name: old[name] for name in ('Zone North', 'Rack 1', 'Level 1', 'Rack 2')
        }
        assert next(r for r in reprint if r['name'] == 'Level 1')['path'] == (
            'Main Warehouse › Zone North › Rack 1 › Level 1'
        )
        aliases = db_session.scalars(
            select(LabelPool).where(LabelPool.short_code == old['Rack 1'])
        ).all()
        assert [(a.label_type, str(a.target_storage_location_id)) for a in aliases] == [
            ('STORAGE', rack['id'])
        ]

    def test_a_location_back_on_its_old_code_renumbers_again(
        self, client, auth_headers, db_session, switched
    ):
        (warehouse, zone, *_), old = switched
        number = {'renumber': True}
        url = f'/api/v1/locations/{warehouse["id"]}/number'
        client.post(url, json=number, headers=auth_headers)
        # The zone takes its old sticker's code back — its own alias.
        response = client.put(
            f'/api/v1/locations/{zone["id"]}',
            json={'short_code': old['Zone North']},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text

        response = client.post(url, json=number, headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        assert _code(client, auth_headers, zone) == 'A'
        aliases = db_session.scalars(
            select(LabelPool).where(LabelPool.short_code == old['Zone North'])
        ).all()
        assert [str(a.target_storage_location_id) for a in aliases] == [zone['id']]

    def test_an_old_code_is_never_given_to_a_new_location(
        self, client, auth_headers, switched
    ):
        (warehouse, zone, rack, *_), old = switched
        client.post(
            f'/api/v1/locations/{warehouse["id"]}/number',
            json={'renumber': False},
            headers=auth_headers,
        )
        response = client.post(
            '/api/v1/locations',
            json={
                'name': 'Spare',
                'parent_id': zone['id'],
                'short_code': old['Rack 1'],
            },
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_a_replaced_sticker_leaves_the_list_and_the_old_code_still_scans(
        self, client, auth_headers, switched
    ):
        (warehouse, zone, rack, *_), old = switched
        client.post(
            f'/api/v1/locations/{warehouse["id"]}/number',
            json={'renumber': False},
            headers=auth_headers,
        )
        response = client.post(
            '/api/v1/locations/reprinted',
            json={'location_ids': [rack['id']]},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        reprint = client.get(
            f'/api/v1/locations/{warehouse["id"]}/codes', headers=auth_headers
        ).json()['reprint']
        assert 'Rack 1' not in {r['name'] for r in reprint}
        assert (
            _scan(client, auth_headers, old['Rack 1'])['location']['id'] == (rack['id'])
        )


class TestNumberingABranch:
    def test_number_this_rack_codes_what_has_none_and_keeps_the_rest(
        self, client, auth_headers, db_session, test_user
    ):
        """A rack set up while its zone was still unnumbered: numbering the
        zone gives the rack and its levels their shelf codes."""
        warehouse, zone, rack, level, second = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        stray = _add(client, auth_headers, 'Rack 9', zone, short_code='OLD9')
        under = _add(client, auth_headers, 'Level 1', stray)
        assert _RANDOM.match(under['short_code'])
        response = client.post(
            f'/api/v1/locations/{stray["id"]}/number',
            json={'renumber': False},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert {c['name']: c['new_code'] for c in response.json()['changes']} == {
            'Rack 9': 'A-03',
            'Level 1': 'A-03-01',
        }
        # The rest of the zone was not touched.
        assert _code(client, auth_headers, second) == 'A-02'
        assert _scan(client, auth_headers, 'OLD9')['location']['id'] == (stray['id'])

    def test_renumbering_follows_the_walk_order_for_what_has_no_code_yet(
        self, client, auth_headers, db_session, test_user
    ):
        warehouse, zone, rack, level, second = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        late = _add(client, auth_headers, 'Rack 8', zone, short_code='OLD8')
        early = _add(client, auth_headers, 'Rack 9', zone, short_code='OLD9')
        for place, sequence in ((early, 1), (late, 2)):
            client.put(
                f'/api/v1/locations/{place["id"]}',
                json={'sequence': sequence},
                headers=auth_headers,
            )
        response = client.post(
            f'/api/v1/locations/{zone["id"]}/number',
            json={'renumber': True},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        # Rack 9 walks before Rack 8; both are numbered after the racks that
        # already read like the shelf, which keep their codes.
        assert _code(client, auth_headers, early) == 'A-03'
        assert _code(client, auth_headers, late) == 'A-04'
        assert _code(client, auth_headers, rack) == 'A-01'
        assert _code(client, auth_headers, second) == 'A-02'
        assert _scan(client, auth_headers, 'OLD9')['location']['id'] == (early['id'])

    def test_renumbering_leaves_a_code_that_already_matches_unchanged(
        self, client, auth_headers, db_session, test_user
    ):
        """A rack that walks after a rack with a foreign code keeps its code."""
        warehouse, zone, rack, level, second = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        # Walks before Rack 1 and would take A-01 in a numbering from scratch.
        moved = _add(client, auth_headers, 'Rack 0', zone, short_code='B-07')
        client.put(
            f'/api/v1/locations/{moved["id"]}',
            json={'sequence': 1},
            headers=auth_headers,
        )
        response = client.post(
            f'/api/v1/locations/{zone["id"]}/number',
            json={'renumber': True},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert {c['name'] for c in response.json()['changes']} == {'Rack 0'}
        assert _code(client, auth_headers, rack) == 'A-01'
        assert _code(client, auth_headers, level) == 'A-01-01'
        assert _code(client, auth_headers, second) == 'A-02'
        assert _code(client, auth_headers, moved) == 'A-03'

    def test_a_branch_under_an_unnumbered_parent_is_refused(
        self, client, auth_headers, db_session, test_user
    ):
        warehouse, zone, *_ = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        # Not a zone code: letters alone would be one.
        odd = _add(client, auth_headers, 'Odd zone', warehouse, short_code='DOCK-1')
        shelf = _add(client, auth_headers, 'Shelf', odd)
        response = client.post(
            f'/api/v1/locations/{shelf["id"]}/number',
            json={'renumber': False},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestTheTemplate:
    def test_a_warehouse_takes_a_template_of_its_own(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user, 'equipment_wms')
        warehouse = _add(client, auth_headers, 'Second Warehouse')
        response = client.put(
            f'/api/v1/locations/{warehouse["id"]}/code-template',
            json={'template': 'w2/{aisle:03}.{bay}'},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['template'] == 'W2/{aisle:03}.{bay}'
        aisle = _add(client, auth_headers, 'Aisle', warehouse)
        bay = _add(client, auth_headers, 'Bay', aisle)
        assert (aisle['short_code'], bay['short_code']) == ('W2/001', 'W2/001.A')

    def test_a_prefix_template_draws_random_codes_after_it(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user, 'equipment_wms')
        warehouse = _add(client, auth_headers, 'Annex')
        client.put(
            f'/api/v1/locations/{warehouse["id"]}/code-template',
            json={'template': 'ANX-'},
            headers=auth_headers,
        )
        assert re.match(
            r'^ANX-[A-Z0-9]{4}$',
            _add(client, auth_headers, 'Bay', warehouse)['short_code'],
        )

    @pytest.mark.parametrize(
        'template', ['{zone}{rack:02}', 'TOO-LONG-PREFIX', '{zone}-{rack:02}x?', '']
    )
    def test_a_template_that_cannot_number_is_refused(
        self, client, auth_headers, db_session, test_user, template
    ):
        warehouse = _add(client, auth_headers, 'Third Warehouse')
        response = client.put(
            f'/api/v1/locations/{warehouse["id"]}/code-template',
            json={'template': template or ' '},
            headers=auth_headers,
        )
        if not template:
            # Empty means "follow the profile again", not a mistake.
            assert response.status_code == status.HTTP_200_OK
            assert response.json()['stored'] is False
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_only_a_warehouse_carries_a_template(
        self, client, auth_headers, db_session, test_user
    ):
        _, zone, *_ = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        response = client.put(
            f'/api/v1/locations/{zone["id"]}/code-template',
            json={'template': '{zone}'},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestAScanAddressNamesTheShelf:
    def test_an_old_qr_read_by_a_hardware_scanner_names_the_shelf(
        self, client, auth_headers, db_session, test_user
    ):
        _, _, _, level, _ = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        address = 'https%3A%2F%2Fwh.example.test%2Flabels%2Fscan%2FA-01-01'
        scanned = _scan(client, auth_headers, address)
        assert scanned['location']['id'] == level['id']

    def test_an_archived_location_keeps_its_code_out_of_reach(
        self, client, auth_headers, db_session, test_user
    ):
        _, zone, _, _, second = _tree(
            client, auth_headers, 'equipment_wms', db_session, test_user
        )
        db_session.execute(
            update(StorageLocation)
            .where(StorageLocation.id == second['id'])
            .values(settings={'archived': True})
        )
        db_session.commit()
        assert _add(client, auth_headers, 'Rack 3', zone)['short_code'] == 'A-03'
