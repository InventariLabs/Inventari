"""Unit tests for CategoryFieldDefinition schema.

The ``type`` Literal is extended to include ``money``, ``multi-select``,
``textarea``, and ``file``. The full closed set is documented in
``CategoryFieldDefinition.FieldType`` and used by both the model validator and any
code that branches on field type.
"""

import pytest
from pydantic import ValidationError

from app.schemas.category import CategoryFieldDefinition, FieldDefinitionCreate

# The closed set of supported field types. Every code that
# branches on field type (frontend renderer, backend validator, registry
# endpoint) must agree with this list. Update FIELD_TYPE in
# neutralBaseFields.ts on the frontend when this changes.
EXPECTED_FIELD_TYPES = {
    'text',
    'number',
    'date',
    'select',
    'boolean',
    'textarea',
    'file',
    'money',
    'multi-select',
}


class TestFieldDefinitionTypes:
    """The Phase-2 extension: all new field types validate on the schema."""

    def test_text_type_passes(self):
        f = CategoryFieldDefinition(key='author', type='text', label='Author')
        assert f.type == 'text'

    def test_number_type_passes(self):
        f = CategoryFieldDefinition(key='weight', type='number', label='Weight')
        assert f.type == 'number'

    def test_date_type_passes(self):
        f = CategoryFieldDefinition(key='best_before', type='date', label='Best before')
        assert f.type == 'date'

    def test_select_type_passes(self):
        f = CategoryFieldDefinition(
            key='lactose_free',
            type='select',
            label='Lactose free',
            options=['No', 'Yes'],
        )
        assert f.type == 'select'
        assert f.options == ['No', 'Yes']

    def test_boolean_type_passes(self):
        f = CategoryFieldDefinition(key='is_organic', type='boolean', label='Organic')
        assert f.type == 'boolean'

    def test_textarea_type_passes(self):
        f = CategoryFieldDefinition(key='notes', type='textarea', label='Notes')
        assert f.type == 'textarea'

    def test_file_type_passes(self):
        f = CategoryFieldDefinition(key='manual', type='file', label='Manual')
        assert f.type == 'file'

    def test_money_type_passes(self):
        # Used for a deposit, purchase_price, insurance_value, …
        f = CategoryFieldDefinition(key='deposit', type='money', label='Deposit')
        assert f.type == 'money'

    def test_multi_select_type_passes(self):
        # Used for allergens, hazard classes, asset tags
        f = CategoryFieldDefinition(
            key='allergens',
            type='multi-select',
            label='Allergens',
            options=['Gluten', 'Dairy', 'Nuts'],
        )
        assert f.type == 'multi-select'
        assert f.options == ['Gluten', 'Dairy', 'Nuts']

    def test_unknown_type_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            CategoryFieldDefinition(key='x', type='markdown', label='X')
        # Pydantic's error message mentions the offending value
        assert 'markdown' in str(exc_info.value)

    def test_empty_type_defaults_to_text(self):
        # Backward compat: legacy/system fields without a type default to 'text'.
        f = CategoryFieldDefinition(key='legacy')
        assert f.type == 'text'

    @pytest.mark.parametrize('type_name', sorted(EXPECTED_FIELD_TYPES))
    def test_every_expected_type_passes(self, type_name: str):
        """Regression: the closed set is exactly the documented one.

        If someone adds a new type to the Literal but forgets to update
        ``EXPECTED_FIELD_TYPES`` here, this test catches the drift.
        """
        # select / multi-select require a non-empty options list (per
        # CategoryFieldDefinition._validate_type_specific_requirements).
        opts = ['a', 'b'] if type_name in {'select', 'multi-select'} else None
        f = CategoryFieldDefinition(
            key=f'k_{type_name}', type=type_name, label='L', options=opts
        )
        assert f.type == type_name

    def test_field_type_alias_for_internal_use(self):
        """Expose the closed set as a class attribute for code that needs to
        iterate (e.g. the FieldBuilder's type selector)."""
        # CategoryFieldDefinition.FIELD_TYPES is the alias; should match EXPECTED_FIELD_TYPES.
        assert hasattr(CategoryFieldDefinition, 'FIELD_TYPES'), (
            'CategoryFieldDefinition must expose the closed set as FIELD_TYPES'
        )
        assert set(CategoryFieldDefinition.FIELD_TYPES) == EXPECTED_FIELD_TYPES


class TestFieldDefinitionLenientRead:
    """Legacy data: CategoryFieldDefinition must accept empty ``options`` for
    select / multi-select on read paths. The strict rule lives in
    :class:`FieldDefinitionCreate` and is enforced at the API write
    boundary only. This is the fix for the regression that broke
    GET /items responses when ``categories.field_definitions`` JSONB
    contained legacy rows with ``options=[]``.
    """

    def test_select_with_empty_options_passes(self):
        f = CategoryFieldDefinition(
            key='equipment_status',
            type='select',
            label='Status',
            options=[],
        )
        assert f.type == 'select'
        assert f.options == []

    def test_multi_select_with_empty_options_passes(self):
        f = CategoryFieldDefinition(
            key='allergens',
            type='multi-select',
            label='Allergens',
            options=[],
        )
        assert f.type == 'multi-select'
        assert f.options == []

    def test_select_with_options_passes(self):
        f = CategoryFieldDefinition(
            key='status',
            type='select',
            label='Status',
            options=['AVAILABLE', 'DEPLOYED'],
        )
        assert f.options == ['AVAILABLE', 'DEPLOYED']


class TestFieldDefinitionCreateStrict:
    """The strict write shape: options is required for select/multi-select."""

    def test_select_with_empty_options_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            FieldDefinitionCreate(
                key='status',
                type='select',
                label='Status',
                options=[],
            )
        assert 'non-empty list of options' in str(exc_info.value)

    def test_multi_select_with_empty_options_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            FieldDefinitionCreate(
                key='allergens',
                type='multi-select',
                label='Allergens',
                options=[],
            )
        assert 'non-empty list of options' in str(exc_info.value)

    def test_select_with_options_accepted(self):
        f = FieldDefinitionCreate(
            key='status',
            type='select',
            label='Status',
            options=['AVAILABLE'],
        )
        assert f.options == ['AVAILABLE']

    def test_text_type_does_not_require_options(self):
        # text/number/date/boolean/textarea/file/money: no options needed.
        for t in ('text', 'number', 'date', 'boolean', 'textarea', 'file', 'money'):
            f = FieldDefinitionCreate(key=f'k_{t}', type=t, label='L')
            assert f.type == t
            assert f.options is None
