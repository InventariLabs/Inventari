"""
Unit tests for Pydantic schemas.

Tests verify correctness of validation, conversion and data mapping
in Pydantic schemas for various application models.
"""

from datetime import date
from uuid import uuid4

import pytest

from app.schemas.item import (
    ItemCreate,
    ItemMove,
    ItemQuantityUpdate,
    ItemUpdate,
)
from app.schemas.user import Token, TokenData, UserCreate, UserUpdate


@pytest.mark.unit
class TestUserSchemas:
    """Tests for user schemas."""

    def test_user_create_valid(self):
        """Verifies that valid user data is validated."""
        data = {
            'email': 'test@example.com',
            'password': 'Testpassword123',
            'full_name': 'Test User',
        }
        user = UserCreate(**data)

        assert user.email == 'test@example.com'
        assert user.password == 'Testpassword123'
        assert user.full_name == 'Test User'

    def test_user_create_without_full_name(self):
        """Verifies that user creation without name is possible."""
        data = {'email': 'test@example.com', 'password': 'Testpassword123'}
        user = UserCreate(**data)

        assert user.email == 'test@example.com'
        assert user.password == 'Testpassword123'
        assert user.full_name is None

    def test_user_update_partial(self):
        """Verifies that partial user update works."""
        data = {'full_name': 'Updated Name'}
        user_update = UserUpdate(**data)

        assert user_update.full_name == 'Updated Name'
        assert user_update.password is None

    def test_token_schema(self):
        """Verifies that token schema works."""
        data = {'access_token': 'test_token_123', 'token_type': 'bearer'}
        token = Token(**data)

        assert token.access_token == 'test_token_123'
        assert token.token_type == 'bearer'

    def test_token_data_schema(self):
        """Verifies that TokenData schema works."""
        user_id = uuid4()
        data = {'user_id': user_id}
        token_data = TokenData(**data)

        assert token_data.user_id == user_id


@pytest.mark.unit
class TestItemSchemas:
    """Tests for item schemas."""

    def test_item_create_valid(self):
        """Verifies that valid item data is validated."""
        storage_id = uuid4()
        category_id = uuid4()
        data = {
            'name': 'Test Product',
            'brand': 'Test Brand',
            'quantity': 2,
            'expiry_date': date.today(),
            'freeze_date': date.today(),
            'shelf_location': 'Shelf 1',
            'location_id': storage_id,
            'category_id': category_id,
        }
        item = ItemCreate(**data)

        assert item.name == 'Test Product'
        assert item.brand == 'Test Brand'
        assert item.quantity == 2

    def test_item_create_minimal(self):
        """Verifies that minimal item data is validated."""
        storage_id = uuid4()
        data = {'name': 'Test Product', 'location_id': storage_id}
        item = ItemCreate(**data)

        assert item.name == 'Test Product'
        assert item.location_id == storage_id
        assert item.quantity == 1  # default value

    def test_item_empty_string_to_none(self):
        """Verifies that empty strings are converted to None."""
        data = {
            'name': 'Test Product',
            'brand': '',
            'shelf_location': '',
            'location_id': uuid4(),
        }
        item = ItemCreate(**data)

        assert item.brand is None
        assert item.shelf_location is None

    def test_item_empty_date_to_none(self):
        """Verifies that empty dates are converted to None."""
        data = {
            'name': 'Test Product',
            'expiry_date': '',
            'freeze_date': '',
            'location_id': uuid4(),
        }
        item = ItemCreate(**data)

        assert item.expiry_date is None
        assert item.freeze_date is None

    def test_item_update_partial(self):
        """Verifies that partial item update works."""
        data = {'name': 'Updated Name'}
        item_update = ItemUpdate(**data)

        assert item_update.name == 'Updated Name'
        assert item_update.brand is None
        assert item_update.quantity is None

    def test_item_move_schema(self):
        """Verifies that item move schema works."""
        to_storage_id = uuid4()
        data = {
            'to_location_id': to_storage_id,
            'notes': 'Moved to another fridge',
        }
        item_move = ItemMove(**data)

        assert item_move.to_location_id == to_storage_id
        assert item_move.notes == 'Moved to another fridge'

    def test_item_quantity_update_schema(self):
        """Verifies that quantity update schema works."""
        data = {'quantity': 5}
        quantity_update = ItemQuantityUpdate(**data)

        assert quantity_update.quantity == 5


@pytest.mark.unit
class TestSchemaValidation:
    """Tests for schema validation."""

    def test_item_quantity_validation_negative(self):
        """Verifies that negative quantity is rejected."""
        data = {'name': 'Test Product', 'quantity': -1, 'location_id': uuid4()}

        with pytest.raises(ValueError):
            ItemCreate(**data)
