"""Unit tests for field value validation.

The new field types have richer value shapes than the legacy
primitives:

  - ``money``       value: ``{amount: number, currency: str}``
  - ``multi-select`` value: ``string[]`` (each element must be in field.options)

``validate_field_value`` (under test) is the single helper that:
  1. Routes by field type.
  2. Enforces the value-shape contract.
  3. Returns a structured error (``FieldValueError``) on failure so callers
     can surface field-level diagnostics in the API response.
"""

import pytest
from pydantic import ValidationError

from app.schemas.category import CategoryFieldDefinition
from app.services.fields.validation import (
    FieldValueError,
    validate_field_value,
)

# ── CategoryFieldDefinition type-specific requirements ─────────────────────────


class TestFieldDefinitionRequirements:
    """``select`` / ``multi-select`` must declare ``options``."""

    def test_select_with_options_passes(self):
        f = CategoryFieldDefinition(
            key='lactose', type='select', label='Lactose', options=['Yes', 'No']
        )
        assert f.options == ['Yes', 'No']

    def test_multi_select_with_options_passes(self):
        f = CategoryFieldDefinition(
            key='allergens',
            type='multi-select',
            label='Allergens',
            options=['Gluten', 'Dairy', 'Nuts'],
        )
        assert f.options == ['Gluten', 'Dairy', 'Nuts']

    def test_multi_select_without_options_rejected(self):
        # The strict rule lives on FieldDefinitionCreate (API write boundary);
        # the lenient CategoryFieldDefinition (read shape) accepts it.
        from app.schemas.category import FieldDefinitionCreate

        with pytest.raises(ValidationError) as exc_info:
            FieldDefinitionCreate(key='allergens', type='multi-select', label='A')
        assert 'options' in str(exc_info.value).lower()

    def test_multi_select_with_empty_options_rejected(self):
        from app.schemas.category import FieldDefinitionCreate

        with pytest.raises(ValidationError) as exc_info:
            FieldDefinitionCreate(
                key='allergens',
                type='multi-select',
                label='A',
                options=[],
            )
        assert 'options' in str(exc_info.value).lower()

    def test_money_field_accepts_optional_default_currency(self):
        f = CategoryFieldDefinition(key='deposit', type='money', label='Deposit')
        assert f.type == 'money'
        # default_currency is optional; org-level currency is the fallback.
        assert getattr(f, 'default_currency', None) is None

    def test_money_field_accepts_default_currency(self):
        f = CategoryFieldDefinition(
            key='deposit',
            type='money',
            label='Deposit',
            default_currency='EUR',
        )
        assert f.default_currency == 'EUR'


# ── validate_field_value helper ────────────────────────────────────────


@pytest.fixture
def multi_select_field() -> CategoryFieldDefinition:
    return CategoryFieldDefinition(
        key='allergens',
        type='multi-select',
        label='Allergens',
        options=['Gluten', 'Dairy', 'Nuts'],
    )


@pytest.fixture
def money_field() -> CategoryFieldDefinition:
    return CategoryFieldDefinition(key='deposit', type='money', label='Deposit')


@pytest.fixture
def select_field() -> CategoryFieldDefinition:
    return CategoryFieldDefinition(
        key='lactose', type='select', label='Lactose', options=['Yes', 'No']
    )


class TestValidateFieldValueMultiSelect:
    def test_valid_list_passes(self, multi_select_field):
        validate_field_value(multi_select_field, ['Gluten', 'Dairy'])

    def test_empty_list_passes(self, multi_select_field):
        # User hasn't selected any allergens — that's valid.
        validate_field_value(multi_select_field, [])

    def test_value_not_in_options_rejected(self, multi_select_field):
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(multi_select_field, ['Gluten', 'Soy'])
        assert exc_info.value.key == 'field_option_not_allowed'
        assert 'Soy' in str(exc_info.value)
        assert 'Allergens' in str(exc_info.value)

    def test_non_list_rejected(self, multi_select_field):
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(multi_select_field, 'Gluten')
        assert exc_info.value.key == 'field_multi_select_shape'

    def test_non_string_element_rejected(self, multi_select_field):
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(multi_select_field, ['Gluten', 42])
        assert exc_info.value.key == 'field_multi_select_shape'

    def test_none_passes_when_not_required(self, multi_select_field):
        # None means "not set" — only rejected if field.required.
        validate_field_value(multi_select_field, None)


class TestValidateFieldValueMoney:
    def test_valid_dict_passes(self, money_field):
        validate_field_value(money_field, {'amount': 5.0, 'currency': 'EUR'})

    def test_integer_amount_passes(self, money_field):
        validate_field_value(money_field, {'amount': 5, 'currency': 'USD'})

    def test_zero_amount_passes(self, money_field):
        # Free items / zero-value deposits are valid.
        validate_field_value(money_field, {'amount': 0, 'currency': 'PLN'})

    def test_negative_amount_passes(self, money_field):
        # Refunds are negative — model allows it.
        validate_field_value(money_field, {'amount': -5, 'currency': 'PLN'})

    def test_missing_amount_rejected(self, money_field):
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(money_field, {'currency': 'EUR'})
        assert exc_info.value.key == 'field_money_shape'

    def test_missing_currency_rejected(self, money_field):
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(money_field, {'amount': 5})
        assert exc_info.value.key == 'field_money_shape'

    def test_non_numeric_amount_rejected(self, money_field):
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(money_field, {'amount': '5', 'currency': 'EUR'})
        assert exc_info.value.key == 'field_money_amount'

    def test_empty_currency_rejected(self, money_field):
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(money_field, {'amount': 5, 'currency': ''})
        assert exc_info.value.key == 'field_money_currency'

    def test_non_3letter_currency_rejected(self, money_field):
        # ISO 4217 codes are 3 uppercase letters. We validate the shape only;
        # the exhaustive code list is a future enhancement.
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(money_field, {'amount': 5, 'currency': 'EURO'})
        assert exc_info.value.key == 'field_money_currency'

    def test_dict_with_extra_keys_rejected(self, money_field):
        # Forbid noise: extras like 'note' or 'tax' would be silently ignored
        # and confuse aggregation. Reject and force the caller to be explicit.
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(
                money_field, {'amount': 5, 'currency': 'EUR', 'tax': 1}
            )
        assert exc_info.value.key == 'field_money_shape'

    def test_non_dict_rejected(self, money_field):
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(money_field, 5)
        assert exc_info.value.key == 'field_money_shape'


class TestValidateFieldValueSelect:
    def test_valid_value_passes(self, select_field):
        validate_field_value(select_field, 'Yes')

    def test_invalid_value_rejected(self, select_field):
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(select_field, 'Maybe')
        assert exc_info.value.key == 'field_option_not_allowed'
        assert 'Maybe' in str(exc_info.value)

    def test_non_string_value_rejected(self, select_field):
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(select_field, 42)
        assert exc_info.value.key == 'field_select_shape'


class TestValidateFieldValueRequired:
    def test_required_field_none_rejected(self):
        f = CategoryFieldDefinition(
            key='allergens',
            type='multi-select',
            label='Allergens',
            options=['Gluten'],
            required=True,
        )
        with pytest.raises(FieldValueError) as exc_info:
            validate_field_value(f, None)
        assert exc_info.value.key == 'custom_field_required'

    def test_optional_field_none_passes(self, multi_select_field):
        validate_field_value(multi_select_field, None)


class TestFieldValueErrorShape:
    def test_error_carries_field_key_and_choice(self):
        f = CategoryFieldDefinition(
            key='allergens',
            type='multi-select',
            label='Allergens',
            options=['Gluten'],
        )
        try:
            validate_field_value(f, ['Soy'])
        except FieldValueError as exc:
            assert exc.field_key == 'allergens'
            assert exc.options == ['Gluten']
            assert exc.value == 'Soy'
        else:
            pytest.fail('expected FieldValueError')
