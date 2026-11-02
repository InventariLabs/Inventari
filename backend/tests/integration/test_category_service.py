"""Integration tests for  and _merge_field_definitions."""

import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import ServiceRejectionError
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryUpdate
from app.services._category_reads import (
    _merge_field_definitions,
    get_by_id_async,
    get_categories_async,
)
from app.services._category_writes import (
    create_category,
    delete_category,
    update_category,
)


@pytest.mark.integration
class TestMergeFieldDefinitions:
    """Tests for the _merge_field_definitions pure helper."""

    def test_update_none_returns_existing(self):
        existing = [{'key': 'color', 'label': 'Color', 'type': 'text'}]
        assert _merge_field_definitions(existing, None) == existing

    def test_update_none_and_existing_none_returns_empty(self):
        assert _merge_field_definitions(None, None) == []

    def test_existing_none_returns_update(self):
        update = [{'key': 'size', 'label': 'Size', 'type': 'number'}]
        assert _merge_field_definitions(None, update) == update

    def test_system_fields_preserved_when_absent_from_update(self):
        existing = [
            {'key': 'cut_type', 'label': 'Cut', 'type': 'text', 'is_system': True},
            {'key': 'color', 'label': 'Color', 'type': 'text'},
        ]
        update = [{'key': 'weight', 'label': 'Weight', 'type': 'number'}]

        result = _merge_field_definitions(existing, update)

        keys = {f['key'] for f in result}
        assert 'cut_type' in keys
        assert 'weight' in keys
        assert 'color' not in keys

    def test_user_cannot_grant_is_system(self):
        update = [
            {'key': 'new_field', 'label': 'New', 'type': 'text', 'is_system': True}
        ]

        result = _merge_field_definitions(None, update)

        assert result[0].get('is_system') is None

    def test_existing_system_flag_carried_over_on_merge(self):
        existing = [
            {'key': 'cut_type', 'label': 'Cut', 'type': 'text', 'is_system': True},
        ]
        update = [{'key': 'cut_type', 'label': 'Cut Updated', 'type': 'text'}]

        result = _merge_field_definitions(existing, update)

        assert len(result) == 1
        assert result[0]['label'] == 'Cut Updated'
        assert result[0]['is_system'] is True

    def test_merge_preserves_update_order(self):
        existing = [{'key': 'a', 'label': 'A', 'type': 'text'}]
        update = [
            {'key': 'b', 'label': 'B', 'type': 'text'},
            {'key': 'a', 'label': 'A2', 'type': 'text'},
        ]

        result = _merge_field_definitions(existing, update)

        assert len(result) == 2
        assert result[0]['key'] == 'b'
        assert result[1]['key'] == 'a'

    def test_an_entry_that_carries_no_label_keeps_the_stored_one(self):
        """A nameless entry is an edit, not a wipe of the name.

        The entry replaces only the keys it carries: what it leaves out
        stays as stored. That is what makes a change of type or required
        possible without echoing the stored label back — echoing it is what
        the contract used to demand, and losing it is what the write used to
        do when the echo was missing.
        """
        existing = [
            {
                'key': 'cut_type',
                'label': 'Cut',
                'type': 'text',
                'options': ['a', 'b'],
                'is_system': True,
            },
        ]
        update = [{'key': 'cut_type', 'type': 'number', 'required': True}]

        result = _merge_field_definitions(existing, update)

        assert len(result) == 1
        assert result[0]['label'] == 'Cut'
        assert result[0]['options'] == ['a', 'b']
        assert result[0]['type'] == 'number'
        assert result[0]['required'] is True
        assert result[0]['is_system'] is True

    def test_a_null_label_is_no_name_not_an_erasure(self):
        """`label: null` carries no name either — the schema's own "unset".

        `label: str | None = None` cannot tell "erase the name" from "I did
        not name it", and a client that serializes the full model always
        sends the null. Reading either as a change would refuse or erase
        what the reader never mentioned; the stored name stays. Naming a
        field blank is `label: ''`, which is a name and passes through.
        """
        existing = [{'key': 'size', 'label': 'Size', 'type': 'text'}]

        result = _merge_field_definitions(
            existing, [{'key': 'size', 'type': 'text', 'label': None}]
        )

        assert result[0]['label'] == 'Size'


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetCategories:
    """Tests for get_categories_async."""

    async def test_returns_system_categories(
        self, real_async_db_session, async_test_household
    ):
        """System categories (organization_id IS NULL) are visible."""
        results = await get_categories_async(
            real_async_db_session, async_test_household.id
        )

        assert len(results) > 0
        # Seeded system categories have organization_id=None
        for cat in results:
            assert (
                cat.organization_id is None
                or cat.organization_id == async_test_household.id
            )

    async def test_returns_org_specific_categories(
        self, real_async_db_session, async_test_household
    ):
        """Org-specific categories are returned alongside system ones."""
        org_cat = Category(
            name='Org Custom Cat',
            organization_id=async_test_household.id,
            sort_order=99,
            is_active=True,
        )
        real_async_db_session.add(org_cat)
        await real_async_db_session.flush()

        results = await get_categories_async(
            real_async_db_session, async_test_household.id
        )

        names = {c.name for c in results}
        assert 'Org Custom Cat' in names

    async def test_excludes_inactive_by_default(
        self, real_async_db_session, async_test_household
    ):
        inactive = Category(
            name='Inactive Cat',
            organization_id=async_test_household.id,
            is_active=False,
        )
        real_async_db_session.add(inactive)
        await real_async_db_session.flush()

        results = await get_categories_async(
            real_async_db_session, async_test_household.id
        )

        names = {c.name for c in results}
        assert 'Inactive Cat' not in names

    async def test_include_inactive_returns_all(
        self, real_async_db_session, async_test_household
    ):
        inactive = Category(
            name='Inactive Cat',
            organization_id=async_test_household.id,
            is_active=False,
        )
        real_async_db_session.add(inactive)
        await real_async_db_session.flush()

        results = await get_categories_async(
            real_async_db_session, async_test_household.id, include_inactive=True
        )

        names = {c.name for c in results}
        assert 'Inactive Cat' in names

    async def test_ordered_by_sort_order_then_name(
        self, real_async_db_session, async_test_household
    ):
        c1 = Category(
            name='Zebra', organization_id=async_test_household.id, sort_order=2
        )
        c2 = Category(
            name='Alpha', organization_id=async_test_household.id, sort_order=2
        )
        c3 = Category(
            name='Beta', organization_id=async_test_household.id, sort_order=1
        )
        real_async_db_session.add_all([c1, c2, c3])
        await real_async_db_session.flush()

        all_cats = await get_categories_async(
            real_async_db_session, async_test_household.id
        )
        org_cats = [c for c in all_cats if c.organization_id == async_test_household.id]

        assert org_cats[0].name == 'Beta'
        assert org_cats[1].name == 'Alpha'
        assert org_cats[2].name == 'Zebra'


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetCategory:
    """Tests for get_by_id_async."""

    async def test_returns_existing_category(
        self, real_async_db_session, async_test_household
    ):
        cat = Category(
            name='Findable',
            organization_id=async_test_household.id,
            is_active=True,
        )
        real_async_db_session.add(cat)
        await real_async_db_session.flush()

        result = await get_by_id_async(
            real_async_db_session, async_test_household.id, cat.id
        )

        assert result is not None
        assert result.name == 'Findable'

    async def test_returns_system_category(
        self, real_async_db_session, async_test_household
    ):
        """System categories (org_id IS NULL) are accessible to any org.

        The test plants its own instead of borrowing one from the food seed,
        which it used to skip without — a precondition it can set costs a row.
        """
        sys_cat = Category(name='System, planted', organization_id=None, is_active=True)
        real_async_db_session.add(sys_cat)
        await real_async_db_session.flush()

        result = await get_by_id_async(
            real_async_db_session, async_test_household.id, sys_cat.id
        )

        assert result is not None
        assert result.id == sys_cat.id

    async def test_returns_none_for_nonexistent(
        self, real_async_db_session, async_test_household
    ):
        result = await get_by_id_async(
            real_async_db_session, async_test_household.id, uuid.uuid4()
        )

        assert result is None

    async def test_returns_none_for_other_org_category(
        self, real_async_db_session, async_test_household
    ):
        from app.models.organization import Organization

        other_org = Organization(name='Other Org for Category Test')
        real_async_db_session.add(other_org)
        await real_async_db_session.flush()

        other_org_cat = Category(
            name='Other Org', organization_id=other_org.id, is_active=True
        )
        real_async_db_session.add(other_org_cat)
        await real_async_db_session.flush()

        result = await get_by_id_async(
            real_async_db_session, async_test_household.id, other_org_cat.id
        )

        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestCreate:
    """Tests for .create_category."""

    def _make_user_dto(self, user):
        from app.core.contracts import UserContextDTO

        return UserContextDTO(
            id=user.id,
            organization_id=user.organization_id,
            role=user.role,
            email=user.email,
        )

    async def test_create_category_success(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        cat_data = CategoryCreate(name='New Category', icon='Box', sort_order=5)
        user_dto = self._make_user_dto(async_test_user)

        result = await create_category(real_async_db_session, cat_data, user_dto)

        assert result.name == 'New Category'
        assert result.organization_id == async_test_household.id
        assert result.id is not None

    async def test_create_category_duplicate_raises(
        self, real_async_db_session, async_test_user
    ):
        cat_data = CategoryCreate(name='Unique Cat', icon='Box')
        user_dto = self._make_user_dto(async_test_user)

        await create_category(real_async_db_session, cat_data, user_dto)

        with pytest.raises(ValueError, match='already exists'):
            await create_category(real_async_db_session, cat_data, user_dto)


@pytest.mark.integration
@pytest.mark.asyncio
class TestUpdate:
    """Tests for .update_category."""

    def _make_user_dto(self, user):
        from app.core.contracts import UserContextDTO

        return UserContextDTO(
            id=user.id,
            organization_id=user.organization_id,
            role=user.role,
            email=user.email,
        )

    async def test_update_name(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        cat = Category(name='Old Name', organization_id=async_test_household.id)
        real_async_db_session.add(cat)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(cat)

        user_dto = self._make_user_dto(async_test_user)
        update = CategoryUpdate(name='New Name')

        result = await update_category(real_async_db_session, cat, update, user_dto)

        assert result.name == 'New Name'

    async def test_update_field_definitions_merges(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        cat = Category(
            name='Merge Test',
            organization_id=async_test_household.id,
            field_definitions=[
                {'key': 'cut_type', 'label': 'Cut', 'type': 'text', 'is_system': True},
            ],
        )
        real_async_db_session.add(cat)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(cat)

        user_dto = self._make_user_dto(async_test_user)
        update = CategoryUpdate(
            field_definitions=[
                {'key': 'weight', 'label': 'Weight', 'type': 'number'},
                {'key': 'cut_type', 'label': 'Cut', 'type': 'text'},
            ]
        )

        result = await update_category(real_async_db_session, cat, update, user_dto)

        keys = {f['key'] for f in result.field_definitions}
        assert 'cut_type' in keys
        assert 'weight' in keys
        # System flag preserved
        cut = next(f for f in result.field_definitions if f['key'] == 'cut_type')
        assert cut['is_system'] is True
        assert cut['label'] == 'Cut'

    async def test_update_refuses_renaming_a_system_field(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """The label of a system field is the catalog's word — renaming refuses.

        The old contract stored the new label where no screen reads it:
        every reader of an is_system field takes the translated catalog
        label, so the write changed nothing the user could see.
        """
        cat = Category(
            name='Rename Refusal',
            organization_id=async_test_household.id,
            field_definitions=[
                {'key': 'cut_type', 'label': 'Cut', 'type': 'text', 'is_system': True},
            ],
        )
        real_async_db_session.add(cat)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(cat)

        user_dto = self._make_user_dto(async_test_user)
        update = CategoryUpdate(
            field_definitions=[
                {'key': 'cut_type', 'label': 'Cut Type', 'type': 'text'},
            ]
        )

        with pytest.raises(ServiceRejectionError) as exc_info:
            await update_category(real_async_db_session, cat, update, user_dto)

        assert exc_info.value.key == 'category_system_field_label_locked'
        # The refusal names the field the way the form the reader was on
        # names it — the stored label, the word FieldBuilder prints — never
        # the technical key, which no screen has ever shown.
        assert 'Cut' in str(exc_info.value)
        assert 'cut_type' not in str(exc_info.value)

    async def test_update_without_a_label_is_not_a_rename(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """A request that carries no name renames nothing.

        The lock used to compare `incoming.get('label')` to the stored label
        and read the schema's own "no label sent" (None) as a rename of
        "Cut", so changing type or required passed only when the client
        echoed the raw stored label back — and on the contract before the
        lock the same write passed while silently dropping the label.
        Neither is the truth: the entry names no field, so the stored name
        stands and the rest of the entry lands.
        """
        cat = Category(
            name='Nameless Edit',
            organization_id=async_test_household.id,
            field_definitions=[
                {
                    'key': 'cut_type',
                    'label': 'Cut',
                    'type': 'text',
                    'required': False,
                    'is_system': True,
                },
            ],
        )
        real_async_db_session.add(cat)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(cat)

        user_dto = self._make_user_dto(async_test_user)
        update = CategoryUpdate(
            field_definitions=[
                {'key': 'cut_type', 'type': 'number', 'required': True},
            ]
        )

        result = await update_category(real_async_db_session, cat, update, user_dto)

        cut = next(f for f in result.field_definitions if f['key'] == 'cut_type')
        assert cut['label'] == 'Cut', 'the catalog keeps its word'
        assert cut['type'] == 'number'
        assert cut['required'] is True
        assert cut['is_system'] is True

    async def test_update_forks_system_category(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """Updating a system category creates an org-specific fork."""
        sys_cat = Category(
            name='System Cat Fork',
            code='sys_fork',
            organization_id=None,
            is_active=True,
        )
        real_async_db_session.add(sys_cat)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(sys_cat)

        user_dto = self._make_user_dto(async_test_user)
        update = CategoryUpdate(name='Forked Name')

        result = await update_category(real_async_db_session, sys_cat, update, user_dto)

        assert result.organization_id == async_test_household.id
        assert result.name == 'Forked Name'
        # Original system category untouched
        await real_async_db_session.refresh(sys_cat)
        assert sys_cat.organization_id is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestDelete:
    """Tests for .delete_category."""

    def _make_user_dto(self, user):
        from app.core.contracts import UserContextDTO

        return UserContextDTO(
            id=user.id,
            organization_id=user.organization_id,
            role=user.role,
            email=user.email,
        )

    async def test_delete_org_category(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        cat = Category(name='Deletable', organization_id=async_test_household.id)
        real_async_db_session.add(cat)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(cat)

        user_dto = self._make_user_dto(async_test_user)
        await delete_category(real_async_db_session, cat, user_dto)

        remaining = (
            await real_async_db_session.scalars(
                select(Category).where(Category.id == cat.id)
            )
        ).all()
        assert len(remaining) == 0

    async def test_delete_system_category_creates_inactive_fork(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """Deleting a system category creates an inactive org-specific fork."""
        sys_cat = Category(
            name='Sys Delete',
            code='sys_del',
            organization_id=None,
            is_active=True,
        )
        real_async_db_session.add(sys_cat)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(sys_cat)

        user_dto = self._make_user_dto(async_test_user)
        await delete_category(real_async_db_session, sys_cat, user_dto)

        fork = (
            await real_async_db_session.scalars(
                select(Category).where(
                    Category.code == 'sys_del',
                    Category.organization_id == async_test_household.id,
                )
            )
        ).first()
        assert fork is not None
        assert fork.is_active is False

    async def test_delete_category_in_use_raises(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """Cannot delete a category that has items referencing it."""
        from app.models.item import Item
        from app.models.storage_location import LocationUsage, StorageLocation

        cat = Category(name='In Use', organization_id=async_test_household.id)
        real_async_db_session.add(cat)
        await real_async_db_session.flush()

        loc = StorageLocation(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            name='Test Loc',
            usage=LocationUsage.INTERNAL,
        )
        real_async_db_session.add(loc)
        await real_async_db_session.flush()

        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=loc.id,
            category_id=cat.id,
            name='Referencing Item',
        )
        real_async_db_session.add(item)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(cat)

        user_dto = self._make_user_dto(async_test_user)

        with pytest.raises(ValueError, match='Cannot delete category'):
            await delete_category(real_async_db_session, cat, user_dto)
