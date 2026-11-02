"""Integration tests for module/vertical visibility isolation.

Covers: archived items scoping, items list, storages, history, and
claimed-tags behavior.
"""

from datetime import UTC, datetime

import pytest
from fastapi import status


@pytest.fixture
def test_household_with_equipment(db_session, test_user):
    """Ensure test_user's org has equipment in enabled_modules."""
    from app.models.organization import Organization

    org = db_session.get(Organization, test_user.organization_id)
    enabled = set(org.enabled_modules or [])
    enabled.add('equipment')
    org.enabled_modules = sorted(enabled)
    db_session.commit()
    return org


def _make_item(
    db_session,
    *,
    name,
    org_id,
    storage_id,
    category,
    deleted=False,
    module_name=None,
):
    """Helper: create (optionally soft-deleted) item.

    ``category`` may be None — an asset saved without one is exactly the case
    the category half of the scope rule cannot answer.
    """
    from app.models.item import Item

    item = Item(
        name=name,
        organization_id=org_id,
        storage_location_id=storage_id,
        category_id=category.id if category else None,
        module_name=module_name,
        quantity=1,
        is_deleted=deleted,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.fixture
def equipment_category(db_session, test_household):
    """A category with context_tag='equipment' (simulating equipment module seed)."""
    from app.models.category import Category

    cat = Category(
        name='IT Equipment',
        code='TEST_EQUIPMENT',
        context_tag='equipment',
        organization_id=test_household.id,
    )
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    return cat


@pytest.fixture
def food_category(db_session, test_household):
    """A food category (no context_tag — food is NOT claimed by a module)."""
    from app.models.category import Category

    cat = Category(
        name='Food',
        code='TEST_FOOD',
        context_tag=None,
        organization_id=test_household.id,
    )
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    return cat


@pytest.fixture
def archived_equipment_item(
    db_session, test_household, test_storage_location, equipment_category
):
    return _make_item(
        db_session,
        name='Archived Laptop',
        org_id=test_household.id,
        storage_id=test_storage_location.id,
        category=equipment_category,
        deleted=True,
    )


@pytest.fixture
def archived_food_item(
    db_session, test_household, test_storage_location, food_category
):
    return _make_item(
        db_session,
        name='Archived Bread',
        org_id=test_household.id,
        storage_id=test_storage_location.id,
        category=food_category,
        deleted=True,
    )


@pytest.mark.integration
class TestArchivedItemsScope:
    """GET /items/archived must respect context_tag and
    exclude_module_contexts."""

    def test_archived_unfiltered_returns_all(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        archived_food_item,
        archived_equipment_item,
    ):
        """Default (no params) — backward compatible — returns everything."""
        resp = client.get('/api/v1/items/archived', headers=auth_headers)
        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert 'Archived Bread' in names
        assert 'Archived Laptop' in names

    def test_archived_context_tag_equipment_excludes_food(
        self,
        client,
        auth_headers,
        archived_food_item,
        archived_equipment_item,
    ):
        resp = client.get(
            '/api/v1/items/archived?context_tag=equipment', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert 'Archived Laptop' in names
        assert 'Archived Bread' not in names

    def test_archived_exclude_module_contexts_hides_equipment(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        archived_food_item,
        archived_equipment_item,
    ):
        """Inventory view: exclude_module_contexts=true hides equipment."""
        resp = client.get(
            '/api/v1/items/archived?exclude_module_contexts=true',
            headers=auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert 'Archived Bread' in names
        assert 'Archived Laptop' not in names

    def test_module_scope_finds_the_asset_archived_without_a_category(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        test_storage_location,
        archived_equipment_item,
        db_session,
    ):
        """A module screen has to see everything it just archived.

        ``context_tag`` asks the category alone, so an asset saved without one
        — the equipment form never required a category — vanished from the
        module's Archive tab the moment it was archived, with no way back to
        it from inside the module. ``module_scope`` asks the pair of questions
        the active list asks.
        """
        _make_item(
            db_session,
            name='Archived Uncategorised Laptop',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=None,
            deleted=True,
            module_name='equipment',
        )

        resp = client.get(
            '/api/v1/items/archived?module_scope=equipment', headers=auth_headers
        )

        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert names == {'Archived Laptop', 'Archived Uncategorised Laptop'}

    def test_module_scope_leaves_out_what_the_module_does_not_own(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        test_storage_location,
        archived_food_item,
        db_session,
    ):
        """An uncategorised record of nobody's stays out of a module's archive."""
        _make_item(
            db_session,
            name='Archived Loose Box',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=None,
            deleted=True,
        )

        resp = client.get(
            '/api/v1/items/archived?module_scope=equipment', headers=auth_headers
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['items'] == []

    def test_an_unregistered_module_scope_narrows_to_nothing(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        archived_food_item,
        archived_equipment_item,
    ):
        """A mistyped scope must not quietly hand back the whole archive."""
        resp = client.get(
            '/api/v1/items/archived?module_scope=nosuchmodule', headers=auth_headers
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['items'] == []


@pytest.mark.integration
class TestItemsListScope:
    """GET /items must respect exclude_module_contexts (Inventory view)."""

    def test_items_exclude_module_contexts_hides_equipment(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        equipment_category,
        food_category,
        test_storage_location,
        db_session,
    ):
        _make_item(
            db_session,
            name='Active Laptop',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=equipment_category,
        )
        _make_item(
            db_session,
            name='Active Bread',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=food_category,
        )
        db_session.commit()

        resp = client.get(
            '/api/v1/items?exclude_module_contexts=true', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert 'Active Bread' in names
        assert 'Active Laptop' not in names

    def test_items_exclude_module_contexts_hides_equipment_without_a_category(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        food_category,
        test_storage_location,
        db_session,
    ):
        """The form never required a category, so plenty of assets have none.

        Asking only about the category let every one of them through: a rack
        with a serial number sat among the groceries on a list the
        organization had asked to keep module data out of.
        """
        _make_item(
            db_session,
            name='Rack 42U Open Frame',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=None,
            module_name='equipment',
        )
        _make_item(
            db_session,
            name='Uncategorised Bread',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=None,
        )
        db_session.commit()

        resp = client.get(
            '/api/v1/items?exclude_module_contexts=true', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert 'Uncategorised Bread' in names
        assert 'Rack 42U Open Frame' not in names

    def test_a_category_without_a_claim_overrules_the_record_owner(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        food_category,
        test_storage_location,
        db_session,
    ):
        """Ownership is where the record is filed, not where it was born.

        Filing a record under an ordinary category is the organization
        saying it is an ordinary record; the module that created it does not
        get to overrule that afterwards.
        """
        _make_item(
            db_session,
            name='Refiled Laptop',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=food_category,
            module_name='equipment',
        )
        db_session.commit()

        resp = client.get(
            '/api/v1/items?exclude_module_contexts=true', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert 'Refiled Laptop' in names

    def test_an_asset_saved_through_the_core_endpoint_is_still_an_asset(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        test_storage_location,
    ):
        """The equipment form does not post to the equipment module.

        It posts to /items, with the module's own namespace in the body and
        no category — so nothing in the request says "equipment" except the
        namespace. Ownership is read off that namespace on write; a client
        naming its own owner would be a client that can hide any record it
        likes.
        """
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Rack 42U Open Frame',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
                'metadata': {'equipment': {'serial_number': 'SN-502944'}},
            },
        )
        assert created.status_code == status.HTTP_201_CREATED

        resp = client.get(
            '/api/v1/items?exclude_module_contexts=true', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert 'Rack 42U Open Frame' not in names

        everything = client.get('/api/v1/items', headers=auth_headers)
        assert 'Rack 42U Open Frame' in {i['name'] for i in everything.json()['items']}

    def test_items_default_includes_everything(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        equipment_category,
        food_category,
        test_storage_location,
        db_session,
    ):
        """No param — backward compatible — returns all."""
        _make_item(
            db_session,
            name='L2 Laptop',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=equipment_category,
        )
        _make_item(
            db_session,
            name='L2 Bread',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=food_category,
        )
        db_session.commit()

        resp = client.get('/api/v1/items', headers=auth_headers)
        names = {i['name'] for i in resp.json()['items']}
        assert {'L2 Laptop', 'L2 Bread'} <= names

    def test_items_context_tag_equipment_returns_only_equipment(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        equipment_category,
        food_category,
        test_storage_location,
        db_session,
    ):
        _make_item(
            db_session,
            name='Scope Laptop',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=equipment_category,
        )
        _make_item(
            db_session,
            name='Scope Bread',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=food_category,
        )
        db_session.commit()

        resp = client.get('/api/v1/items?context_tag=equipment', headers=auth_headers)
        names = {i['name'] for i in resp.json()['items']}
        assert 'Scope Laptop' in names
        assert 'Scope Bread' not in names

    def test_items_context_tag_equipment_finds_the_asset_under_no_category(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        food_category,
        test_storage_location,
        db_session,
    ):
        """The positive filter is the module's own question, not the column's.

        A rack filed under no category stood in the equipment list while
        every ``context_tag=equipment`` read — the dashboard, the fleet
        valuation, this API filter — answered without it, because the filter
        read the category alone and the equipment form never required a
        category. The two screens disagreed about one fleet.
        """
        _make_item(
            db_session,
            name='Rack 42U Open Frame',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=None,
            module_name='equipment',
        )
        _make_item(
            db_session,
            name='Uncategorised Bread',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=None,
        )
        db_session.commit()

        resp = client.get('/api/v1/items?context_tag=equipment', headers=auth_headers)
        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert 'Rack 42U Open Frame' in names
        assert 'Uncategorised Bread' not in names

    def test_items_context_tag_without_a_module_keeps_the_category_reading(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        test_storage_location,
        db_session,
    ):
        """A tag no registered module claims is a plain category label.

        The module question is asked only when the tag names a module; an
        organisation's own tag ('cold_storage') still filters by the column,
        and a record the module owns does not leak into it.
        """
        from app.models.category import Category

        cat = Category(
            name='Chłodnia',
            code='TEST_COLD',
            context_tag='cold_storage',
            organization_id=test_household_with_equipment.id,
        )
        db_session.add(cat)
        db_session.commit()
        db_session.refresh(cat)

        _make_item(
            db_session,
            name='Frozen Peas',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=cat,
        )
        _make_item(
            db_session,
            name='Rack 42U Open Frame',
            org_id=test_household_with_equipment.id,
            storage_id=test_storage_location.id,
            category=None,
            module_name='equipment',
        )
        db_session.commit()

        resp = client.get(
            '/api/v1/items?context_tag=cold_storage', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert 'Frozen Peas' in names
        assert 'Rack 42U Open Frame' not in names


@pytest.fixture
def equipment_storage(db_session, test_household, test_user):
    """A storage location tagged context_tag='equipment'."""
    from app.models.storage_location import StorageLocation

    loc = StorageLocation(
        name='Server Room',
        organization_id=test_household.id,
        created_by=test_user.id,
        context_tag='equipment',
        usage='internal',
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def neutral_storage(db_session, test_household, test_user):
    from app.models.storage_location import StorageLocation

    loc = StorageLocation(
        name='Pantry',
        organization_id=test_household.id,
        created_by=test_user.id,
        context_tag=None,
        usage='internal',
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.mark.integration
class TestStoragesScope:
    """GET /locations must respect exclude_module_contexts."""

    def test_storages_exclude_module_contexts_hides_equipment_locations(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        equipment_storage,
        neutral_storage,
    ):
        resp = client.get(
            '/api/v1/locations?exclude_module_contexts=true', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {s['name'] for s in resp.json()['items']}
        assert 'Pantry' in names
        assert 'Server Room' not in names

    def test_storages_default_includes_everything(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        equipment_storage,
        neutral_storage,
    ):
        resp = client.get('/api/v1/locations', headers=auth_headers)
        names = {s['name'] for s in resp.json()['items']}
        assert {'Pantry', 'Server Room'} <= names


@pytest.fixture
def pantry_shared_with_equipment(
    db_session,
    test_household_with_equipment,
    neutral_storage,
    equipment_category,
    food_category,
):
    """One untagged location holding a product and two assets.

    The assets are the module's by both of the rule's questions: one by its
    claimed category, one — filed under no category — by its owner.
    """
    org_id = test_household_with_equipment.id
    _make_item(
        db_session,
        name='Bread',
        org_id=org_id,
        storage_id=neutral_storage.id,
        category=food_category,
    )
    _make_item(
        db_session,
        name='Laptop',
        org_id=org_id,
        storage_id=neutral_storage.id,
        category=equipment_category,
    )
    _make_item(
        db_session,
        name='Rack 42U Open Frame',
        org_id=org_id,
        storage_id=neutral_storage.id,
        category=None,
        module_name='equipment',
    )
    return neutral_storage


@pytest.mark.integration
class TestStorageCountsScope:
    """The counts on a location answer the question the flag asked.

    With exclude_module_contexts the general screens drop the module's
    locations; the counts on the locations that remain used to go on counting
    the module's records. The inventory overview then said "0 products in
    1 place" above a storage bar of 27 — both answers to one question, from
    two requests carrying the same flag.
    """

    def _pantry(self, rows):
        return next(r for r in rows if r['name'] == 'Pantry')

    def test_tree_counts_only_what_the_items_list_shows(
        self, client, auth_headers, pantry_shared_with_equipment
    ):
        items = client.get(
            '/api/v1/items?exclude_module_contexts=true&limit=1',
            headers=auth_headers,
        ).json()
        resp = client.get(
            '/api/v1/locations/tree?exclude_module_contexts=true',
            headers=auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        pantry = self._pantry(resp.json())
        assert items['total'] == 1
        assert pantry['items_count'] == 1
        assert pantry['subtree_items_count'] == 1

    def test_tree_without_the_flag_still_counts_everything(
        self, client, auth_headers, pantry_shared_with_equipment
    ):
        resp = client.get('/api/v1/locations/tree', headers=auth_headers)
        pantry = self._pantry(resp.json())
        assert pantry['items_count'] == 3
        assert pantry['subtree_items_count'] == 3

    def test_list_counts_the_same_and_keeps_the_whole_truth_beside_it(
        self, client, auth_headers, pantry_shared_with_equipment
    ):
        """The narrowed numbers are for the row; a delete moves every record.

        The all-modules pair rides along so the delete confirmation still
        names the records of every module that change place.
        """
        resp = client.get(
            '/api/v1/locations?exclude_module_contexts=true', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        pantry = self._pantry(resp.json()['items'])
        assert pantry['items_count'] == 1
        assert pantry['subtree_items_count'] == 1
        assert pantry['total_items_count'] == 3
        assert pantry['total_subtree_items_count'] == 3


@pytest.mark.integration
class TestHistoryScope:
    """GET /items/history must respect context_tag and
    exclude_module_contexts."""

    def test_history_context_tag_equipment_excludes_food(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        equipment_category,
        food_category,
        test_storage_location,
        db_session,
    ):
        from app.models.item import Item
        from app.models.item_history import ItemHistory

        eq_item = Item(
            name='Hist Laptop',
            organization_id=test_household_with_equipment.id,
            storage_location_id=test_storage_location.id,
            category_id=equipment_category.id,
            quantity=1,
        )
        food_item = Item(
            name='Hist Bread',
            organization_id=test_household_with_equipment.id,
            storage_location_id=test_storage_location.id,
            category_id=food_category.id,
            quantity=1,
        )
        db_session.add_all([eq_item, food_item])
        db_session.commit()
        for item in (eq_item, food_item):
            db_session.add(
                ItemHistory(
                    item_id=item.id,
                    organization_id=test_household_with_equipment.id,
                    action='CREATED',
                    changes={},
                )
            )
        db_session.commit()

        resp = client.get(
            '/api/v1/items/history?context_tag=equipment&limit=50',
            headers=auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {e['item_name'] for e in resp.json()['items']}
        assert 'Hist Laptop' in names
        assert 'Hist Bread' not in names

    def test_history_exclude_module_contexts_hides_equipment(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        equipment_category,
        food_category,
        test_storage_location,
        db_session,
    ):
        from app.models.item import Item
        from app.models.item_history import ItemHistory

        eq_item = Item(
            name='Excl Laptop',
            organization_id=test_household_with_equipment.id,
            storage_location_id=test_storage_location.id,
            category_id=equipment_category.id,
            quantity=1,
        )
        food_item = Item(
            name='Excl Bread',
            organization_id=test_household_with_equipment.id,
            storage_location_id=test_storage_location.id,
            category_id=food_category.id,
            quantity=1,
        )
        db_session.add_all([eq_item, food_item])
        db_session.commit()
        for item in (eq_item, food_item):
            db_session.add(
                ItemHistory(
                    item_id=item.id,
                    organization_id=test_household_with_equipment.id,
                    action='CREATED',
                    changes={},
                )
            )
        db_session.commit()

        resp = client.get(
            '/api/v1/items/history?exclude_module_contexts=true&limit=50',
            headers=auth_headers,
        )
        names = {e['item_name'] for e in resp.json()['items']}
        assert 'Excl Bread' in names
        assert 'Excl Laptop' not in names


@pytest.fixture
def test_household_without_equipment(db_session, test_user):
    """The org has equipment data but the module switched off."""
    from app.models.organization import Organization

    org = db_session.get(Organization, test_user.organization_id)
    org.enabled_modules = sorted(set(org.enabled_modules or []) - {'equipment'})
    db_session.commit()
    return org


@pytest.mark.integration
class TestIsolationSurvivesDisabling:
    """Data outlives the module that wrote it, and so does its claim.

    A profile without the equipment module — Food & Home is one — still has
    every asset ever recorded under it. Reading the claim off the enabled
    set would put all of them back among the groceries at the moment the
    module was switched off.
    """

    def test_items_stay_hidden_when_the_module_is_disabled(
        self,
        client,
        auth_headers,
        test_household_without_equipment,
        equipment_category,
        food_category,
        test_storage_location,
        db_session,
    ):
        _make_item(
            db_session,
            name='Orphaned Laptop',
            org_id=test_household_without_equipment.id,
            storage_id=test_storage_location.id,
            category=equipment_category,
        )
        _make_item(
            db_session,
            name='Ordinary Bread',
            org_id=test_household_without_equipment.id,
            storage_id=test_storage_location.id,
            category=food_category,
        )
        db_session.commit()

        resp = client.get(
            '/api/v1/items?exclude_module_contexts=true', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {i['name'] for i in resp.json()['items']}
        assert 'Ordinary Bread' in names
        assert 'Orphaned Laptop' not in names

    def test_storages_stay_hidden_when_the_module_is_disabled(
        self,
        client,
        auth_headers,
        test_household_without_equipment,
        equipment_storage,
        neutral_storage,
    ):
        resp = client.get(
            '/api/v1/locations?exclude_module_contexts=true', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        names = {s['name'] for s in resp.json()['items']}
        assert 'Pantry' in names
        assert 'Server Room' not in names

    def test_disabling_does_not_hide_untagged_data(
        self,
        client,
        auth_headers,
        test_household_without_equipment,
        food_category,
        test_storage_location,
        db_session,
    ):
        """The claim covers tagged categories only, never the neutral ones."""
        _make_item(
            db_session,
            name='Plain Cucumber',
            org_id=test_household_without_equipment.id,
            storage_id=test_storage_location.id,
            category=food_category,
        )
        db_session.commit()

        resp = client.get(
            '/api/v1/items?exclude_module_contexts=true', headers=auth_headers
        )
        names = {i['name'] for i in resp.json()['items']}
        assert 'Plain Cucumber' in names


@pytest.mark.integration
class TestCategoriesOwnershipFlag:
    """GET /categories marks the categories a module claims.

    A screen that offers a module-owned category has to be able to say so
    before the save — ``is_module_owned`` is that fact, read off the same
    registry the list isolation applies, so the flag and the scoping can
    never disagree about one category.
    """

    def test_module_owned_flag_follows_the_context_tag(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        equipment_category,
        food_category,
    ):
        resp = client.get('/api/v1/categories', headers=auth_headers)
        assert resp.status_code == status.HTTP_200_OK
        by_id = {c['id']: c for c in resp.json()['items']}
        assert by_id[str(equipment_category.id)]['is_module_owned'] is True
        assert by_id[str(food_category.id)]['is_module_owned'] is False

    def test_module_owned_flag_is_stamped_on_the_scoped_list_too(
        self,
        client,
        auth_headers,
        test_household_with_equipment,
        equipment_category,
        food_category,
    ):
        """Isolation filters with the flag; it does not replace it."""
        resp = client.get(
            '/api/v1/categories?exclude_module_contexts=true',
            headers=auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        listed = resp.json()['items']
        assert str(equipment_category.id) not in {c['id'] for c in listed}
        food = next(c for c in listed if c['id'] == str(food_category.id))
        assert food['is_module_owned'] is False
