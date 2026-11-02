"""Test that commonly-serialized relationships use lazy='selectin' eagerly.

These tests prevent MissingGreenlet regressions by verifying that relationships
commonly accessed during Pydantic from_attributes=True serialization survive
session detachment (expunge).

How it works:
  - Load a model via ``db_session.get()`` (uses model-level lazy='selectin')
  - Call ``db_session.expunge(model)`` to detach from the session
  - Serialize with the Pydantic schema
  - If lazy='selectin' is missing: Pydantic accesses trigger a lazy load on a
    detached object → DetachedInstanceError → test fails
  - If lazy='selectin' is set: eager-loaded data survives expunge → test passes
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item as ItemModel
from app.models.product_template import ProductTemplate as ProductTemplateModel
from app.models.storage_location import StorageLocation as StorageLocationModel
from app.models.uom import Uom
from app.models.user import User as UserModel
from app.schemas.item import Item as ItemSchema
from app.schemas.storage_location import StorageLocation as StorageLocationSchema
from app.schemas.user import User as UserSchema
from tests.integration._shelf import anchor_pending_records


@pytest.mark.integration
@pytest.mark.asyncio
class TestEagerLoadingGuards:
    async def test_item_category_is_eager_loaded(
        self, real_async_db_session: AsyncSession, async_test_item
    ):
        def _check(db):
            item = db.get(ItemModel, async_test_item.id)
            db.expunge(item)
            schema = ItemSchema.model_validate(item)
            assert schema.category is not None, (
                "Item.category not loaded — missing lazy='selectin'?"
            )

        await real_async_db_session.run_sync(_check)

    # The uom and template guards used to skip whenever the item had neither,
    # and async_test_item sets neither — so both skipped in every run. They now
    # give the item what they are about, and load it fresh: an object still in
    # the identity map would carry whatever the fixture already loaded.

    async def test_item_uom_is_eager_loaded(
        self, real_async_db_session: AsyncSession, async_test_item
    ):
        uom = await real_async_db_session.scalar(select(Uom).limit(1))
        assert uom is not None, 'the seed replay is expected to carry units'
        async_test_item.uom_id = uom.id
        await real_async_db_session.flush()

        def _check(db):
            db.expunge_all()
            item = db.get(ItemModel, async_test_item.id)
            db.expunge(item)
            schema = ItemSchema.model_validate(item)
            assert schema.uom is not None, (
                "Item.uom not loaded — missing lazy='selectin'?"
            )

        await real_async_db_session.run_sync(_check)

    async def test_item_template_is_eager_loaded(
        self, real_async_db_session: AsyncSession, async_test_item
    ):
        template = ProductTemplateModel(
            name='Eager template', organization_id=async_test_item.organization_id
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()
        async_test_item.template_id = template.id
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        def _check(db):
            db.expunge_all()
            item = db.get(ItemModel, async_test_item.id)
            db.expunge(item)
            schema = ItemSchema.model_validate(item)
            assert schema.template is not None, (
                "Item.template not loaded — missing lazy='selectin'?"
            )

        await real_async_db_session.run_sync(_check)

    async def test_storage_location_storage_type_is_eager_loaded(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        def _check(db):
            loc = db.get(StorageLocationModel, async_test_storage_location.id)
            db.expunge(loc)
            schema = StorageLocationSchema.model_validate(loc)
            assert schema.location_type is not None, (
                "storage_type not loaded — missing lazy='selectin'?"
            )

        await real_async_db_session.run_sync(_check)

    async def test_user_organization_is_eager_loaded(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        def _check(db):
            user = db.get(UserModel, async_test_user.id)
            db.expunge(user)
            schema = UserSchema.model_validate(user)
            assert schema.organization_name is not None, (
                "organization_name empty — missing lazy='selectin' on User.organization?"
            )

        await real_async_db_session.run_sync(_check)
