"""
Integration tests for categories API endpoints.

Tests verify correctness of endpoints:
- GET /api/v1/categories - list categories
- POST /api/v1/categories - create category
- GET /api/v1/categories/{category_id} - category details
- PUT /api/v1/categories/{category_id} - update category
- DELETE /api/v1/categories/{category_id} - delete category
"""

import pytest
from fastapi import status
from sqlalchemy import select

from app.models.user import User
from app.services.token_service import create_access_token


@pytest.mark.integration
class TestCategoriesList:
    """Tests for categories list endpoint."""

    def test_get_categories_list(self, client, auth_headers):
        """Tests fetching categories list."""
        response = client.get('/api/v1/categories', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert isinstance(data, list)

    def test_get_categories_with_data(self, client, auth_headers, test_category):
        """Tests fetching categories list with data."""
        response = client.get('/api/v1/categories', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        categories = response.json()['items']
        assert len(categories) >= 1
        assert any(c['id'] == str(test_category.id) for c in categories)

    def test_get_categories_omits_counts_by_default(
        self, client, auth_headers, test_category, test_item
    ):
        """The count is extra work, so it is only computed when asked for."""
        response = client.get('/api/v1/categories', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        category = next(
            c for c in response.json()['items'] if c['id'] == str(test_category.id)
        )
        assert category['items_count'] is None

    def test_get_categories_with_counts(
        self, client, auth_headers, test_category, test_item
    ):
        """A category card that cannot say how much it holds says nothing."""
        response = client.get(
            '/api/v1/categories?with_counts=true', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        categories = response.json()['items']
        category = next(c for c in categories if c['id'] == str(test_category.id))
        assert category['items_count'] == 1
        # Categories nobody filed anything under report zero, not null
        assert all(c['items_count'] is not None for c in categories)

    def test_get_categories_counts_skip_deleted_items(
        self, client, auth_headers, db_session, test_category, test_item
    ):
        """A deleted item is gone from the list, so it is gone from the count."""
        test_item.is_deleted = True
        db_session.commit()

        response = client.get(
            '/api/v1/categories?with_counts=true', headers=auth_headers
        )

        category = next(
            c for c in response.json()['items'] if c['id'] == str(test_category.id)
        )
        assert category['items_count'] == 0

    def test_get_categories_counts_products_not_records(
        self,
        client,
        auth_headers,
        test_category,
        test_item,
        test_storage_location,
    ):
        """A tin on five shelves is one product: the card says "products".

        Canned goods read 41 for four products, because every record of
        stock — a shelf, a batch — was counted as one.
        """
        for _ in range(5):
            created = client.post(
                '/api/v1/items',
                headers=auth_headers,
                json={
                    'name': 'Tuna in Oil',
                    'quantity': 1,
                    'location_id': str(test_storage_location.id),
                    'category_id': str(test_category.id),
                },
            )
            assert created.status_code == 201, created.text

        response = client.get(
            '/api/v1/categories?with_counts=true', headers=auth_headers
        )

        category = next(
            c for c in response.json()['items'] if c['id'] == str(test_category.id)
        )
        # Five records of the tin, plus the fixture's own record without a
        # card, which is a product of its own.
        assert category['items_count'] == 2

    def test_get_categories_exclude_module_contexts(
        self, client, auth_headers, db_session
    ):
        """exclude_module_contexts hides categories claimed by enabled modules."""
        from app.models.category import Category

        # Equipment category — claimed by the equipment module
        equip_cat = Category(
            name='Power Tools',
            context_tag='equipment',
            organization_id=None,
        )
        # Food category — not claimed by any module
        food_cat = Category(
            name='Dairy',
            context_tag=None,
            organization_id=None,
        )
        db_session.add_all([equip_cat, food_cat])
        db_session.commit()

        # Without exclusion: both visible
        resp_all = client.get('/api/v1/categories', headers=auth_headers)
        names_all = {c['name'] for c in resp_all.json()['items']}
        assert 'Power Tools' in names_all
        assert 'Dairy' in names_all

        # With exclusion: equipment hidden, food visible
        resp_scoped = client.get(
            '/api/v1/categories?exclude_module_contexts=true', headers=auth_headers
        )
        names_scoped = {c['name'] for c in resp_scoped.json()['items']}
        assert 'Power Tools' not in names_scoped
        assert 'Dairy' in names_scoped


@pytest.mark.integration
class TestCategoriesCreate:
    """Tests for category creation endpoint."""

    def test_create_category_success(self, client, auth_headers):
        """Tests successful category creation."""
        response = client.post(
            '/api/v1/categories',
            headers=auth_headers,
            json={
                'name': 'New Category',
                'icon': '🥩',
                'sort_order': 10,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'New Category'
        assert 'category_type' not in data
        assert data['icon'] == '🥩'
        assert data['sort_order'] == 10

    def test_create_category_minimal(self, client, auth_headers):
        """Tests creating category with minimal data."""
        response = client.post(
            '/api/v1/categories',
            headers=auth_headers,
            json={'name': 'Minimal Category'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Minimal Category'
        assert data['sort_order'] == 0  # default value

    def test_create_category_duplicate_name(self, client, auth_headers, test_category):
        """Tests creating category with existing name."""
        response = client.post(
            '/api/v1/categories',
            headers=auth_headers,
            json={'name': test_category.name},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'already exists' in response.json()['detail']['message']

    def test_a_refused_duplicate_carries_one_code_in_every_language(
        self, client, auth_headers, test_category
    ):
        """A client branches on ``code``; only ``message`` follows the language.

        The router catches the service's refusal itself, and wrapping its text
        in a bare ``ValidationException`` answered ``VALIDATION_ERROR`` for it.
        """
        details = {}
        for lang in ('en', 'pl'):
            response = client.post(
                '/api/v1/categories',
                headers={**auth_headers, 'Accept-Language': lang},
                json={'name': test_category.name},
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            details[lang] = response.json()['detail']

        assert details['en']['code'] == details['pl']['code'] == 'CATEGORY_NAME_TAKEN'
        assert details['pl']['message'] == 'Kategoria o tej nazwie już istnieje'
        assert details['pl']['lang'] == 'pl'

    def test_an_unknown_field_type_is_refused_without_pydantics_words(
        self, client, auth_headers
    ):
        """The service builds the DTO, and pydantic refuses the field's type.

        The router caught that ``ValueError`` itself and answered with its
        text: a Polish reader got "1 validation error for CategoryCreate",
        the echoed input and a link to pydantic's docs. A library's text is
        the global handler's to answer, in the reader's language.
        """
        response = client.post(
            '/api/v1/categories',
            headers={**auth_headers, 'Accept-Language': 'pl'},
            json={
                'name': 'Spiżarnia',
                'field_definitions': [{'key': 'tags', 'type': 'multi_select'}],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail'] == {
            'code': 'VALIDATION_ERROR',
            'message': 'Nieprawidłowe dane',
            'lang': 'pl',
        }

    def test_a_new_select_without_options_names_the_options(self, client, auth_headers):
        """The validator's own refusal is a sentence we wrote, keyed.

        Unlike an unknown type, which only pydantic can describe, the empty
        options list is refused by our validator with a catalogue key; the
        ``ValidationError`` around it is pydantic's envelope, not its words.
        """
        response = client.post(
            '/api/v1/categories',
            headers={**auth_headers, 'Accept-Language': 'pl'},
            json={
                'name': 'Śruby',
                'field_definitions': [
                    {'key': 'size', 'type': 'multi-select', 'label': 'Size'}
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail']['code'] == 'FIELD_OPTIONS_REQUIRED'

    def test_create_category_unauthorized(self, client):
        """Tests creating category without authorization."""
        response = client.post('/api/v1/categories', json={'name': 'Category'})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestCategoryDetails:
    """Tests for category details endpoint."""

    def test_get_category_success(self, client, auth_headers, test_category):
        """Tests successful category details fetching."""
        response = client.get(
            f'/api/v1/categories/{test_category.id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(test_category.id)
        assert data['name'] == test_category.name

    def test_get_category_not_found(self, client, auth_headers):
        """Tests fetching non-existent category."""
        from uuid import uuid4

        response = client.get(f'/api/v1/categories/{uuid4()}', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestCategoryUpdate:
    """Tests for category update endpoint."""

    def test_update_category_success(self, client, auth_headers, test_category):
        """Tests successful category update."""
        response = client.put(
            f'/api/v1/categories/{test_category.id}',
            headers=auth_headers,
            json={'name': 'Updated Category', 'icon': '🍖'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'Updated Category'
        assert data['icon'] == '🍖'

    def test_update_category_partial(self, client, auth_headers, test_category):
        """Tests partial category update."""
        response = client.put(
            f'/api/v1/categories/{test_category.id}',
            headers=auth_headers,
            json={'icon': '🍕'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['icon'] == '🍕'
        assert data['name'] == test_category.name  # unchanged

    def test_update_category_not_found(self, client, auth_headers):
        """Tests updating non-existent category."""
        from uuid import uuid4

        response = client.put(
            f'/api/v1/categories/{uuid4()}',
            headers=auth_headers,
            json={'name': 'New Name'},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_category_with_field_definitions(
        self, client, auth_headers, db_session
    ):
        """field_definitions sent in PUT are persisted (not silently ignored)."""
        from app.models.category import Category

        test_user_obj = db_session.scalars(
            select(User).where(User.email == 'test@example.com')
        ).first()
        category = Category(
            name='Equipment Cat',
            organization_id=test_user_obj.organization_id,
            field_definitions=[],
        )
        db_session.add(category)
        db_session.commit()

        new_fields = [
            {'key': 'serial_number', 'type': 'text', 'label': 'Serial Number'},
            {'key': 'model', 'type': 'text', 'label': 'Model'},
        ]
        response = client.put(
            f'/api/v1/categories/{category.id}',
            headers=auth_headers,
            json={'field_definitions': new_fields},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        keys = [f['key'] for f in data['field_definitions']]
        assert 'serial_number' in keys
        assert 'model' in keys

    def test_a_select_left_without_options_names_the_options(
        self, client, auth_headers, test_category
    ):
        """A dropdown saved with an empty options list is refused for that.

        The validator's refusal reached the router wrapped in pydantic's
        ``ValidationError``, a ``ValueError``, and the router answered every
        ``ValueError`` with "Category not found": the reader lost the save and
        was told the category they were looking at did not exist.
        """
        response = client.put(
            f'/api/v1/categories/{test_category.id}',
            headers={**auth_headers, 'Accept-Language': 'pl'},
            json={
                'field_definitions': [
                    {
                        'key': 'thread_size',
                        'type': 'select',
                        'label': 'Thread size',
                        'options': [],
                    }
                ]
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail'] == {
            'code': 'FIELD_OPTIONS_REQUIRED',
            'message': 'Pole typu select wymaga niepustej listy opcji',
            'lang': 'pl',
        }

    def test_update_system_category_fork_preserves_system_fields(
        self, client, auth_headers, db_session
    ):
        """Forking a system category keeps is_system=True fields even when user sends new list."""
        from app.models.category import Category

        system_cat = Category(
            name='System Equipment',
            organization_id=None,
            field_definitions=[
                {
                    'key': 'serial_number',
                    'type': 'text',
                    'label': 'Serial Number',
                    'is_system': True,
                },
                {'key': 'model', 'type': 'text', 'label': 'Model', 'is_system': True},
            ],
        )
        db_session.add(system_cat)
        db_session.commit()

        # User sends only one field — system fields must survive in the fork
        response = client.put(
            f'/api/v1/categories/{system_cat.id}',
            headers=auth_headers,
            json={
                'field_definitions': [
                    {'key': 'custom_note', 'type': 'text', 'label': 'Note'}
                ]
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        keys = [f['key'] for f in data['field_definitions']]
        assert 'serial_number' in keys, 'System field serial_number must be preserved'
        assert 'model' in keys, 'System field model must be preserved'
        assert 'custom_note' in keys, 'User-added field must be included'

    def test_update_category_cannot_grant_is_system(
        self, client, auth_headers, db_session
    ):
        """Users cannot promote their own fields to is_system=True."""
        from app.models.category import Category

        test_user_obj = db_session.scalars(
            select(User).where(User.email == 'test@example.com')
        ).first()
        category = Category(
            name='User Cat',
            organization_id=test_user_obj.organization_id,
            field_definitions=[],
        )
        db_session.add(category)
        db_session.commit()

        response = client.put(
            f'/api/v1/categories/{category.id}',
            headers=auth_headers,
            json={
                'field_definitions': [
                    {
                        'key': 'hacked',
                        'type': 'text',
                        'label': 'Hack',
                        'is_system': True,
                    }
                ]
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        hacked_field = next(
            f for f in data['field_definitions'] if f['key'] == 'hacked'
        )
        assert not hacked_field.get('is_system'), (
            'User cannot grant is_system privilege'
        )


@pytest.mark.integration
class TestCategorySystemFieldOwnership:
    """is_system is the catalog's flag, not the caller's.

    Module declarations and seed profiles grant it; no client write path
    does. The create path must strip it exactly like the update merge
    already does, and the label of a system field is the catalog's word —
    a payload that renames one is refused, not stored where no screen
    will ever read it.
    """

    def _org_category_with_system_field(self, db_session):
        from app.models.category import Category

        test_user_obj = db_session.scalars(
            select(User).where(User.email == 'test@example.com')
        ).first()
        category = Category(
            name='Cured Meat',
            organization_id=test_user_obj.organization_id,
            field_definitions=[
                {
                    'key': 'cut_type',
                    'type': 'text',
                    'label': 'Cut type',
                    'is_system': True,
                },
                {'key': 'note', 'type': 'text', 'label': 'Note'},
            ],
        )
        db_session.add(category)
        db_session.commit()
        return category

    def test_create_category_cannot_grant_is_system(self, client, auth_headers):
        """POST carrying is_system lands 201, but the flag does not survive."""
        response = client.post(
            '/api/v1/categories',
            headers=auth_headers,
            json={
                'name': 'Forged Flag',
                'field_definitions': [
                    {
                        'key': 'asset_tag',
                        'type': 'text',
                        'label': 'My own tag',
                        'is_system': True,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        field = next(
            f for f in response.json()['field_definitions'] if f['key'] == 'asset_tag'
        )
        assert not field.get('is_system'), (
            'The client cannot forge a platform field on create'
        )

    def test_renaming_a_system_fields_label_is_refused(
        self, client, auth_headers, db_session
    ):
        """A changed label on a system field is a 400, not an invisible write."""
        category = self._org_category_with_system_field(db_session)

        response = client.put(
            f'/api/v1/categories/{category.id}',
            headers=auth_headers,
            json={
                'field_definitions': [
                    {
                        'key': 'cut_type',
                        'type': 'text',
                        'label': 'My own cut kind',
                    },
                    {'key': 'note', 'type': 'text', 'label': 'Note'},
                ]
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # The message names the field the way the modal does ('Cut type' —
        # the stored label), not by the key no screen ever showed.
        message = response.json()['detail']['message']
        assert 'Cut type' in message
        assert 'cut_type' not in message
        db_session.expire_all()
        stored = next(f for f in category.field_definitions if f['key'] == 'cut_type')
        assert stored['label'] == 'Cut type', 'The catalog keeps its word'

    def test_system_field_carrying_its_own_label_passes(
        self, client, auth_headers, db_session
    ):
        """A whole-list replace that leaves the system label alone is legal."""
        category = self._org_category_with_system_field(db_session)

        response = client.put(
            f'/api/v1/categories/{category.id}',
            headers=auth_headers,
            json={
                'field_definitions': [
                    {'key': 'cut_type', 'type': 'text', 'label': 'Cut type'},
                    {'key': 'note', 'type': 'text', 'label': 'Note v2'},
                ]
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        note = next(f for f in data['field_definitions'] if f['key'] == 'note')
        assert note['label'] == 'Note v2'
        cut = next(f for f in data['field_definitions'] if f['key'] == 'cut_type')
        assert cut['label'] == 'Cut type'

    def _org_category_with_two_system_fields(self, db_session):
        """A category shaped like the catalog's: two platform fields, one own.

        The measured report was PUT on a laptop category whose 13 fields all
        carry is_system; two stand in here, which is the same contract.
        """
        from app.models.category import Category

        test_user_obj = db_session.scalars(
            select(User).where(User.email == 'test@example.com')
        ).first()
        category = Category(
            name='Laptopish',
            organization_id=test_user_obj.organization_id,
            field_definitions=[
                {
                    'key': 'asset_tag',
                    'type': 'text',
                    'label': 'Asset Tag',
                    'required': False,
                    'is_system': True,
                },
                {
                    'key': 'model',
                    'type': 'text',
                    'label': 'Model',
                    'is_system': True,
                },
                {'key': 'note', 'type': 'text', 'label': 'Note'},
            ],
        )
        db_session.add(category)
        db_session.commit()
        return category

    def test_changing_type_and_required_without_the_label_passes(
        self, client, auth_headers, db_session
    ):
        """The measured PUT: no label in the payload, so no rename to refuse.

        Before, this request was read as a rename of "Asset Tag" to nothing
        and answered 400 'The name of the "Asset Tag" field belongs to the
        product catalog' — a refusal whose reason was untrue, since the
        client named no field. What it asked for (type, required) landed
        only when the payload echoed the raw stored label back. The stored
        name now stands untouched and the edit lands without the echo.
        """
        category = self._org_category_with_two_system_fields(db_session)

        response = client.put(
            f'/api/v1/categories/{category.id}',
            headers=auth_headers,
            json={
                'field_definitions': [
                    {'key': 'asset_tag', 'type': 'number', 'required': True}
                ]
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        asset_tag = next(
            f for f in data['field_definitions'] if f['key'] == 'asset_tag'
        )
        assert asset_tag['label'] == 'Asset Tag', 'the catalog keeps its word'
        assert asset_tag['type'] == 'number'
        assert asset_tag['required'] is True
        assert asset_tag['is_system'] is True
        # Omission is silence about the other catalog fields — they are the
        # platform's structure, not the client's to roster away.
        keys = {f['key'] for f in data['field_definitions']}
        assert 'model' in keys
        # The list is the roster of the client's OWN fields, so the user
        # field it did not name is gone. Same rule for both, honestly
        # asymmetric: your fields follow your roster, catalog fields stay.
        assert 'note' not in keys

    def test_an_empty_field_list_does_not_delete_catalog_fields(
        self, client, auth_headers, db_session
    ):
        """PUT with no fields says nothing about the catalog's fields.

        THE RESOLUTION, recorded here because the behavior looks like a
        swallow and is a pin: there is no delete verb for a catalog field in
        this contract. `field_definitions` is the roster of the client's own
        fields — its entries edit what they name and its omissions drop what
        the client owns. A catalog field is neither: it is the platform's
        structure (is_system is the catalog's flag), its name AND its
        presence belong to the catalog, and an entry cannot express "this
        one is deleted" any more than it can express a rename the lock
        already refuses. So omission is silence, not a command, and there is
        nothing here to refuse — answering 200 with the fields still in the
        body is the truth ("this write did not touch them"), where a 400
        would invent a deletion the payload never made. Refusing omission
        would also demand every client echo the whole catalog roster to
        change one field's type — exactly the echo this contract must not
        require. The UI keeps its side of the same rule: a catalog field's
        row carries no remove control ("its name and presence are fixed").
        """
        category = self._org_category_with_two_system_fields(db_session)

        response = client.put(
            f'/api/v1/categories/{category.id}',
            headers=auth_headers,
            json={'field_definitions': []},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        keys = {f['key'] for f in response.json()['field_definitions']}
        assert {'asset_tag', 'model'} <= keys, 'catalog fields are pinned'
        assert 'note' not in keys, 'the roster of own fields is the client'


@pytest.mark.integration
class TestCategoryGroupLabel:
    """group_label: free-form org grouping label, stored verbatim."""

    def test_create_category_with_group_label_verbatim(self, client, auth_headers):
        """POST stores group_label exactly as typed — no enum, no upper()."""
        response = client.post(
            '/api/v1/categories',
            headers=auth_headers,
            json={'name': 'Grouped Category', 'group_label': 'Narzędzia'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['group_label'] == 'Narzędzia'

    def test_create_category_without_group_label_defaults_none(
        self, client, auth_headers
    ):
        """No group is a valid state, not missing data."""
        response = client.post(
            '/api/v1/categories',
            headers=auth_headers,
            json={'name': 'Ungrouped Category'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['group_label'] is None

    def test_update_category_group_label_not_uppercased(
        self, client, auth_headers, test_category
    ):
        """A group label is stored verbatim: a label, not an uppercase code."""
        response = client.put(
            f'/api/v1/categories/{test_category.id}',
            headers=auth_headers,
            json={'group_label': 'cold Chain'},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['group_label'] == 'cold Chain'

    def test_update_category_group_label_nullable(
        self, client, auth_headers, test_category
    ):
        """Clearing the group stores NULL."""
        response = client.put(
            f'/api/v1/categories/{test_category.id}',
            headers=auth_headers,
            json={'group_label': None},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['group_label'] is None

    def test_group_label_over_50_chars_is_422(self, client, auth_headers):
        """max_length mirrors the String(50) column — a 422, not a DB error."""
        response = client.post(
            '/api/v1/categories',
            headers=auth_headers,
            json={'name': 'Long Label Category', 'group_label': 'x' * 51},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
class TestCategoryGroupRename:
    """A group is a label repeated on categories, and one place changes it.

    Before this there was nowhere to rename a group: the only route was to
    open every category carrying it, and the food profile seeds a dozen or
    more per group.
    """

    @staticmethod
    def _make(client, auth_headers, name: str, group: str | None) -> str:
        response = client.post(
            '/api/v1/categories',
            headers=auth_headers,
            json={'name': name, 'group_label': group},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        return response.json()['id']

    def test_renaming_a_group_renames_it_on_every_category_in_it(
        self, client, auth_headers
    ):
        first = self._make(client, auth_headers, 'Milk things', 'COLD')
        second = self._make(client, auth_headers, 'Cheese things', 'COLD')
        untouched = self._make(client, auth_headers, 'Flour things', 'DRY')

        response = client.patch(
            '/api/v1/categories/groups',
            headers=auth_headers,
            json={'current_name': 'COLD', 'new_name': 'Chłodnia'},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['updated'] == 2
        listed = client.get('/api/v1/categories', headers=auth_headers).json()['items']
        by_id = {c['id']: c for c in listed}
        assert by_id[first]['group_label'] == 'Chłodnia'
        assert by_id[second]['group_label'] == 'Chłodnia'
        assert by_id[untouched]['group_label'] == 'DRY'

    def test_a_group_can_be_taken_off_the_categories_that_carry_it(
        self, client, auth_headers
    ):
        category = self._make(client, auth_headers, 'Loose things', 'SHELF')

        response = client.patch(
            '/api/v1/categories/groups',
            headers=auth_headers,
            json={'current_name': 'SHELF', 'new_name': None},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        listed = client.get('/api/v1/categories', headers=auth_headers).json()['items']
        by_id = {c['id']: c for c in listed}
        # The category stays; it simply stops being grouped.
        assert by_id[category]['group_label'] is None
        assert by_id[category]['name'] == 'Loose things'

    def test_a_removed_group_is_put_back_by_the_ids_the_removal_returned(
        self, client, auth_headers
    ):
        first = self._make(client, auth_headers, 'Undo one', 'UNDOGROUP')
        second = self._make(client, auth_headers, 'Undo two', 'UNDOGROUP')
        bystander = self._make(client, auth_headers, 'Undo bystander', None)

        removed = client.patch(
            '/api/v1/categories/groups',
            headers=auth_headers,
            json={'current_name': 'UNDOGROUP', 'new_name': None},
        )
        assert removed.status_code == status.HTTP_200_OK, removed.text
        assert set(removed.json()['category_ids']) == {first, second}

        restored = client.patch(
            '/api/v1/categories/groups',
            headers=auth_headers,
            json={
                'current_name': 'UNDOGROUP',
                'new_name': 'UNDOGROUP',
                'category_ids': removed.json()['category_ids'],
            },
        )

        assert restored.status_code == status.HTTP_200_OK, restored.text
        listed = client.get('/api/v1/categories', headers=auth_headers).json()['items']
        by_id = {c['id']: c for c in listed}
        assert by_id[first]['group_label'] == 'UNDOGROUP'
        assert by_id[second]['group_label'] == 'UNDOGROUP'
        assert by_id[bystander]['group_label'] is None

    def test_a_blank_new_name_means_no_group_rather_than_an_empty_one(
        self, client, auth_headers
    ):
        category = self._make(client, auth_headers, 'Blank things', 'BLANKGROUP')

        response = client.patch(
            '/api/v1/categories/groups',
            headers=auth_headers,
            json={'current_name': 'BLANKGROUP', 'new_name': '   '},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        listed = client.get('/api/v1/categories', headers=auth_headers).json()['items']
        by_id = {c['id']: c for c in listed}
        assert by_id[category]['group_label'] is None

    def test_a_group_nobody_is_in_is_a_404(self, client, auth_headers):
        response = client.patch(
            '/api/v1/categories/groups',
            headers=auth_headers,
            json={'current_name': 'NOSUCHGROUP', 'new_name': 'Something'},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_the_route_is_not_read_as_a_category_id(self, client, auth_headers):
        """A route segment that is a word, where `/categories/{id}` expects an id."""
        self._make(client, auth_headers, 'Routed things', 'ROUTED')

        response = client.patch(
            '/api/v1/categories/groups',
            headers=auth_headers,
            json={'current_name': 'ROUTED', 'new_name': 'Still routed'},
        )

        assert response.status_code == status.HTTP_200_OK, response.text


@pytest.mark.integration
class TestCategoryDelete:
    """Tests for category deletion endpoint."""

    @pytest.mark.asyncio
    async def test_delete_category_success(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """Tests successful category deletion."""
        from app.models.category import Category

        db = real_async_db_session
        category = Category(
            name='To Delete',
            organization_id=async_test_user.organization_id,
        )
        db.add(category)
        await db.commit()

        headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(async_test_user.id)})}'
        }
        response = await real_async_client.delete(
            f'/api/v1/categories/{category.id}', headers=headers
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_category_not_found(self, client, auth_headers):
        """Tests deleting non-existent category."""
        from uuid import uuid4

        response = client.delete(f'/api/v1/categories/{uuid4()}', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_category_in_use_refuses_in_ui_language(
        self, client, auth_headers, db_session, test_user, test_item
    ):
        """The refusal travels in the interface's language, not English.

        The backend used to raise a plain English f-string here, so a reader
        working in Polish got the one sentence that mattered — why the delete
        failed — in a language the rest of their screen does not speak.
        """
        from app.models.category import Category

        category = Category(
            name='In use',
            organization_id=test_user.organization_id,
        )
        db_session.add(category)
        db_session.flush()
        test_item.category_id = category.id
        db_session.commit()

        response = client.delete(
            f'/api/v1/categories/{category.id}',
            headers={**auth_headers, 'Accept-Language': 'pl'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']
        assert 'Cannot delete' not in str(detail)
        assert 'Nie można usunąć kategorii' in detail['message']
