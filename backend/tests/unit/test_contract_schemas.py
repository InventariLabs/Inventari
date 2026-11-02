"""
Contract tests for API response schemas.

Verify that Pydantic response models can correctly serialize
SQLAlchemy ORM model instances (from_attributes=True roundtrip).
Guards against schema drift — if a DB column or relationship is renamed
and the schema is not updated accordingly, these tests will catch it.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake
from app.modules.stock_takes.schemas import StockTakeResponse
from app.modules.webhooks.schemas import WebhookEndpointResponse
from app.schemas.category import Category as CategorySchema
from app.schemas.item import Item as ItemSchema
from app.schemas.item import ItemListResponse
from app.schemas.organization import Organization as OrganizationSchema
from app.schemas.storage_location import StorageLocation as StorageLocationSchema
from app.schemas.user import User as UserSchema

# ---------------------------------------------------------------------------
# ItemSchema contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestItemSchemaContract:
    """Verify ItemSchema can roundtrip from an Item ORM instance."""

    def test_item_schema_serializes_orm_instance(
        self,
        test_item: Item,
    ):
        """ItemSchema.model_validate must not raise on a real ORM instance."""
        schema = ItemSchema.model_validate(test_item)
        assert schema.id == test_item.id
        assert schema.name == test_item.name
        assert schema.quantity == test_item.quantity

    def test_item_schema_preserves_nullable_fields(self, test_item: Item):
        """Nullable fields must remain None when not set on the model."""
        schema = ItemSchema.model_validate(test_item)
        # category_id is set in fixture but other optional fields are None
        assert schema.label_code is None
        assert schema.freeze_date is not None  # set in fixture

    def test_item_schema_meta_data_mapped_to_metadata(self, test_item: Item):
        """The meta_data DB column must be surfaced as `metadata` in the schema."""
        schema = ItemSchema.model_validate(test_item)
        # metadata field should exist (even if None)
        assert hasattr(schema, 'metadata')

    def test_item_list_response_contract(self, test_items_batch: list[Item]):
        """ItemListResponse wraps items correctly and exposes pagination fields."""
        items_schemas = [ItemSchema.model_validate(i) for i in test_items_batch]
        response = ItemListResponse(
            items=items_schemas,
            total=len(items_schemas),
            limit=20,
            offset=0,
            has_more=False,
        )
        assert response.total == len(test_items_batch)
        assert len(response.items) == len(test_items_batch)
        assert response.limit == 20
        assert response.offset == 0
        assert response.has_more is False

    def test_item_list_response_has_more_flag(self, test_items_batch: list[Item]):
        """has_more is True when more items exist beyond current page."""
        items_schemas = [ItemSchema.model_validate(i) for i in test_items_batch]
        response = ItemListResponse(
            items=items_schemas,
            total=100,
            limit=5,
            offset=0,
            has_more=True,
        )
        assert response.has_more is True
        assert response.limit == 5


# ---------------------------------------------------------------------------
# UserSchema contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUserSchemaContract:
    """Verify UserSchema can roundtrip from a User ORM instance."""

    def test_user_schema_serializes_orm_instance(self, test_user: User):
        schema = UserSchema.model_validate(test_user)
        assert schema.id == test_user.id
        assert schema.email == test_user.email
        assert schema.full_name == test_user.full_name

    def test_user_schema_does_not_expose_password(self, test_user: User):
        """Hashed password must never appear in the response schema."""
        schema = UserSchema.model_validate(test_user)
        schema_dict = schema.model_dump()
        assert 'hashed_password' not in schema_dict
        assert 'password' not in schema_dict


# ---------------------------------------------------------------------------
# OrganizationSchema contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrganizationSchemaContract:
    def test_organization_schema_serializes_orm_instance(
        self, test_household: Organization
    ):
        schema = OrganizationSchema.model_validate(test_household)
        assert schema.id == test_household.id
        assert schema.name == test_household.name


# ---------------------------------------------------------------------------
# StorageLocationSchema contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStorageLocationSchemaContract:
    def test_storage_location_schema_serializes_orm_instance(
        self, test_storage_location: StorageLocation
    ):
        schema = StorageLocationSchema.model_validate(test_storage_location)
        assert schema.id == test_storage_location.id
        assert schema.name == test_storage_location.name

    def test_storage_location_nullable_parent_is_none(
        self, test_storage_location: StorageLocation
    ):
        """Top-level locations have no parent_id."""
        schema = StorageLocationSchema.model_validate(test_storage_location)
        assert schema.parent_id is None


# ---------------------------------------------------------------------------
# WebhookEndpointResponse contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWebhookEndpointSchemaContract:
    """
    WebhookEndpointResponse is built via _to_response() helper in the router,
    not by model_validate directly (because `has_secret` is computed).
    These tests verify that the schema structure is correct and the secret
    is never exposed in serialised output.
    """

    def _make_response(self, with_secret: bool = True) -> WebhookEndpointResponse:
        return WebhookEndpointResponse(
            id=uuid4(),
            name='Test hook',
            url='https://example.com/hook',
            has_secret=with_secret,
            http_method='POST',
            event_types=['item.created', 'item.used'],
            max_retries=3,
            retry_backoff_seconds=30,
            timeout_seconds=10,
            is_active=True,
            last_triggered_at=None,
            last_status_code=None,
            consecutive_failures=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    def test_webhook_endpoint_schema_instantiation(self):
        schema = self._make_response()
        assert schema.url == 'https://example.com/hook'
        assert schema.is_active is True
        assert schema.has_secret is True

    def test_webhook_endpoint_secret_not_exposed(self):
        """The raw secret value must never appear in the serialised schema."""
        schema = self._make_response(with_secret=True)
        schema_dict = schema.model_dump()
        # Only the boolean flag is present, not the actual secret value
        assert 'secret' not in schema_dict
        assert schema_dict['has_secret'] is True

    def test_webhook_endpoint_no_secret_reflected(self):
        schema = self._make_response(with_secret=False)
        assert schema.has_secret is False


# ---------------------------------------------------------------------------
# CategorySchema contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCategorySchemaContract:
    """Verify CategorySchema can roundtrip from a Category ORM instance."""

    def test_category_schema_serializes_orm_instance(self, test_category: Category):
        """CategorySchema.model_validate must not raise on a real ORM instance."""
        schema = CategorySchema.model_validate(test_category)
        assert schema.id == test_category.id
        assert schema.name == test_category.name

    def test_category_schema_preserves_icon(self, test_category: Category):
        """Icon field must be preserved in the schema."""
        schema = CategorySchema.model_validate(test_category)
        assert schema.icon == test_category.icon


# ---------------------------------------------------------------------------
# StockTakeResponse contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStockTakeSchemaContract:
    """Verify StockTakeResponse can roundtrip from a StockTake ORM instance."""

    def test_stock_take_response_serializes_orm_instance(
        self, test_stock_take: StockTake
    ):
        """StockTakeResponse.model_validate must not raise on a real ORM instance."""
        schema = StockTakeResponse.model_validate(test_stock_take)
        assert schema.id == test_stock_take.id
        assert schema.name == test_stock_take.name
        assert schema.status == test_stock_take.status

    def test_stock_take_response_storage_location_preserved(
        self, test_stock_take: StockTake
    ):
        """location_id must be preserved in the response schema."""
        schema = StockTakeResponse.model_validate(test_stock_take)
        assert schema.location_id == test_stock_take.storage_location_id
